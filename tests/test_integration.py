import io
from unittest.mock import patch
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from backend.main import app
from backend.ocr_schema import InvoiceData as OCRInvoiceData, InvoiceItem as OCRInvoiceItem
from backend.ocr_engine import InvoiceReviewRequired
from backend.bridge import map_ocr_to_audit_invoice, run_full_pipeline_from_ocr
from backend.auditor import parse_arabic_tafqeet, audit_invoice
from backend.exporter import export_to_odoo_csv, export_to_excel

client = TestClient(app)


def test_health_endpoint():
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "gemini_model" in body


def test_frontend_served():
    res = client.get("/")
    assert res.status_code == 200
    assert "قَيد الذكي" in res.text


def test_tafqeet_parser_cases():
    assert parse_arabic_tafqeet("فقط ثلاثمائة ألف ريال لا غير") == 300000.0
    assert parse_arabic_tafqeet("ألفان وخمسمائة ريال ونصف") == 2500.5
    assert parse_arabic_tafqeet("مائة ريال وخمسون هللة") == 100.50
    assert parse_arabic_tafqeet("") is None


def test_bridge_and_audit_valid_invoice():
    ocr_data = OCRInvoiceData(
        vendor_name="شركة اليمن للتجارة",
        invoice_date="24/11/2026",
        invoice_number="INV-100",
        items=[
            OCRInvoiceItem(description="شاشة عرض", quantity=2.0, unit_price=50000.0, line_total=100000.0),
            OCRInvoiceItem(description="لوحة مفاتيح", quantity=5.0, unit_price=4000.0, line_total=20000.0),
        ],
        tax_amount=0.0,
        total_amount=120000.0,
        tafqeet_text="فقط مائة وعشرون ألف ريال لا غير",
    )
    resp = run_full_pipeline_from_ocr(ocr_data, processing_time_ms=150)
    assert resp.audit_result.status == "valid"
    assert resp.invoice.invoice_date == "2026-11-24"
    assert resp.invoice.grand_total == 120000.0


def test_bridge_handwritten_single_column_invoice():
    ocr_data = OCRInvoiceData(
        vendor_name="",
        invoice_date="",
        invoice_number="__QAYD_REVIEW_REQUIRED__",
        items=[
            OCRInvoiceItem(description="ماء مقطر", quantity=0.0, unit_price=0.0, line_total=10000.0),
            OCRInvoiceItem(description="ملابس", quantity=0.0, unit_price=0.0, line_total=16000.0),
        ],
        tax_amount=0.0,
        total_amount=26000.0,
        tafqeet_text="",
    )
    resp = run_full_pipeline_from_ocr(ocr_data, review_required=True)
    assert resp.audit_result.status == "manual_review"
    assert len(resp.invoice.items) == 2
    assert resp.invoice.items[0].quantity == 1.0
    assert resp.invoice.items[0].unit_price == 10000.0


def test_audit_endpoint_detects_math_error():
    payload = {
        "vendor_name": "مورد اختبار",
        "invoice_date": "2026-11-24",
        "invoice_number": "99",
        "items": [{"name": "صنف 1", "quantity": 2, "unit_price": 100, "line_total": 250}],
        "subtotal": 250,
        "discount": 0,
        "tax": 0,
        "grand_total": 250,
        "tafqeet_text": "مائتان وخمسون ريال",
        "missing_fields": [],
    }
    res = client.post("/api/audit", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "error"
    assert len(data["math_errors"]) == 1


def test_exports_odoo_csv_and_excel():
    payload = {
        "invoice": {
            "vendor_name": "شركة الأمل",
            "invoice_date": "2026-11-24",
            "invoice_number": "INV-55",
            "items": [
                {"name": "صنف أ", "quantity": 2, "unit_price": 500, "line_total": 1000},
                {"name": "صنف ب", "quantity": 1, "unit_price": 500, "line_total": 500},
            ],
            "subtotal": 1500,
            "discount": 100,
            "tax": 0,
            "grand_total": 1400,
            "tafqeet_text": "ألف وأربعمائة ريال",
            "missing_fields": [],
        },
        "expense_account": "600000 Expenses",
    }
    csv_res = client.post("/api/export/odoo-csv", json=payload)
    assert csv_res.status_code == 200
    csv_text = csv_res.content.decode("utf-8-sig")
    assert "partner_id" in csv_text
    assert "شركة الأمل" in csv_text
    assert "-100.0" in csv_text

    xlsx_res = client.post("/api/export/excel", json=payload)
    assert xlsx_res.status_code == 200
    wb = load_workbook(io.BytesIO(xlsx_res.content))
    ws = wb.active
    assert ws.views.sheetView[0].rightToLeft is True
    assert "قَيد الذكي" in ws["A1"].value


def test_process_invoice_endpoint_with_mocked_ocr():
    mock_ocr = OCRInvoiceData(
        vendor_name="مورد تجريبي",
        invoice_date="2026-11-24",
        invoice_number="INV-77",
        items=[OCRInvoiceItem(description="خدمة برمجية", quantity=1.0, unit_price=5000.0, line_total=5000.0)],
        tax_amount=0.0,
        total_amount=5000.0,
        tafqeet_text="فقط خمسة آلاف ريال لا غير",
    )
    with patch("backend.main.extract_invoice", return_value=mock_ocr):
        res = client.post(
            "/api/process-invoice",
            files={"file": ("test.jpg", b"fake-jpeg-bytes", "image/jpeg")},
        )
    assert res.status_code == 200
    data = res.json()
    assert data["audit_result"]["status"] == "valid"
    assert data["invoice"]["vendor_name"] == "مورد تجريبي"
