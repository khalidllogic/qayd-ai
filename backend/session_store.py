import json
import os
import urllib.request
import urllib.error

UPSTASH_URL = os.getenv("UPSTASH_REDIS_REST_URL", "").strip().rstrip("/")
UPSTASH_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "").strip()

# بديل محلي للعمل على جهازك بدون إنترنت
_local_store = {}


def _upstash_cmd(command: list):
    req = urllib.request.Request(
        UPSTASH_URL,
        data=json.dumps(command).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {UPSTASH_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8")).get("result")


def save_session(session_id: str, data: dict, ttl_seconds: int = 600) -> None:
    payload = json.dumps(data, ensure_ascii=False)
    if UPSTASH_URL and UPSTASH_TOKEN:
        _upstash_cmd(["SET", f"qayd:session:{session_id}", payload, "EX", ttl_seconds])
    else:
        _local_store[session_id] = data


def get_session(session_id: str) -> dict | None:
    if UPSTASH_URL and UPSTASH_TOKEN:
        raw = _upstash_cmd(["GET", f"qayd:session:{session_id}"])
        return json.loads(raw) if raw else None
    return _local_store.get(session_id)


def delete_session(session_id: str) -> None:
    if UPSTASH_URL and UPSTASH_TOKEN:
        _upstash_cmd(["DEL", f"qayd:session:{session_id}"])
    else:
        _local_store.pop(session_id, None)
