from pathlib import Path

import pdfplumber


def extract_text(pdf_path: Path) -> str:
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append(text)
    text = "\n\n".join(pages).strip()
    if not text:
        raise ValueError(
            f"No extractable text in {pdf_path} — likely a scanned/image-only PDF (needs OCR)"
        )
    return text
