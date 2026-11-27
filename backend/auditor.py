import re
from typing import Optional

try:
    from backend.schema import InvoiceData, AuditResult
except ImportError:
    from schema import InvoiceData, AuditResult

# هامش الخطأ المسموح به للكسور العشرية (1 هللة/فلس)
TOLERANCE = 0.01

# قاموس الأرقام العربية بعد التطبيع (توحيد الألف والهاء والياء)
ARABIC_NUMBERS = {
    "صفر": 0,
    "واحد": 1, "واحده": 1, "احد": 1, "احدي": 1,
    "اثنان": 2, "اثنين": 2, "اثنتان": 2, "اثنتين": 2, "ثنتين": 2, "اتنين": 2, "اثنا": 2, "اثني": 2, "اثنتا": 2, "اثنتي": 2,
    "ثلاث": 3, "ثلاثه": 3, "تلات": 3, "تلاته": 3,
    "اربع": 4, "اربعه": 4,
    "خمس": 5, "خمسه": 5,
    "ست": 6, "سته": 6,
    "سبع": 7, "سبعه": 7,
    "ثمان": 8, "ثماني": 8, "ثمانيه": 8, "تمنيه": 8,
    "تسع": 9, "تسعه": 9,
    "عشر": 10, "عشره": 10,
    "عشرون": 20, "عشرين": 20,
    "ثلاثون": 30, "ثلاثين": 30, "تلاتين": 30,
    "اربعون": 40, "اربعين": 40,
    "خمسون": 50, "خمسين": 50,
    "ستون": 60, "ستين": 60,
    "سبعون": 70, "سبعين": 70,
    "ثمانون": 80, "ثمانين": 80, "تمانين": 80,
    "تسعون": 90, "تسعين": 90,
    "مائتان": 200, "مائتين": 200, "مئتان": 200, "مئتين": 200, "ميتين": 200,
    "ثلاثمائه": 300, "ثلاثمئه": 300, "ثلاثميه": 300,
    "اربعمائه": 400, "اربعمئه": 400, "اربعميه": 400,
    "خمسمائه": 500, "خمسمئه": 500, "خمسميه": 500,
    "ستمائه": 600, "ستمئه": 600, "ستميه": 600,
    "سبعمائه": 700, "سبعمئه": 700, "سبعميه": 700,
    "ثمانمائه": 800, "ثمانمئه": 800, "ثمانيمئه": 800, "ثمانميه": 800,
    "تسعمائه": 900, "تسعمئه": 900, "تسعميه": 900,
}

HUNDRED_WORDS = {"مائه", "مئه", "ميه"}
THOUSAND_WORDS = {"الف", "الفا", "الاف", "الفان", "الفين"}
MILLION_WORDS = {"مليون", "مليونا", "ملايين", "مليونان", "مليونين"}

# كلمات زائدة (حشو وعملات) تُزال قبل التحويل
STOP_WORDS = {
    "فقط", "لا", "غير", "لاغير", "ريال", "ريالا", "ريالات",
    "يمني", "سعودي", "اماراتي", "درهم", "درهما", "دراهم",
    "دولار", "دولارا", "دولارات", "ر", "ي", "س", "د", "ا",
    "مبلغ", "وقدره", "اجمالي", "الاجمالي", "المبلغ"
}


def normalize_arabic_text(text: str) -> str:
    """تنظيف وتوحيد النص العربي لتسهيل تحويل التفقيط"""
    if not text:
        return ""
    text = re.sub(r"[\u064B-\u065F\u0670\u0640]", "", text)
    text = re.sub(r"[أإآٱ]", "ا", text)
    text = text.replace("ة", "ه").replace("ى", "ي")
    text = re.sub(r"[^\u0600-\u06FF\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_int_tokens(tokens: list[str]) -> Optional[int]:
    total = 0
    current = 0
    for tok in tokens:
        if tok in ARABIC_NUMBERS:
            current += ARABIC_NUMBERS[tok]
        elif tok in HUNDRED_WORDS:
            current = current * 100 if 1 <= current <= 9 else current + 100
        elif tok in {"الفان", "الفين"}:
            total += 2000
        elif tok in THOUSAND_WORDS:
            total += (current if current > 0 else 1) * 1000
            current = 0
        elif tok in {"مليونان", "مليونين"}:
            total += 2_000_000
        elif tok in MILLION_WORDS:
            total += (current if current > 0 else 1) * 1_000_000
            current = 0
        else:
            return None
    return total + current


def parse_arabic_tafqeet(text: Optional[str]) -> Optional[float]:
    if not text or not text.strip():
        return None

    cleaned = normalize_arabic_text(text)
    if not cleaned:
        return None

    raw_tokens = cleaned.split()
    tokens = []
    for tok in raw_tokens:
        if tok in STOP_WORDS or tok == "و":
            continue
        if tok.startswith("و") and len(tok) > 2 and tok not in ARABIC_NUMBERS:
            stripped = tok[1:]
            if stripped in STOP_WORDS:
                continue
            if (
                stripped in ARABIC_NUMBERS
                or stripped in HUNDRED_WORDS
                or stripped in THOUSAND_WORDS
                or stripped in MILLION_WORDS
                or stripped in {"نصف", "نص", "ربع", "هلله", "هللات", "فلس", "فلوس", "قرش", "قروش"}
            ):
                tok = stripped
        tokens.append(tok)

    if not tokens:
        return None

    fraction = 0.0
    if tokens[-1] in {"نصف", "نص"}:
        fraction = 0.5
        tokens = tokens[:-1]
    elif tokens[-1] == "ربع":
        fraction = 0.25
        tokens = tokens[:-1]

    sub_units = {"هلله", "هللات", "فلس", "فلوس", "قرش", "قروش"}
    if any(t in sub_units for t in tokens):
        idx = next(i for i, t in enumerate(tokens) if t in sub_units)
        sub_tokens = tokens[:idx]
        if not sub_tokens:
            return None
        currency_split = re.split(r"\b(?:ريال|ريالا|ريالات|درهم|درهما|دراهم|دولار|دولارا)\b", cleaned, maxsplit=1)
        if len(currency_split) == 2:
            main_val = parse_arabic_tafqeet(currency_split[0])
            sub_clean = re.sub(r"\b(?:هلله|هللات|فلس|فلوس|قرش|قروش|فقط|لا|غير|لاغير)\b", "", currency_split[1]).strip()
            sub_val = parse_arabic_tafqeet(sub_clean) if sub_clean else 0.0
            if main_val is None or sub_val is None or sub_val >= 100:
                return None
            return round(main_val + (sub_val / 100.0), 2)
        return None

    main_int = _parse_int_tokens(tokens) if tokens else 0
    if main_int is None:
        return None
    return round(float(main_int) + fraction, 2)


def audit_invoice(invoice: InvoiceData) -> AuditResult:
    """
    محرك التدقيق الحتمي:
    1. يفحص كل صف (الكمية × السعر = إجمالي الصف).
    2. يفحص المجموع الفرعي والخصم والضريبة والإجمالي النهائي.
    3. يفحص مطابقة التفقيط العربي مع الإجمالي النهائي.
    """
    math_errors = []
    warnings = []

    calculated_items_sum = 0.0
    if not invoice.items:
        warnings.append("لا توجد أصناف مستخرجة في جدول الفاتورة.")
    else:
        for idx, item in enumerate(invoice.items, start=1):
            expected_line_total = round(item.quantity * item.unit_price, 2)
            if abs(expected_line_total - item.line_total) > TOLERANCE:
                math_errors.append(
                    f"خطأ حسابي في السطر {idx} ({item.name}): "
                    f"{item.quantity} × {item.unit_price} = {expected_line_total}، "
                    f"بينما المكتوب {item.line_total}."
                )
            calculated_items_sum += item.line_total

    calculated_items_sum = round(calculated_items_sum, 2)

    if invoice.items and invoice.subtotal > 0:
        if abs(calculated_items_sum - invoice.subtotal) > TOLERANCE:
            math_errors.append(
                f"فرق في المجموع قبل الضريبة: مجموع الأسطر {calculated_items_sum}، "
                f"بينما المذكور في الفاتورة {invoice.subtotal}."
            )

    base_subtotal = calculated_items_sum if invoice.items else invoice.subtotal
    expected_grand_total = round(base_subtotal - invoice.discount + invoice.tax, 2)
    if abs(expected_grand_total - invoice.grand_total) > TOLERANCE:
        math_errors.append(
            f"فرق في الإجمالي النهائي: المتوقع ({base_subtotal} - {invoice.discount} + {invoice.tax} = {expected_grand_total})، "
            f"بينما المكتوب {invoice.grand_total}."
        )

    tafqeet_val = None
    tafqeet_match = None
    needs_manual_review = False

    if not invoice.tafqeet_text or not invoice.tafqeet_text.strip():
        warnings.append("نص التفقيط غير موجود في الفاتورة؛ يُنصح بالمراجعة اليدوية.")
        needs_manual_review = True
    else:
        tafqeet_val = parse_arabic_tafqeet(invoice.tafqeet_text)
        if tafqeet_val is None:
            warnings.append(
                f"تعذّر فهم نص التفقيط برمجياً ('{invoice.tafqeet_text}')؛ يتطلب تحققاً يدوياً."
            )
            needs_manual_review = True
        else:
            if abs(tafqeet_val - invoice.grand_total) <= TOLERANCE:
                tafqeet_match = True
            else:
                tafqeet_match = False
                math_errors.append(
                    f"تعارض في التفقيط: المبلغ كتابةً يعادل {tafqeet_val}، "
                    f"بينما الإجمالي الرقمي {invoice.grand_total}."
                )

    if math_errors:
        status = "error"
        summary = f"🔴 توجد {len(math_errors)} أخطاء حسابية أو تعارض في التفقيط."
    elif needs_manual_review or not invoice.items:
        status = "manual_review"
        summary = "🟡 الحسابات متزنة، لكن الفاتورة تحتاج مراجعة يدوية للتفقيط أو البيانات الناقصة."
    else:
        status = "valid"
        summary = "🟢 الفاتورة متزنة 100% رياضياً ولغوياً."

    return AuditResult(
        status=status,
        math_errors=math_errors,
        warnings=warnings,
        tafqeet_parsed_value=tafqeet_val,
        tafqeet_match=tafqeet_match,
        summary_message=summary,
    )
