import base64
import io
import secrets
import socket
import time
from typing import Optional

import qrcode
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response

router = APIRouter()

# تخزين الجلسات المؤقتة في الذاكرة: {session_id: {...}}
MOBILE_SESSIONS: dict[str, dict] = {}
SESSION_TTL_SECONDS = 1800  # 30 دقيقة


def _cleanup_expired() -> None:
    now = time.time()
    expired = [k for k, v in MOBILE_SESSIONS.items() if now - v["created_at"] > SESSION_TTL_SECONDS]
    for k in expired:
        MOBILE_SESSIONS.pop(k, None)


def get_local_ips() -> list[str]:
    ips: list[str] = []
    # محاولة اكتشاف الـ IP النشط عبر جدول التوجيه
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            primary_ip = s.getsockname()[0]
            if primary_ip and not primary_ip.startswith("127."):
                ips.append(primary_ip)
    except Exception:
        pass

    # جمع بقية عناوين IPv4 المحلية (Wi-Fi / Hotspot)
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in ips:
                # إعطاء أولوية لشبكات Wi-Fi و Hotspot المعتادة
                if ip.startswith(("192.168.", "10.", "172.")):
                    ips.append(ip)
    except Exception:
        pass

    return ips or ["127.0.0.1"]


@router.get("/api/mobile/network-info")
def mobile_network_info(request: Request):
    ips = get_local_ips()
    port = request.url.port or 8000
    return {"ips": ips, "default_ip": ips[0], "port": port}


@router.post("/api/mobile/session")
def create_mobile_session():
    _cleanup_expired()
    session_id = secrets.token_urlsafe(6)
    MOBILE_SESSIONS[session_id] = {
        "created_at": time.time(),
        "status": "waiting",  # waiting | uploaded
        "filename": None,
        "content_type": None,
        "image_b64": None,
    }
    return {"session_id": session_id}


@router.get("/api/mobile/qr")
def generate_qr_image(url: str):
    qr = qrcode.QRCode(version=1, box_size=8, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0f172a", back_color="#ffffff")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@router.get("/api/mobile/session/{session_id}/status")
def get_session_status(session_id: str):
    session = MOBILE_SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="انتهت صلاحية الجلسة.")
    if session["status"] == "uploaded" and session["image_b64"]:
        return {
            "status": "uploaded",
            "filename": session["filename"],
            "content_type": session["content_type"],
            "image_b64": session["image_b64"],
        }
    return {"status": "waiting"}


@router.post("/api/mobile/session/{session_id}/upload")
async def upload_from_mobile(session_id: str, file: UploadFile = File(...)):
    session = MOBILE_SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="انتهت صلاحية الجلسة، أعد مسح الرمز من اللابتوب.")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="الملف فارغ.")

    session["status"] = "uploaded"
    session["filename"] = file.filename or f"mobile_invoice_{int(time.time())}.jpg"
    session["content_type"] = file.content_type or "image/jpeg"
    session["image_b64"] = base64.b64encode(raw).decode("ascii")
    return {"ok": True, "message": "تم إرسال الصورة إلى اللابتوب بنجاح"}


@router.get("/mobile/{session_id}", response_class=HTMLResponse)
def mobile_capture_page(session_id: str):
    if session_id not in MOBILE_SESSIONS:
        return HTMLResponse(
            content="""
            <!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
            <meta name="viewport" content="width=device-width,initial-scale=1">
            <title>انتهت الجلسة</title></head>
            <body style="font-family:sans-serif;text-align:center;padding:40px;background:#f8fafc;">
            <h2>⚠️ انتهت صلاحية الرابط</h2>
            <p>يرجى تحديث رمز QR على شاشة اللابتوب وإعادة المسح.</p>
            </body></html>
            """,
            status_code=404,
        )

    return HTMLResponse(
        content=f"""
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1" />
  <title>قَيد الذكي — كاميرا الجوال</title>
  <style>
    * {{ box-sizing: border-box; font-family: system-ui, -apple-system, 'Segoe UI', Tahoma, sans-serif; }}
    body {{
      margin: 0; padding: 20px; background: #0f172a; color: #f8fafc;
      display: flex; flex-direction: column; align-items: center; min-height: 100vh;
    }}
    .card {{
      width: 100%; max-width: 440px; background: #1e293b; border-radius: 20px;
      padding: 24px; box-shadow: 0 20px 40px rgba(0,0,0,0.4); text-align: center;
      border: 1px solid #334155;
    }}
    h1 {{ font-size: 1.35rem; margin: 0 0 8px; color: #38bdf8; }}
    p {{ font-size: 0.92rem; color: #cbd5e1; margin: 0 0 20px; line-height: 1.5; }}
    .cam-btn {{
      display: flex; align-items: center; justify-content: center; gap: 10px;
      width: 100%; padding: 18px; border-radius: 14px; border: none;
      background: linear-gradient(135deg, #0284c7, #2563eb); color: #fff;
      font-size: 1.1rem; font-weight: 700; cursor: pointer;
      box-shadow: 0 8px 20px rgba(37, 99, 235, 0.35);
    }}
    .cam-btn:active {{ transform: scale(0.98); }}
    input[type="file"] {{ display: none; }}
    #preview-box {{ margin-top: 18px; display: none; }}
    #preview-img {{
      width: 100%; max-height: 320px; object-fit: contain;
      border-radius: 12px; border: 2px solid #38bdf8; background: #0f172a;
    }}
    .status {{
      margin-top: 16px; padding: 12px; border-radius: 12px;
      font-weight: 600; font-size: 0.95rem; display: none;
    }}
    .status.loading {{ display: block; background: #1e3a8a; color: #93c5fd; }}
    .status.success {{ display: block; background: #064e3b; color: #6ee7b7; }}
    .status.error {{ display: block; background: #7f1d1d; color: #fca5a5; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>📱 قَيد الذكي — كاميرا الجوال</h1>
    <p>التقط صورة واضحة للفاتورة وسيتم إرسالها فوراً إلى شاشة اللابتوب.</p>

    <label class="cam-btn" for="cameraInput">
      <span>📸 افتح الكاميرا وصوّر الفاتورة</span>
    </label>
    <input id="cameraInput" type="file" accept="image/*" capture="environment" />

    <div id="preview-box">
      <img id="preview-img" alt="معاينة الفاتورة" />
    </div>

    <div id="statusBox" class="status"></div>
  </div>

  <script>
    const sessionId = "{session_id}";
    const cameraInput = document.getElementById("cameraInput");
    const previewBox = document.getElementById("preview-box");
    const previewImg = document.getElementById("preview-img");
    const statusBox = document.getElementById("statusBox");

    function showStatus(type, msg) {{
      statusBox.className = "status " + type;
      statusBox.textContent = msg;
    }}

    cameraInput.addEventListener("change", async (e) => {{
      const file = e.target.files[0];
      if (!file) return;

      previewImg.src = URL.createObjectURL(file);
      previewBox.style.display = "block";
      showStatus("loading", "⏳ جاري ضغط وإرسال الفاتورة إلى اللابتوب...");

      const formData = new FormData();
      formData.append("file", file, file.name || "invoice.jpg");

      try {{
        const res = await fetch(`/api/mobile/session/${{sessionId}}/upload`, {{
          method: "POST",
          body: formData
        }});
        const data = await res.json();
        if (res.ok && data.ok) {{
          showStatus("success", "✅ تم إرسال الفاتورة بنجاح! انظر إلى شاشة اللابتوب الآن.");
        }} else {{
          showStatus("error", "❌ " + (data.detail || "فشل الإرسال"));
        }}
      }} catch (err) {{
        showStatus("error", "❌ تعذر الاتصال باللابتوب. تأكد أنك على نفس شبكة Wi-Fi.");
      }}
    }});
  </script>
</body>
</html>
        """
    )
