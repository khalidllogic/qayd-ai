from pydantic import BaseModel, ConfigDict

REVIEW_MARKER = "__QAYD_REVIEW_REQUIRED__"


class InvoiceItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    description: str
    quantity: float
    unit_price: float
    line_total: float


class InvoiceData(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    vendor_name: str
    invoice_date: str
    invoice_number: str
    items: list[InvoiceItem]
    tax_amount: float
    total_amount: float
    tafqeet_text: str
