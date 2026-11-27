from argparse import ArgumentParser
from pathlib import Path

try:
    from backend.ocr_engine import (
        InvoiceOCRError,
        InvoiceReviewRequired,
        extract_invoice,
        extract_text,
    )
    from backend.bridge import run_full_pipeline_from_ocr
    from backend.exporter import export_to_excel, export_to_odoo_csv
except ImportError:
    from ocr_engine import (
        InvoiceOCRError,
        InvoiceReviewRequired,
        extract_invoice,
        extract_text,
    )
    from bridge import run_full_pipeline_from_ocr
    from exporter import export_to_excel, export_to_odoo_csv


def main() -> None:
    parser = ArgumentParser(
        description="Qayd AI CLI: Extract, audit, and export Arabic invoices."
    )
    parser.add_argument("image", help="Path to the invoice image")
    parser.add_argument("--text", action="store_true", help="Return plain text only")
    parser.add_argument("--export-dir", default="", help="Directory to save Odoo CSV and Excel report")
    args = parser.parse_args()

    try:
        if args.text:
            print(extract_text(args.image))
            return

        review_required = False
        try:
            ocr_invoice = extract_invoice(args.image)
        except InvoiceReviewRequired as exc:
            if exc.invoice is None:
                raise SystemExit("REVIEW REQUIRED: Check the invoice manually.") from None
            ocr_invoice = exc.invoice
            review_required = True
    except InvoiceOCRError as error:
        raise SystemExit(f"OCR ERROR: {error}") from None

    result = run_full_pipeline_from_ocr(ocr_invoice, review_required=review_required)
    print(result.audit_result.summary_message)
    print(result.model_dump_json(indent=2))

    if args.export_dir:
        out_dir = Path(args.export_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(args.image).stem
        csv_path = out_dir / f"odoo_{stem}.csv"
        xlsx_path = out_dir / f"qayd_audit_{stem}.xlsx"
        export_to_odoo_csv(result.invoice, output_path=str(csv_path))
        export_to_excel(result.invoice, audit_result=result.audit_result, output_path=str(xlsx_path))
        print(f"Exported: {csv_path} & {xlsx_path}")


if __name__ == "__main__":
    main()
