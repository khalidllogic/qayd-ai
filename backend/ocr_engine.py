import base64
import json
import os
import re
from pathlib import Path
from typing import Optional

import cv2
import httpx
import numpy as np
from dotenv import dotenv_values
from google import genai
from google.genai import errors, types
from pydantic import ValidationError

try:
    from backend.preprocessing import preprocess_invoice
    from backend.ocr_schema import REVIEW_MARKER, InvoiceData, InvoiceItem
except ImportError:
    from preprocessing import preprocess_invoice
    from ocr_schema import REVIEW_MARKER, InvoiceData, InvoiceItem


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCAL_ENV_FILE = Path(__file__).with_name(".env")
ROOT_ENV_FILE = PROJECT_ROOT / ".env"

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
GEMINI_ACTIVE_MODELS = ["gemini-3.8-flash", "gemini-3.5-flash-lite"]
DEFAULT_GROQ_MODEL = "qwen/qwen3.8-27b"
MAX_INLINE_IMAGE_BYTES = 14_000_000

OCR_PROMPT = f"""
أنت محلل بصري متخصص في قراءة الفواتير العربية (المطبوعة والمكتوبة بخط اليد). استخرج البيانات وأعدها بصيغة JSON فقط بدون أي نص إضافي، وفق الهيكل التالي:
{{
  "vendor_name": "اسم المورد أو المحل الموجود في رأس الفاتورة أو نص فارغ",
  "invoice_date": "تاريخ الفاتورة بصيغة YYYY-MM-DD أو نص فارغ",
  "invoice_number": "رقم الفاتورة أو {REVIEW_MARKER} إذا لم يوجد",
  "items": [
    {{
      "description": "اسم الصنف أو البيان المكتوب في السطر",
      "quantity": 1.0,
      "unit_price": 0.0,
      "line_total": 0.0
    }}
  ],
  "tax_amount": 0.0,
  "total_amount": 0.0,
  "tafqeet_text": "نص التفقيط بالحروف العربية إن وجد أو نص فارغ"
}}

قواعد صارمة:
1. استخرج كل سطر في جدول الفاتورة داخل قائمة "items" بدقة دون اختصار أو دمج.
2. إذا لم تُذكر الكمية أو سعر الوحدة، اجعل quantity = 1.0 و unit_price مساوياً لـ line_total.
3. حوّل جميع الأرقام إلى أرقام إنجليزية عشرية (float) داخل JSON، وانتبه للأصفار بدقة.
4. لا تقم بأي عمليات حسابية أو تصحيح من عندك؛ انقل الأرقام كما هي مكتوبة في الفاتورة حرفياً.
5. إذا كان رقم الفاتورة غير واضح أو مفقوداً ضع "{REVIEW_MARKER}" في invoice_number.
"""

TEXT_PROMPT = """
انسخ جميع النصوص العربية والإنجليزية والأرقام الموجودة في الصورة كما هي حرفياً.
حافظ على ترتيب الأسطر والفقرات، واكتب [غير واضح] مكان أي كلمة لا يمكن قراءتها.
أعد النص المستخرج فقط دون أي مقدمات أو شروحات.
"""


class InvoiceOCRError(RuntimeError):
    """The OCR request could not return a valid invoice."""


class InvoiceReviewRequired(InvoiceOCRError):
    """A required field needs human review, carrying partial extracted data."""

    def __init__(self, message: str, invoice: Optional[InvoiceData] = None) -> None:
        super().__init__(message)
        self.invoice = invoice


def _load_settings() -> dict[str, str]:
    settings: dict[str, Optional[str]] = {}
    for candidate in (ROOT_ENV_FILE, LOCAL_ENV_FILE):
        if candidate.exists():
            settings.update(dotenv_values(candidate, encoding="utf-8-sig", interpolate=False))

    return {
        "gemini_key": (settings.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip(),
        "gemini_model": (settings.get("GEMINI_MODEL") or os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL,
        "groq_key": (settings.get("GROQ_API_KEY") or os.getenv("GROQ_API_KEY") or "").strip(),
        "groq_model": (settings.get("GROQ_MODEL") or os.getenv("GROQ_MODEL") or DEFAULT_GROQ_MODEL).strip() or DEFAULT_GROQ_MODEL,
    }


def is_api_key_configured() -> bool:
    cfg = _load_settings()
    has_gemini = bool(cfg["gemini_key"] and cfg["gemini_key"] != "YOUR_API_KEY")
    has_groq = bool(cfg["groq_key"] and cfg["groq_key"] != "YOUR_API_KEY")
    return has_gemini or has_groq


def get_active_provider_label() -> str:
    cfg = _load_settings()
    if cfg["gemini_key"] and cfg["gemini_key"] != "YOUR_API_KEY":
        return f"Gemini ({cfg['gemini_model']}) + Groq Backup"
    if cfg["groq_key"] and cfg["groq_key"] != "YOUR_API_KEY":
        return f"Groq ({cfg['groq_model']})"
    return "غير مضبوط"


def _encode_image_bytes(image_path: str, *, correct_perspective: bool) -> bytes:
    if correct_perspective:
        image = preprocess_invoice(image_path)
    else:
        data = np.frombuffer(Path(image_path).read_bytes(), dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if image is None:
            raise InvoiceOCRError("تعذّر فتح أو قراءة ملف الصورة.")

    height, width = image.shape[:2]
    scale = min(1.0, 1200 / max(width, height))

    if scale < 1.0:
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        image = cv2.resize(image, size, interpolation=cv2.INTER_AREA)

    success, encoded = cv2.imencode(
        ".jpg",
        image,
        [cv2.IMWRITE_JPEG_QUALITY, 85, cv2.IMWRITE_JPEG_OPTIMIZE, 1],
    )
    if not success:
        raise InvoiceOCRError("فشل ضغط الصورة قبل الإرسال.")

    if encoded.nbytes > MAX_INLINE_IMAGE_BYTES:
        raise InvoiceOCRError("حجم الصورة كبير جداً بعد الضغط.")

    return encoded.tobytes()


def _call_gemini(
    image_bytes: bytes,
    system_prompt: str,
    user_prompt: str,
    *,
    json_mode: bool,
    api_key: str,
    primary_model: str,
) -> str:
    image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
    models_to_try = [primary_model] + [m for m in GEMINI_ACTIVE_MODELS if m != primary_model]
    last_err = "فشل الاتصال بخدمة Gemini."

    config_kwargs: dict = {
        "system_instruction": system_prompt,
        "temperature": 0.0,
    }
    if json_mode:
        config_kwargs["response_mime_type"] = "application/json"
    else:
        config_kwargs["response_mime_type"] = "text/plain"

    config = types.GenerateContentConfig(**config_kwargs)

    with genai.Client(
        api_key=api_key,
        vertexai=False,
        http_options=types.HttpOptions(timeout=25_000),
    ) as client:
        for model_name in models_to_try:
            try:
                resp = client.models.generate_content(
                    model=model_name,
                    contents=[image_part, user_prompt],
                    config=config,
                )
                if resp.text and resp.text.strip():
                    return resp.text.strip()
            except errors.APIError as err:
                last_err = f"Gemini HTTP {err.code}: {err.message}"
                continue
            except Exception as exc:
                last_err = f"Gemini Error: {type(exc).__name__}: {exc}"
                continue

    raise InvoiceOCRError(last_err)


def _call_groq(
    image_bytes: bytes,
    system_prompt: str,
    user_prompt: str,
    *,
    json_mode: bool,
    api_key: str,
    primary_model: str,
) -> str:
    b64_img = base64.b64encode(image_bytes).decode("ascii")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload: dict = {
        "model": primary_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}},
                ],
            },
        ],
        "temperature": 0.0,
        "max_tokens": 1024,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    with httpx.Client(timeout=30.0) as client:
        res = client.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
        if res.status_code == 200:
            content = res.json()["choices"][0]["message"]["content"]
            if content and content.strip():
                return content.strip()
        raise InvoiceOCRError(f"Groq HTTP {res.status_code}: {res.text[:200]}")


def _read_image_unified(
    image_path: str,
    system_prompt: str,
    user_prompt: str,
    *,
    correct_perspective: bool,
    json_mode: bool,
) -> str:
    cfg = _load_settings()
    has_gemini = bool(cfg["gemini_key"] and cfg["gemini_key"] != "YOUR_API_KEY")
    has_groq = bool(cfg["groq_key"] and cfg["groq_key"] != "YOUR_API_KEY")

    if not has_gemini and not has_groq:
        raise InvoiceOCRError("يرجى ضبط GEMINI_API_KEY أو GROQ_API_KEY في ملف .env أولاً.")

    try:
        image_bytes = _encode_image_bytes(image_path, correct_perspective=correct_perspective)
    except InvoiceOCRError:
        raise
    except (OSError, ValueError, cv2.error):
        raise InvoiceOCRError("تعذّرت معالجة الصورة المرفوعة.") from None

    errors_collected: list[str] = []

    if has_gemini:
        try:
            return _call_gemini(
                image_bytes,
                system_prompt,
                user_prompt,
                json_mode=json_mode,
                api_key=cfg["gemini_key"],
                primary_model=cfg["gemini_model"],
            )
        except InvoiceOCRError as exc:
            errors_collected.append(str(exc))

    if has_groq:
        try:
            return _call_groq(
                image_bytes,
                system_prompt,
                user_prompt,
                json_mode=json_mode,
                api_key=cfg["groq_key"],
                primary_model=cfg["groq_model"],
            )
        except InvoiceOCRError as exc:
            errors_collected.append(str(exc))

    raise InvoiceOCRError(" | ".join(errors_collected))


def _coerce_float(val) -> float:
    if isinstance(val, (int, float)):
        return float(val)
    if not val:
        return 0.0
    digits = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    cleaned = re.sub(r"[^\d.\-]", "", str(val).translate(digits))
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0


def _parse_invoice_json_safely(raw_text: str) -> InvoiceData:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.DOTALL).strip()

    try:
        parsed = InvoiceData.model_validate_json(cleaned)
        if parsed.items:
            return parsed
    except ValidationError:
        pass

    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError:
        raise InvoiceOCRError("أعاد النموذج مخرجات JSON غير صالحة.") from None

    raw_items = obj.get("items")
    if not isinstance(raw_items, list):
        for v in obj.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                raw_items = v
                break
    raw_items = raw_items or []

    norm_items: list[InvoiceItem] = []
    for it in raw_items:
        if not isinstance(it, dict):
            continue
        desc = str(it.get("description") or it.get("name") or it.get("item") or "").strip()
        lt = _coerce_float(it.get("line_total") or it.get("total") or it.get("price") or it.get("amount"))
        qty = _coerce_float(it.get("quantity") or it.get("qty")) or 1.0
        up = _coerce_float(it.get("unit_price")) or lt
        if desc or lt > 0:
            norm_items.append(
                InvoiceItem(
                    description=desc or "صنف غير محدد",
                    quantity=qty,
                    unit_price=up,
                    line_total=lt,
                )
            )

    return InvoiceData(
        vendor_name=str(obj.get("vendor_name") or obj.get("vendor") or "").strip(),
        invoice_date=str(obj.get("invoice_date") or obj.get("date") or "").strip(),
        invoice_number=str(obj.get("invoice_number") or "").strip(),
        items=norm_items,
        tax_amount=_coerce_float(obj.get("tax_amount") or obj.get("tax")),
        total_amount=_coerce_float(obj.get("total_amount") or obj.get("grand_total") or obj.get("total")),
        tafqeet_text=str(obj.get("tafqeet_text") or "").strip(),
    )


def extract_invoice(image_path: str) -> InvoiceData:
    response_text = _read_image_unified(
        image_path,
        OCR_PROMPT,
        "استخرج جميع بيانات الفاتورة من هذه الصورة وأعدها بصيغة JSON فقط.",
        correct_perspective=True,
        json_mode=True,
    )

    invoice = _parse_invoice_json_safely(response_text)

    identity_fields = (invoice.vendor_name, invoice.invoice_date, invoice.invoice_number)
    if invoice.invoice_number.strip() == REVIEW_MARKER or not all(
        value.strip() for value in identity_fields
    ):
        raise InvoiceReviewRequired(
            "بعض الحقول الأساسية غير واضحة أو ناقصة وتتطلب مراجعة يدوية.",
            invoice=invoice,
        )

    return invoice


def extract_text(image_path: str) -> str:
    return _read_image_unified(
        image_path,
        TEXT_PROMPT,
        "انسخ جميع النصوص والأرقام الموجودة في الصورة بدقة.",
        correct_perspective=False,
        json_mode=False,
    )