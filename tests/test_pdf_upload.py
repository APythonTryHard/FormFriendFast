"""Fictional PDF pages, real rendering, no live provider requests."""
import io
import unittest
from PIL import Image
from app import app


def pdf_bytes():
    out = io.BytesIO()
    Image.new("RGB", (200, 300), "white").save(out, "PDF", save_all=True,
        append_images=[Image.new("RGB", (200, 300), "black")], resolution=72)
    return out.getvalue()


class PdfUploadTests(unittest.TestCase):
    def upload(self, data, page="0"):
        response = app.test_client().post("/api/convert", data={"image": (io.BytesIO(data), "form.pdf"), "page": page})
        response.request.environ["wsgi.input"].close()
        return response

    def test_pdf_pages_render_as_jpeg_with_page_count(self):
        for page, expected in (("0", (255, 255, 255)), ("1", (0, 0, 0))):
            response = self.upload(pdf_bytes(), page)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["X-Page-Count"], "2")
            self.assertEqual(response.headers["X-Page-Index"], page)
            self.assertEqual(response.mimetype, "image/jpeg")
            with Image.open(io.BytesIO(response.data)) as rendered:
                self.assertEqual(rendered.size, (400, 600))
                self.assertEqual(rendered.getpixel((50, 50)), expected)
    def test_encrypted_pdfs_are_rejected_even_without_a_user_password(self):
        from pypdf import PdfReader, PdfWriter
        for password in ("", "fictional-password"):
            with self.subTest(password_required=bool(password)):
                writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf_bytes())))
                writer.encrypt(user_password=password, owner_password="fictional-owner")
                out = io.BytesIO()
                writer.write(out)
                response = self.upload(out.getvalue())
                self.assertEqual(response.status_code, 400)
                self.assertIn("Encrypted PDFs", response.json["error"])

    def test_invalid_page_and_damaged_pdf_return_safe_errors(self):
        for page in ("-1", "2", "not-a-number", "1.5"):
            response = self.upload(pdf_bytes(), page)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json["error"], "Choose a valid PDF page.")
        response = self.upload(b"%PDF-1.7\nfictional damaged document")
        self.assertEqual(response.status_code, 400)
        self.assertIn("could not be opened or converted", response.json["error"])
        self.assertNotIn("fictional damaged", response.json["error"])

    def test_page_count_and_render_size_are_bounded(self):
        from pypdf import PdfWriter
        writer = PdfWriter()
        for _ in range(21):
            writer.add_blank_page(width=200, height=300)
        out = io.BytesIO()
        writer.write(out)
        response = self.upload(out.getvalue())
        self.assertEqual(response.status_code, 400)
        self.assertIn("20", response.json["error"])
        writer = PdfWriter()
        writer.add_blank_page(width=10000, height=15000)
        out = io.BytesIO()
        writer.write(out)
        response = self.upload(out.getvalue())
        self.assertEqual(response.status_code, 200)
        with Image.open(io.BytesIO(response.data)) as rendered:
            self.assertLessEqual(max(rendered.size), 4096)

    def test_selected_pdf_page_reaches_model_as_jpeg(self):
        import base64
        from contextlib import redirect_stdout
        from types import SimpleNamespace
        from unittest.mock import patch
        completion = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content='{"fields":[]}'))])
        with patch("app.load_api_key", return_value=("fictional-key", None)), patch("app.OpenAI") as client, redirect_stdout(io.StringIO()):
            client.return_value.chat.completions.create.return_value = completion
            response = app.test_client().post("/api/analyze", data={"image": (io.BytesIO(pdf_bytes()), "form.pdf"), "page": "1"})
        self.assertEqual(response.status_code, 200)
        url = client.return_value.chat.completions.create.call_args.kwargs["messages"][1]["content"][1]["image_url"]["url"]
        self.assertTrue(url.startswith("data:image/jpeg;base64,"))
        with Image.open(io.BytesIO(base64.b64decode(url.split(",")[1]))) as image:
            self.assertEqual(image.getpixel((50, 50)), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
