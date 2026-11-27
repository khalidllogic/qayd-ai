from typing import List
from pydantic import BaseModel, Field

try:
    from backend.ocr_schema import REVIEW_MARKER, InvoiceData as OCRInvoiceData
    from backend.schema import InvoiceData as AuditInvoiceData, InvoiceItem as AuditInvoiceItem, AuditResult
    from backend.auditor import audit_invoice
except ImportError:
    from ocr_schema import REVIEW_MARKER, InvoiceData as OCRInvoiceData
    from schema import InvoiceData as AuditInvoiceData, InvoiceItem as AuditInvoiceItem, AuditResult
    from auditor import audit_invoice


class ProcessedInvoiceResponse(BaseModel):
    invoice: AuditInvoiceData
    audit_result: AuditResult
    ocr_review_required: bool = False
    ocr_notes: List[str] = Field(default_factory=list)
    processing_time_ms: int = 0


def map_ocr_to_audit_invoice(
    ocr_invoice: OCRInvoiceData,
    *,
    review_required: bool = False,
) -> tuple[AuditInvoiceData, list[str]]:
    missing_fields: list[str] = []
    notes: list[str] = []

    vendor_name = (ocr_invoice.vendor_name or "").strip()
    if not vendor_name or vendor_name == REVIEW_MARKER:
        vendor_name = None
        missing_fields.append("vendor_name")
        notes.append("اسم المورد غير واضح أو غير موجود في الفاتورة.")

    invoice_date = (ocr_invoice.invoice_date or "").strip()
    if not invoice_date or invoice_date == REVIEW_MARKER:
        invoice_date = None
        missing_fields.append("invoice_date")
        notes.append("تاريخ الفاتورة غير واضح أو غير مذكور.")

    invoice_number = (ocr_invoice.invoice_number or "").strip()
    if not invoice_number or invoice_number == REVIEW_MARKER:
        invoice_number = None
        missing_fields.append("invoice_number")
        notes.append("رقم الفاتورة غير واضح أو غير مذكور؛ يُرجى إدخاله يدوياً قبل التصدير إلى Odoo.")

    mapped_items: list[AuditInvoiceItem] = []
    for item in ocr_invoice.items:
        qty = float(item.quantity)
        unit_price = float(item.unit_price)
        line_total = float(item.line_total)

        if qty == 0.0 and unit_price == 0.0 and line_total > 0.0:
            qty = 1.0
            unit_price = line_total

        mapped_items.append(
            AuditInvoiceItem(
                name=(item.description or "").strip() or "صنف غير محدد",
                quantity=qty,
                unit_price=unit_price,
                line_total=line_total,
            )
        )

    calculated_subtotal = round(sum(i.line_total for i in mapped_items), 2)
    tax = round(float(ocr_invoice.tax_amount or 0.0), 2)
    raw_total = round(float(ocr_invoice.total_amount or 0.0), 2)

    if raw_total == 0.0 and calculated_subtotal > 0.0:
        grand_total = round(calculated_subtotal + tax, 2)
        missing_fields.append("grand_total")
        notes.append("لم يُكتب إجمالي نهائي في الفاتورة؛ تم احتسابه تلقائياً من مجموع البنود.")
    else:
        grand_total = raw_total

    tafqeet_text = (ocr_invoice.tafqeet_text or "").strip() or None
    if not tafqeet_text:
        missing_fields.append("tafqeet_text")

    if review_required and not notes:
        notes.append("أشار محرك OCR إلى وجود حقل ملتبس يتطلب التحقق البشري.")

    audit_invoice_data = AuditInvoiceData(
        vendor_name=vendor_name,
        invoice_date=invoice_date,
        invoice_number=invoice_number,
        items=mapped_items,
        subtotal=calculated_subtotal,
        discount=0.0,
        tax=tax,
        grand_total=grand_total,
        tafqeet_text=tafqeet_text,
        missing_fields=missing_fields,
    )

    return audit_invoice_data, notes


def run_full_pipeline_from_ocr(
    ocr_invoice: OCRInvoiceData,
    *,
    review_required: bool = False,
    processing_time_ms: int = 0,
) -> ProcessedInvoiceResponse:
    audit_invoice_data, notes = map_ocr_to_audit_invoice(
        ocr_invoice, review_required=review_required
    )
    audit_result = audit_invoice(audit_invoice_data)

    for note in notes:
        if note not in audit_result.warnings:
            audit_result.warnings.append(note)

    if review_required and audit_result.status == "valid":
        audit_result.status = "manual_review"
        audit_result.summary_message = (
            "🟡 الحسابات متزنة، لكن محرك الاستخراج يوصي بمراجعة بعض الحقول الملتبسة."
        )

    return ProcessedInvoiceResponse(
        invoice=audit_invoice_data,
        audit_result=audit_result,
        ocr_review_required=review_required,
        ocr_notes=notes,
        processing_time_ms=processing_time_ms,
    )
