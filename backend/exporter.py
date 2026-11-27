import io
from typing import Optional
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

try:
    from backend.schema import InvoiceData, AuditResult
except ImportError:
    from schema import InvoiceData, AuditResult


def export_to_odoo_csv(
    invoice: InvoiceData,
    expense_account: str = "600000 Expenses",
    output_path: Optional[str] = None,
) -> bytes:
    """
    تصدير الفاتورة إلى ملف CSV مطابق لقالب استيراد فواتير الموردين في Odoo.
    قاعدة Odoo: بيانات رأس الفاتورة تُكتب في السطر الأول فقط وتُترك فارغة في بقية الأسطر.
    """
    rows = []
    items = invoice.items if invoice.items else []

    if not items:
        rows.append({
            "partner_id": invoice.vendor_name or "مورد غير محدد",
            "invoice_date": invoice.invoice_date or "",
            "ref": invoice.invoice_number or "",
            "move_type": "in_invoice",
            "invoice_line_ids/name": "إجمالي الفاتورة",
            "invoice_line_ids/account_id": expense_account,
            "invoice_line_ids/quantity": 1.0,
            "invoice_line_ids/price_unit": invoice.grand_total,
        })
    else:
        for idx, item in enumerate(items):
            rows.append({
                "partner_id": (invoice.vendor_name or "مورد غير محدد") if idx == 0 else "",
                "invoice_date": (invoice.invoice_date or "") if idx == 0 else "",
                "ref": (invoice.invoice_number or "") if idx == 0 else "",
                "move_type": "in_invoice" if idx == 0 else "",
                "invoice_line_ids/name": item.name,
                "invoice_line_ids/account_id": expense_account,
                "invoice_line_ids/quantity": item.quantity,
                "invoice_line_ids/price_unit": item.unit_price,
            })

    if invoice.discount > 0:
        rows.append({
            "partner_id": "",
            "invoice_date": "",
            "ref": "",
            "move_type": "",
            "invoice_line_ids/name": "خصم الفاتورة",
            "invoice_line_ids/account_id": expense_account,
            "invoice_line_ids/quantity": 1.0,
            "invoice_line_ids/price_unit": -invoice.discount,
        })

    df = pd.DataFrame(rows)
    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")

    if output_path:
        with open(output_path, "wb") as f:
            f.write(csv_bytes)

    return csv_bytes


def export_to_excel(
    invoice: InvoiceData,
    audit_result: Optional[AuditResult] = None,
    expense_account: str = "600000 Expenses",
    output_path: Optional[str] = None,
) -> bytes:
    """
    تصدير الفاتورة ونتيجة التدقيق إلى ملف Excel (.xlsx) منسّق بالكامل باتجاه RTL.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "تدقيق الفاتورة"
    ws.views.sheetView[0].rightToLeft = True

    title_font = Font(name="Arial", size=14, bold=True, color="FFFFFF")
    header_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
    bold_font = Font(name="Arial", size=11, bold=True)
    regular_font = Font(name="Arial", size=11)

    primary_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    sub_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin")
    )
    center_align = Alignment(horizontal="center", vertical="center")
    right_align = Alignment(horizontal="right", vertical="center")

    ws.merge_cells("A1:E1")
    ws["A1"] = "تقرير تدقيق الفاتورة — نظام قَيد الذكي (Qayd AI)"
    ws["A1"].font = title_font
    ws["A1"].fill = primary_fill
    ws["A1"].alignment = center_align
    ws.row_dimensions[1].height = 28

    meta = [
        ("اسم المورد:", invoice.vendor_name or "غير محدد"),
        ("رقم الفاتورة:", invoice.invoice_number or "غير محدد"),
        ("تاريخ الفاتورة:", invoice.invoice_date or "غير محدد"),
        ("حساب المصروفات (Odoo):", expense_account),
    ]
    if audit_result:
        meta.append(("حالة التدقيق:", audit_result.summary_message))

    row_idx = 3
    for label, value in meta:
        ws[f"A{row_idx}"] = label
        ws[f"A{row_idx}"].font = bold_font
        ws[f"A{row_idx}"].fill = sub_fill
        ws[f"A{row_idx}"].alignment = right_align
        ws.merge_cells(f"B{row_idx}:E{row_idx}")
        ws[f"B{row_idx}"] = value
        ws[f"B{row_idx}"].font = regular_font
        ws[f"B{row_idx}"].alignment = right_align
        row_idx += 1

    row_idx += 1
    headers = ["#", "اسم الصنف", "الكمية", "سعر الوحدة", "إجمالي السطر"]
    for col_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=row_idx, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = primary_fill
        cell.alignment = center_align
        cell.border = thin_border

    row_idx += 1
    for i, item in enumerate(invoice.items, start=1):
        vals = [i, item.name, item.quantity, item.unit_price, item.line_total]
        for col_idx, val in enumerate(vals, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.font = regular_font
            cell.alignment = right_align if col_idx == 2 else center_align
            cell.border = thin_border
        row_idx += 1

    row_idx += 1
    totals = [
        ("المجموع قبل الضريبة:", invoice.subtotal),
        ("الخصم:", invoice.discount),
        ("الضريبة:", invoice.tax),
        ("الإجمالي النهائي:", invoice.grand_total),
        ("التفقيط:", invoice.tafqeet_text or "غير مذكور"),
    ]
    for label, val in totals:
        ws[f"D{row_idx}"] = label
        ws[f"D{row_idx}"].font = bold_font
        ws[f"D{row_idx}"].fill = sub_fill
        ws[f"D{row_idx}"].alignment = right_align
        ws[f"E{row_idx}"] = val
        ws[f"E{row_idx}"].font = bold_font
        ws[f"E{row_idx}"].alignment = center_align
        ws[f"D{row_idx}"].border = thin_border
        ws[f"E{row_idx}"].border = thin_border
        row_idx += 1

    if audit_result and (audit_result.math_errors or audit_result.warnings):
        row_idx += 1
        ws[f"A{row_idx}"] = "تفاصيل الأخطاء والتحذيرات:"
        ws[f"A{row_idx}"].font = bold_font
        row_idx += 1
        for msg in audit_result.math_errors + audit_result.warnings:
            ws.merge_cells(f"A{row_idx}:E{row_idx}")
            ws[f"A{row_idx}"] = f"- {msg}"
            ws[f"A{row_idx}"].font = regular_font
            ws[f"A{row_idx}"].alignment = right_align
            row_idx += 1

    col_widths = {"A": 18, "B": 32, "C": 14, "D": 22, "E": 22}
    for col_letter, width in col_widths.items():
        ws.column_dimensions[col_letter].width = width

    buffer = io.BytesIO()
    wb.save(buffer)
    excel_bytes = buffer.getvalue()

    if output_path:
        with open(output_path, "wb") as f:
            f.write(excel_bytes)

    return excel_bytes
