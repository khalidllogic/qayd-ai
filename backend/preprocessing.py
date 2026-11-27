from pathlib import Path

import cv2
import numpy as np


MIN_PAGE_AREA = 0.40
MAX_DETECTION_SIZE = 1400


def _has_visible_edges(gray: np.ndarray, corners: np.ndarray) -> bool:
    height, width = gray.shape
    offset = max(5.0, 0.012 * min(height, width))
    bounds = np.array([width - 1, height - 1])

    if np.any(corners < 2 * offset) or np.any(corners > bounds - 2 * offset):
        return False

    sides = np.roll(corners, -1, axis=0) - corners
    lengths = np.linalg.norm(sides, axis=1)
    if np.any(lengths < 0.12 * min(height, width)):
        return False

    directions = sides / lengths[:, None]
    adjacent_cosines = np.sum(directions * np.roll(directions, 1, axis=0), axis=1)
    if np.any(np.abs(adjacent_cosines) > 0.8):
        return False

    center = corners.mean(axis=0)
    sample_positions = np.linspace(0.15, 0.85, 16)[:, None]

    for start, side, direction in zip(corners, sides, directions):
        inward = np.array([-direction[1], direction[0]])
        if np.dot(inward, center - (start + 0.5 * side)) < 0:
            inward = -inward

        samples = start + sample_positions * side

        # A page boundary stays visible beyond the thickness of a printed line.
        for distance in (offset, 2 * offset):
            inside = np.rint(samples + distance * inward).astype(int)
            outside = np.rint(samples - distance * inward).astype(int)
            inside_values = gray[inside[:, 1], inside[:, 0]].astype(np.int16)
            outside_values = gray[outside[:, 1], outside[:, 0]].astype(np.int16)

            if np.count_nonzero(inside_values - outside_values >= 12) < 12:
                return False

    return True


def _find_page(gray: np.ndarray) -> np.ndarray | None:
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 25, 75)
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(closed, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    minimum_area = MIN_PAGE_AREA * gray.size
    page = None

    for contour in sorted(contours, key=cv2.contourArea, reverse=True):
        contour_area = cv2.contourArea(contour)
        if contour_area <= minimum_area:
            break

        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, 0.015 * perimeter, True)
        if len(polygon) != 4 or not cv2.isContourConvex(polygon):
            continue

        area = cv2.contourArea(polygon)
        if area <= minimum_area or not 0.90 <= contour_area / area <= 1.10:
            continue

        corners = polygon.reshape(4, 2).astype(np.float32)
        if not _has_visible_edges(gray, corners):
            continue

        if page is None:
            page = corners
        else:
            overlap, _ = cv2.intersectConvexConvex(page, corners)
            if overlap < 0.90 * max(cv2.contourArea(page), area):
                return None

    return page


def _rectify(image: np.ndarray, corners: np.ndarray) -> np.ndarray:
    if cv2.contourArea(corners, oriented=True) < 0:
        corners = corners[::-1]

    start = int(np.argmin(corners.sum(axis=1)))
    corners = np.roll(corners, -start, axis=0)
    top_left, top_right, bottom_right, bottom_left = corners

    horizontal = max(
        np.linalg.norm(top_right - top_left),
        np.linalg.norm(bottom_right - bottom_left),
    )
    vertical = max(
        np.linalg.norm(bottom_left - top_left),
        np.linalg.norm(bottom_right - top_right),
    )
    width, height = round(horizontal) + 1, round(vertical) + 1
    pad = max(2, round(0.01 * min(width, height)))

    target = np.float32([
        [pad, pad],
        [pad + width - 1, pad],
        [pad + width - 1, pad + height - 1],
        [pad, pad + height - 1],
    ])

    transform = cv2.getPerspectiveTransform(corners, target)
    return cv2.warpPerspective(
        image, transform, (width + 2 * pad, height + 2 * pad),
        borderMode=cv2.BORDER_REPLICATE,
    )


def preprocess_invoice(image_path: str) -> np.ndarray:
    """Return a BGR image, preserving all original pixels when detection is uncertain."""
    data = Path(image_path).read_bytes()
    if not data:
        raise ValueError("The image file is empty.")

    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("The file could not be decoded as an image.")

    height, width = image.shape[:2]
    scale = min(1.0, MAX_DETECTION_SIZE / max(width, height))
    detection = image

    if scale < 1.0:
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        detection = cv2.resize(image, size, interpolation=cv2.INTER_AREA)

    gray = cv2.cvtColor(detection, cv2.COLOR_BGR2GRAY)
    corners = _find_page(gray)
    if corners is None:
        return image

    detect_height, detect_width = gray.shape
    corners *= np.float32([width / detect_width, height / detect_height])
    return _rectify(image, corners)
