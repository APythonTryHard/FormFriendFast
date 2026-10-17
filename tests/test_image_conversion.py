"""Real image conversion fixtures; no credentials or live inference."""
import base64
import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from app import app


class ImageConversionTests(unittest.TestCase):
    def upload(self, data, name="form.bmp", route="/api/convert"):
        response = app.test_client().post(route, data={"image": (io.BytesIO(data), name)})
        # Werkzeug's test multipart builder may spool large fixture requests.
        response.request.environ["wsgi.input"].close()
        return response

    def test_bmp_is_converted_to_browser_and_model_readable_jpeg(self):
        source = io.BytesIO()
        Image.new("RGB", (80, 120), "white").save(source, "BMP")
        response = self.upload(source.getvalue())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/jpeg")
        with Image.open(io.BytesIO(response.data)) as converted:
            self.assertEqual(converted.size, (80, 120))
            self.assertEqual(converted.format, "JPEG")
        completion = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content='{"fields":[]}'))])
        with patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "fictional-key"}), patch("ai_client.OpenAI") as client, redirect_stdout(io.StringIO()):
            client.return_value.chat.completions.create.return_value = completion
            analyzed = self.upload(source.getvalue(), route="/api/analyze")
        self.assertEqual(analyzed.status_code, 200)
        url = client.return_value.chat.completions.create.call_args.kwargs["messages"][1]["content"][1]["image_url"]["url"]
        self.assertTrue(url.startswith("data:image/jpeg;base64,"))
        with Image.open(io.BytesIO(base64.b64decode(url.split(",")[1]))) as sent:
            self.assertEqual(sent.size, (80, 120))

    def test_common_raster_formats_are_normalized_without_filename_or_mime_rules(self):
        for fmt in ("PNG", "JPEG", "WEBP", "BMP", "TIFF", "GIF", "ICO", "AVIF", "HEIF", "PPM", "TGA", "JPEG2000", "QOI"):
            with self.subTest(format=fmt):
                data = io.BytesIO()
                Image.new("RGB", (64, 96), "white").save(data, fmt)
                with Image.open(io.BytesIO(data.getvalue())) as original:
                    expected_size = original.size
                response = self.upload(data.getvalue(), "unknown-image")
                self.assertEqual(response.status_code, 200)
                with Image.open(io.BytesIO(response.data)) as image:
                    self.assertEqual(image.format, "JPEG")
                    self.assertEqual(image.size, expected_size)
                self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_orientation_and_transparency_are_normalized(self):
        data = io.BytesIO()
        exif = Image.Exif()
        exif[274] = 6
        Image.new("RGB", (80, 120), "white").save(data, "JPEG", exif=exif)
        response = self.upload(data.getvalue(), "phone.jpg")
        with Image.open(io.BytesIO(response.data)) as image:
            self.assertEqual(image.size, (120, 80))
            self.assertFalse(image.getexif())
        data = io.BytesIO()
        Image.new("RGBA", (80, 120), (0, 0, 0, 0)).save(data, "PNG")
        response = self.upload(data.getvalue(), "transparent.png")
        with Image.open(io.BytesIO(response.data)) as image:
            self.assertEqual(image.getpixel((40, 60)), (255, 255, 255))

    def test_first_frame_is_used_for_gif_and_tiff(self):
        for fmt in ("GIF", "TIFF"):
            with self.subTest(format=fmt):
                data = io.BytesIO()
                Image.new("RGB", (64, 96), "white").save(data, fmt, save_all=True,
                    append_images=[Image.new("RGB", (64, 96), "black")])
                response = self.upload(data.getvalue())
                self.assertEqual(response.status_code, 200)
                with Image.open(io.BytesIO(response.data)) as image:
                    self.assertEqual(image.getpixel((30, 30)), (255, 255, 255))

    def test_unconvertible_data_is_rejected_before_inference(self):
        for data in (b"", b"not an image", b"%PDF-1.7", b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'):
            for route in ("/api/convert", "/api/analyze"):
                with self.subTest(data=data, route=route), patch("ai_client.OpenAI") as provider:
                    response = self.upload(data, "bad.png", route)
                    self.assertEqual(response.status_code, 400)
                    self.assertIn("error", response.json)
                    provider.assert_not_called()

    def test_upload_and_pixel_limits_remain_enforced(self):
        response = self.upload(b"x" * (8 * 1024 * 1024 + 1))
        self.assertEqual(response.status_code, 413)
        data = io.BytesIO()
        Image.new("RGB", (80, 120), "white").save(data, "PNG")
        with patch("app.MAX_PIXELS", 100):
            response = self.upload(data.getvalue())
        self.assertEqual(response.status_code, 400)
        self.assertIn("megapixels", response.json["error"])
        # Exactly 8 MB of file bytes is valid despite multipart overhead.
        response = self.upload(data.getvalue().ljust(8 * 1024 * 1024, b"\0"))
        self.assertEqual(response.status_code, 200)

    def test_codec_failure_returns_safe_error(self):
        with patch("app.Image.open", side_effect=RuntimeError("private codec details")):
            response = self.upload(b"fixture")
        self.assertEqual(response.status_code, 400)
        self.assertIn("could not be converted", response.json["error"])
        self.assertNotIn("private", response.get_data(as_text=True))

    def test_duplicate_files_are_rejected(self):
        response = app.test_client().post("/api/convert", data={"image": [
            (io.BytesIO(b"a"), "a.bmp"), (io.BytesIO(b"b"), "b.bmp")]})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
