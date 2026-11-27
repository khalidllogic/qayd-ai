from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Literal
import re


def clean_number(v) -> float:
    """تنظيف الأرقام من الفواصل والأرقام العربية والعملات لمنع انهيار Pydantic"""
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    arabic_digits = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    s = str(v).translate(arabic_digits)
    s = re.sub(r"[^\d.\-]", "", s)
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


class InvoiceItem(BaseModel):
    name: str = Field("صنف غير محدد", description="اسم الصنف")
    quantity: float = Field(0.0, description="الكمية")
    unit_price: float = Field(0.0, description="سعر الوحدة")
    line_total: float = Field(0.0, description="إجمالي السطر")

    @field_validator("quantity", "unit_price", "line_total", mode="before")
    @classmethod
    def parse_numbers(cls, v):
        return clean_number(v)


class InvoiceData(BaseModel):
    vendor_name: Optional[str] = Field(None, description="اسم المورد")
    invoice_date: Optional[str] = Field(None, description="تاريخ الفاتورة YYYY-MM-DD")
    invoice_number: Optional[str] = Field(None, description="رقم الفاتورة")
    items: List[InvoiceItem] = Field(default_factory=list, description="جدول الأصناف")
    subtotal: float = Field(0.0, description="المجموع قبل الضريبة")
    discount: float = Field(0.0, description="قيمة الخصم إن وجد")
    tax: float = Field(0.0, description="قيمة الضريبة")
    grand_total: float = Field(0.0, description="الإجمالي النهائي رقماً")
    tafqeet_text: Optional[str] = Field(None, description="المبلغ كتابةً بالحروف العربية")
    missing_fields: List[str] = Field(default_factory=list, description="حقول لم تُستخرج")

    @field_validator("subtotal", "discount", "tax", "grand_total", mode="before")
    @classmethod
    def parse_totals(cls, v):
        return clean_number(v)

    @field_validator("invoice_date", mode="before")
    @classmethod
    def normalize_date(cls, v):
        if not v:
            return None
        arabic_digits = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
        s = str(v).translate(arabic_digits).strip()
        m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$", s)
        if m:
            d, mo, y = m.groups()
            return f"{y}-{int(mo):02d}-{int(d):02d}"
        return s


class AuditResult(BaseModel):
    status: Literal["valid", "manual_review", "error"]
    math_errors: List[str] = Field(default_factory=list, description="أخطاء رياضية")
    warnings: List[str] = Field(default_factory=list, description="تحذيرات لا تمنع الاعتماد")
    tafqeet_parsed_value: Optional[float] = None
    tafqeet_match: Optional[bool] = None
    summary_message: str = Field("لا توجد ملاحظات", description="ملخص الحالة للمستخدم")
