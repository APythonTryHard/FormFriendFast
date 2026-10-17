"""Bounded local PDF-to-raster rendering; never executes document actions."""
import io
import math
import threading

import pypdfium2 as pdfium
from pypdf import PdfReader

MAX_PDF_PAGES = 20
PDF_LOCK = threading.Lock()  # PDFium calls must not overlap across Flask threads.


class PdfConversionError(ValueError):
    """A fixed, user-safe conversion failure."""


def render_pdf_page(data, page_index):
    try:
        # is_encrypted also detects owner-password-only documents.
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise PdfConversionError("Encrypted PDFs are not supported. Upload an unencrypted copy.")
        with PDF_LOCK, pdfium.PdfDocument(data) as document:
            count = len(document)
            if not 1 <= count <= MAX_PDF_PAGES:
                raise PdfConversionError(f"Choose a PDF with 1–{MAX_PDF_PAGES} pages.")
            if not 0 <= page_index < count:
                raise PdfConversionError("Choose a valid PDF page.")
            page = document[page_index]
            try:
                width, height = page.get_size()
                if not all(math.isfinite(n) and n > 0 for n in (width, height)):
                    raise PdfConversionError("This PDF has an invalid page size.")
                scale = min(2, 4096 / width, 4096 / height)
                bitmap = page.render(scale=scale)
                try:
                    image = bitmap.to_pil()
                    try:
                        output = io.BytesIO()
                        image.convert("RGB").save(output, "JPEG", quality=95, optimize=True)
                        return output.getvalue(), count
                    finally:
                        image.close()
                finally:
                    bitmap.close()
            finally:
                page.close()
    except PdfConversionError:
        raise
    except Exception:
        raise PdfConversionError("This PDF could not be opened or converted. Try an undamaged, unencrypted copy.") from None
