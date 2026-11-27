import os
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    from backend.ocr_engine import (
        InvoiceOCRError,
        InvoiceReviewRequired,
        get_active_provider_label,
        extract_invoice,
        extract_text,
        is_api_key_configured,
    )
    from backend.bridge import ProcessedInvoiceResponse, run_full_pipeline_from_ocr
    from backend.schema import AuditResult, InvoiceData
    from backend.auditor import audit_invoice
    from backend.exporter import export_to_excel, export_to_odoo_csv
    from backend.mobile_bridge import router as mobile_router
except ImportError:
    from ocr_engine import (
        InvoiceOCRError,
        InvoiceReviewRequired,
        get_active_provider_label,
        extract_invoice,
        extract_text,
        is_api_key_configured,
    )
    from bridge import ProcessedInvoiceResponse, run_full_pipeline_from_ocr
    from schema import AuditResult, InvoiceData
    from auditor import audit_invoice
    from exporter import export_to_excel, export_to_odoo_csv
    from mobile_bridge import router as mobile_router


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

app = FastAPI(
    title="Qayd AI — نظام قَيد الذكي لاستخراج وتدقيق الفواتير",
    version="1.0.0",
    description="منصة متكاملة لاستخراج الفواتير العربية بالذكاء الاصطناعي وتدقيقها محاسبياً وتصديرها إلى Odoo وExcel.",
)
app.include_router(mobile_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ExportRequest(BaseModel):
    invoice: InvoiceData
    expense_account: str = "600000 Expenses"


class TextOCRResponse(BaseModel):
    text: str
    processing_time_ms: int


@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "service": "Qayd AI Integrated System",
        "api_key_configured": is_api_key_configured(),
        "gemini_model": get_active_provider_label(),
    }


def _save_upload_temp(upload: UploadFile) -> str:
    suffix = Path(upload.filename or "invoice.jpg").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"صيغة الملف غير مدعومة ({suffix}). الصيغ المدعومة: JPG, PNG, WEBP, BMP.",
        )

    content = upload.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="الملف المرفوع فارغ.")

    fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix="qayd_upload_")
    with os.fdopen(fd, "wb") as tmp_file:
        tmp_file.write(content)
    return tmp_path


@app.post("/api/process-invoice", response_model=ProcessedInvoiceResponse)
def process_invoice_endpoint(file: UploadFile = File(...)):
    tmp_path = _save_upload_temp(file)
    start = time.perf_counter()
    try:
        try:
            ocr_invoice = extract_invoice(tmp_path)
            review_required = False
        except InvoiceReviewRequired as review_exc:
            if review_exc.invoice is None:
                raise HTTPException(status_code=422, detail=str(review_exc))
            ocr_invoice = review_exc.invoice
            review_required = True
        except InvoiceOCRError as ocr_exc:
            raise HTTPException(status_code=502, detail=str(ocr_exc))

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return run_full_pipeline_from_ocr(
            ocr_invoice,
            review_required=review_required,
            processing_time_ms=elapsed_ms,
        )
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@app.post("/api/extract-text", response_model=TextOCRResponse)
def extract_text_endpoint(file: UploadFile = File(...)):
    tmp_path = _save_upload_temp(file)
    start = time.perf_counter()
    try:
        try:
            text = extract_text(tmp_path)
        except InvoiceOCRError as ocr_exc:
            raise HTTPException(status_code=502, detail=str(ocr_exc))

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return TextOCRResponse(text=text, processing_time_ms=elapsed_ms)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@app.post("/api/audit", response_model=AuditResult)
def audit_invoice_endpoint(invoice: InvoiceData):
    return audit_invoice(invoice)


@app.post("/api/export/odoo-csv")
def export_odoo_csv_endpoint(payload: ExportRequest):
    csv_bytes = export_to_odoo_csv(
        payload.invoice,
        expense_account=payload.expense_account or "600000 Expenses",
    )
    safe_ref = re.sub(r'[\\/:*?"<>|\s]+', "_", (payload.invoice.invoice_number or "invoice").strip()) or "invoice"
    filename = f"odoo_{safe_ref}.csv"
    encoded_filename = quote(filename)
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="odoo_invoice.csv"; filename*=UTF-8\'\'{encoded_filename}'
        },
    )


@app.post("/api/export/excel")
def export_excel_endpoint(payload: ExportRequest):
    audit_res = audit_invoice(payload.invoice)
    xlsx_bytes = export_to_excel(
        payload.invoice,
        audit_result=audit_res,
        expense_account=payload.expense_account or "600000 Expenses",
    )
    safe_ref = re.sub(r'[\\/:*?"<>|\s]+', "_", (payload.invoice.invoice_number or "invoice").strip()) or "invoice"
    filename = f"qayd_audit_{safe_ref}.xlsx"
    encoded_filename = quote(filename)
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="qayd_audit.xlsx"; filename*=UTF-8\'\'{encoded_filename}'
        },
    )


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def serve_frontend():
        return FileResponse(str(FRONTEND_DIR / "index.html"))