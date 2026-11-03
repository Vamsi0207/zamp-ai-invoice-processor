"""Generate visibly synthetic native and image-only invoice PDFs with PyMuPDF."""
from pathlib import Path

import fitz


ROOT = Path(__file__).resolve().parents[1] / "fixtures"


def generate():
    ROOT.mkdir(exist_ok=True)
    with fitz.open() as doc:
        page = doc.new_page(width=612, height=792)
        page.insert_text((45, 55), "SYNTHETIC OFFICE SUPPLY", fontsize=21)
        page.insert_text((45, 85), "INVOICE | SYNTHETIC TEST DATA - NOT PAYABLE", fontsize=12)
        for y, text in enumerate([
            "Vendor reference: DEMO-VENDOR", "Invoice number: SYN-001", "Invoice date: 2026-01-15",
            "Purchase order: DEMO-PO", "Bill to: Zamp Demo Accounts Payable",
            "Currency: USD", "", "Line   Description       Quantity   Unit price   Amount",
            "L1     Office chairs     4          100.00       400.00", "",
            "Subtotal: USD 400.00", "Tax: USD 0.00", "Shipping: USD 0.00", "Discount: USD 0.00",
            "TOTAL DUE: USD 400.00", "", "Payment terms: Net 30", "All entities and transactions are fictitious."
        ]):
            page.insert_text((45, 125 + y * 25), text, fontsize=11, fontname="cour")
        doc.save(ROOT / "native_invoice.pdf", deflate=True)
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        with fitz.open() as scan:
            scan.new_page(width=612, height=792).insert_image(page.rect, pixmap=pix)
            scan.save(ROOT / "scanned_invoice.pdf", deflate=True)


if __name__ == "__main__":
    generate()
