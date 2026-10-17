import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from PIL import Image

from app import app


def png_bytes():
    image = Image.new("RGB", (400, 600), "white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class FakeResponse:
    def __init__(self, fields):
        content = json.dumps({"fields": fields})
        self.choices = [SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=content))]


class AnalyzeTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def upload(self, content=None, filename="form.png"):
        return self.client.post("/api/analyze", data={"image": (io.BytesIO(content if content is not None else png_bytes()), filename)}, content_type="multipart/form-data")

    def test_image_returns_structured_fields_and_sends_vision_request(self):
        fields = [{"label": "Full name", "guidance": "Enter your legal full name.", "box": [100, 200, 500, 280]}]
        output = io.StringIO()
        with patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "test-key"}), patch("ai_client.OpenAI") as client, redirect_stdout(output):
            client.return_value.chat.completions.create.return_value = FakeResponse(fields)
            response = self.upload()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["fields"], [{"id": 0, "label": "Full name", "guidance": "Enter your legal full name.", "box": [100, 200, 400, 80]}])
        payload = client.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(client.call_args.kwargs["api_key"], "test-key")
        self.assertEqual(client.call_args.kwargs["base_url"], "https://api.openai.com/v1")
        self.assertEqual(payload["model"], "gpt-6.1-sol")
        self.assertEqual(payload["max_completion_tokens"], 16_384)
        image_url = payload["messages"][1]["content"][1]["image_url"]["url"]
        self.assertTrue(image_url.startswith("data:image/jpeg;base64,"))
        self.assertFalse(payload["stream"])
        self.assertIn("[FormFriend] Parsed 1 fields", output.getvalue())
        self.assertNotIn("Checking the image", response.get_data(as_text=True))
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_short_examples_are_kept_and_unsafe_or_invalid_examples_are_omitted(self):
        box = [10, 20, 100, 40]
        fields = [
            {"label": "Full name", "guidance": "Your name.", "box": box, "example": "  Alex   Smith "},
            {"label": "Phone", "guidance": "Your phone.", "box": box, "example": "(555) 555-0123"},
            {"label": "Signature", "guidance": "Sign here.", "box": box, "example": ""},
            {"label": "SSN", "guidance": "Your SSN.", "box": box, "example": "123-45-6789"},
            {"label": "Card", "guidance": "Card number.", "box": box, "example": "4111 1111 1111 1111"},
            {"label": "Notes", "guidance": "Notes.", "box": box, "example": "x" * 61},
            {"label": "City", "guidance": "City.", "box": box, "example": "Line one\nLine two"},
            {"label": "Age", "guidance": "Age.", "box": box, "example": 42},
            {"label": "Email", "guidance": "Email.", "box": box},
        ]
        with patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "test-key"}), patch("ai_client.OpenAI") as client, redirect_stdout(io.StringIO()):
            client.return_value.chat.completions.create.return_value = FakeResponse(fields)
            response = self.upload()
        self.assertEqual(response.status_code, 200)
        examples = [field.get("example") for field in response.json["fields"]]
        self.assertEqual(examples, ["Alex Smith", "(555) 555-0123", None, None, None, None, None, None, None])
        self.assertNotIn("example", response.json["fields"][2], "Empty examples are omitted, not sent as blanks")
        system = client.return_value.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn('"example"', system)
        self.assertIn("examples in English", system)

    def test_bracketless_fallback_accepts_optional_example(self):
        raw = '{"fields": {"label": "Name", "guidance": "Your name", "box": [10, 20, 100, 40], "example": "Alex Smith"}, {"label": "Date", "guidance": "Today", "box": [10, 50, 100, 70]}}'
        completion = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=raw))])
        with patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "test-key"}), patch("ai_client.OpenAI") as client, redirect_stdout(io.StringIO()):
            client.return_value.chat.completions.create.return_value = completion
            response = self.upload()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["fields"][0]["example"], "Alex Smith")
        self.assertNotIn("example", response.json["fields"][1])

    def test_openai_luna_request_uses_low_reasoning_without_provider_extensions(self):
        with tempfile.TemporaryDirectory() as directory, patch("ai_client.OPENAI_KEY_FILE", Path(directory) / "missing"), patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "openai-test-key"}, clear=True), patch("ai_client.OpenAI") as client, redirect_stdout(io.StringIO()):
            client.return_value.chat.completions.create.return_value = FakeResponse([])
            response = self.upload()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.call_args.kwargs["api_key"], "openai-test-key")
        self.assertEqual(client.call_args.kwargs["base_url"], "https://api.openai.com/v1")
        payload = client.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(payload["model"], "gpt-6.1-sol")
        self.assertEqual(payload["reasoning_effort"], "low")
        self.assertEqual(payload["max_completion_tokens"], 16_384)
        self.assertNotIn("max_tokens", payload)
        self.assertNotIn("extra_body", payload)

    def test_json_mode_uses_buffered_completion_with_low_reasoning(self):
        with patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "test-key"}), patch("ai_client.OpenAI") as client, redirect_stdout(io.StringIO()):
            client.return_value.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
                finish_reason="stop", message=SimpleNamespace(content='{"fields":[]}', reasoning="fictional reasoning"))])
            response = self.upload()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"fields": [], "context": ""})
        payload = client.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["reasoning_effort"], "low")
        self.assertNotIn("extra_body", payload)

    def test_vision_request_uses_json_instructions_as_system_text_with_json_mode(self):
        with patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "test-key"}), patch("ai_client.OpenAI") as client, redirect_stdout(io.StringIO()):
            client.return_value.chat.completions.create.return_value = FakeResponse([])
            response = self.upload()
        self.assertEqual(response.status_code, 200)
        payload = client.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual([message["role"] for message in payload["messages"]], ["system", "user"])
        system = payload["messages"][0]["content"]
        self.assertIn('"fields" must be an array', system)
        self.assertIn('never use "box2"', system)
        self.assertEqual(payload["messages"][1]["content"][0]["type"], "text")
        self.assertEqual(payload["messages"][1]["content"][1]["type"], "image_url")

    def test_low_reasoning_does_not_parse_reasoning_as_json(self):
        answer = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(
            content='{"fields":[]}', reasoning="This is reasoning, not JSON"))])
        output = io.StringIO()
        with patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "test-key"}), patch("ai_client.OpenAI") as client, redirect_stdout(output):
            client.return_value.chat.completions.create.return_value = answer
            response = self.upload()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"fields": [], "context": ""})
        payload = client.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(payload["reasoning_effort"], "low")
        self.assertNotIn("extra_body", payload)
        self.assertNotIn("This is reasoning", output.getvalue())

    def test_sdk_serializes_buffered_json_vision_request(self):
        requests = []
        urls = []

        def respond(request):
            requests.append(json.loads(request.content))
            urls.append(str(request.url))
            return httpx.Response(200, json={"id": "chat-1", "object": "chat.completion", "created": 1,
                                             "model": "gpt-6.1-sol", "choices": [{"index": 0,
                                             "message": {"role": "assistant", "content": '{"fields":[]}', "reasoning": "private thought"},
                                             "finish_reason": "stop"}]})

        transport = httpx.MockTransport(respond)
        real_client = OpenAI(api_key="test-key", base_url="https://api.openai.com/v1", http_client=httpx.Client(transport=transport))
        with patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "test-key"}), patch("ai_client.OpenAI", return_value=real_client), redirect_stdout(io.StringIO()):
            response = self.upload()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["fields"], [])
        self.assertEqual(urls, ["https://api.openai.com/v1/chat/completions"])
        self.assertEqual(requests[0]["model"], "gpt-6.1-sol")
        self.assertEqual(requests[0]["reasoning_effort"], "low")
        self.assertNotIn("chat_template_kwargs", requests[0])
        self.assertEqual(requests[0]["max_completion_tokens"], 16_384)
        self.assertFalse(requests[0]["stream"])
        self.assertEqual([message["role"] for message in requests[0]["messages"]], ["system", "user"])
        self.assertEqual(requests[0]["response_format"], {"type": "json_object"})
        self.assertTrue(requests[0]["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        real_client.close()

    def test_rejects_non_image_even_with_png_name(self):
        with patch("ai_client.OpenAI") as request:
            response = self.upload(b"not an image")
        self.assertEqual(response.status_code, 400)
        request.assert_not_called()

    def test_rejects_duplicate_file_parts(self):
        response = self.client.post("/api/analyze", data={"image": [(io.BytesIO(png_bytes()), "a.png"), (io.BytesIO(png_bytes()), "b.png")]}, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 400)

    def test_rejects_out_of_bounds_model_box(self):
        fields = [{"label": "Name", "guidance": "Your name", "box": [950, 100, 1150, 160]}]
        output = io.StringIO()
        with patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "test-key"}), patch("ai_client.OpenAI") as client, redirect_stdout(output):
            client.return_value.chat.completions.create.return_value = FakeResponse(fields)
            response = self.upload()
        self.assertEqual(response.status_code, 502)
        self.assertIn("Invalid box", output.getvalue())

    def test_dense_form_with_120_valid_fields_is_accepted(self):
        fields = [{"label": f"Field {number}", "guidance": "Enter the requested value.", "box": [10, 20, 100, 40]} for number in range(120)]
        with patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "test-key"}, clear=True), patch("ai_client.OpenAI") as client, redirect_stdout(io.StringIO()):
            client.return_value.chat.completions.create.return_value = FakeResponse(fields)
            response = self.upload()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json["fields"]), 120)

    def test_dense_form_limit_still_rejects_more_than_300_fields(self):
        fields = [{"label": f"Field {number}", "guidance": "Enter the requested value.", "box": [10, 20, 100, 40]} for number in range(301)]
        output = io.StringIO()
        with patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "test-key"}, clear=True), patch("ai_client.OpenAI") as client, redirect_stdout(output):
            client.return_value.chat.completions.create.return_value = FakeResponse(fields)
            response = self.upload()
        self.assertEqual(response.status_code, 502)
        self.assertIn("Too many fields: 301 (maximum 300)", output.getvalue())
        self.assertIn("300", response.json["error"])

    def test_non_array_fields_reports_wrong_type(self):
        output = io.StringIO()
        with patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "test-key"}, clear=True), patch("ai_client.OpenAI") as client, redirect_stdout(output):
            client.return_value.chat.completions.create.return_value = FakeResponse({})
            response = self.upload()
        self.assertEqual(response.status_code, 502)
        self.assertIn("Fields must be an array, got dict", output.getvalue())

    def test_long_label_in_field_80_is_preserved_and_can_be_asked_about(self):
        label = "Printed instructions for this field. " * 8
        fields = [{"label": f"Field {number}", "guidance": "Enter the requested value", "box": [10, 20, 100, 40]} for number in range(79)]
        fields.append({"label": label, "guidance": "Check the printed instructions", "box": [10, 20, 100, 40]})
        lines = ["Use the information requested by this field.", "Consult the source document named on the form.", "Check official instructions if unsure."]
        answer = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=json.dumps({"lines": lines})))])
        with patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "fictional-key"}, clear=True), patch("ai_client.OpenAI") as client, redirect_stdout(io.StringIO()):
            client.return_value.chat.completions.create.side_effect = [FakeResponse(fields), answer]
            response = self.upload()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["fields"][79]["label"], label.strip())
            answered = self.client.post("/api/ask", json={"label": response.json["fields"][79]["label"], "guidance": "Check the printed instructions", "question": "Where do I find this?"})
        self.assertEqual(answered.status_code, 200)
        self.assertEqual(answered.json["lines"], lines)

    def test_invalid_field_reports_index_and_specific_reason_without_raw_text(self):
        cases = [
            ({"label": "private " * 126, "guidance": "Enter value", "box": [10, 20, 100, 40]}, "label exceeds 1000 characters"),
            ({"label": "Name", "guidance": "Enter value", "box": [10.5, 20, 100, 40]}, "box coordinates must be integers"),
            ({"label": "Name", "guidance": "", "box": [10, 20, 100, 40]}, "guidance must be nonempty text"),
            ({"label": "Name", "guidance": "Enter value"}, "missing required keys"),
        ]
        for field, reason in cases:
            output = io.StringIO()
            with self.subTest(reason=reason), patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "test-key"}, clear=True), patch("ai_client.OpenAI") as client, redirect_stdout(output):
                client.return_value.chat.completions.create.return_value = FakeResponse([field])
                response = self.upload()
            self.assertEqual(response.status_code, 502)
            self.assertIn(f"Invalid field 1: {reason}", output.getvalue())
            self.assertIn(f"Invalid field 1: {reason}", response.json["error"])
            self.assertNotIn("private", response.json["error"])

    def test_missing_model_answer_explains_cropped_section(self):
        response_stream = FakeResponse([])
        response_stream.choices = []
        output = io.StringIO()
        with patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "test-key"}), patch("ai_client.OpenAI") as client, redirect_stdout(output):
            client.return_value.chat.completions.create.return_value = response_stream
            response = self.upload()
        self.assertEqual(response.status_code, 502)
        self.assertIn("cropped section", response.json["error"])
        self.assertIn("No JSON answer", output.getvalue())

    def test_json_mode_rejects_unfinished_answer_even_if_json_parses(self):
        answer = FakeResponse([{"label": "Name", "guidance": "Enter a name", "box": [10, 20, 100, 50]}])
        answer.choices[0].finish_reason = "length"
        output = io.StringIO()
        with patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "test-key"}), patch("ai_client.OpenAI") as client, redirect_stdout(output):
            client.return_value.chat.completions.create.return_value = answer
            response = self.upload()
        self.assertEqual(response.status_code, 502)
        self.assertIn("Incomplete answer", output.getvalue())
        self.assertIn("cropped section", response.json["error"])

    def test_json_mode_rejects_reasoning_and_multiple_fenced_answers(self):
        answer = FakeResponse([])
        answer.choices[0].message.content = '```json\n{"fields":[]}\n```\nWait, more fields.\n```json\n{"fields":[]}\n```'
        with patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "test-key"}), patch("ai_client.OpenAI") as client, redirect_stdout(io.StringIO()):
            client.return_value.chat.completions.create.return_value = answer
            response = self.upload()
        self.assertEqual(response.status_code, 502)

    def test_json_code_fence_is_accepted_as_layout(self):
        response_stream = FakeResponse([])
        response_stream.choices[0].message.content = '```json\n{"fields": []}\n```'
        with patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "test-key"}), patch("ai_client.OpenAI") as client, redirect_stdout(io.StringIO()):
            client.return_value.chat.completions.create.return_value = response_stream
            response = self.upload()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"fields": [], "context": ""})

    def test_raw_model_output_is_not_logged(self):
        raw = '{"fields":[{"label":"Private account number","guidance":"Sensitive guidance","box":[10,20,100,40]}]}'
        response_stream = FakeResponse([])
        response_stream.choices[0].message.content = raw
        output = io.StringIO()
        with patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "test-key"}), patch("ai_client.OpenAI") as client, redirect_stdout(output):
            client.return_value.chat.completions.create.return_value = response_stream
            response = self.upload()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Private account number", output.getvalue())
        self.assertNotIn("Sensitive guidance", output.getvalue())
        self.assertNotIn("Raw gpt-6.1-sol output", output.getvalue())
        self.assertIn("[FormFriend] Parsed 1 fields", output.getvalue())

    def test_complete_unbracketed_field_objects_with_numbered_box_are_recovered(self):
        answer = ('```json\n{"fields": '
                  '{"label":"First name","guidance":"Enter a first name","box":[100,137,396,153]}, '
                  '{"label":"Last name","guidance":"Enter a last name","box2":[396,137,693,153]}}\n```')
        response_stream = FakeResponse([])
        response_stream.choices[0].message.content = answer
        with patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "test-key"}), patch("ai_client.OpenAI") as client, redirect_stdout(io.StringIO()):
            client.return_value.chat.completions.create.return_value = response_stream
            response = self.upload()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["fields"], [
            {"id": 0, "label": "First name", "guidance": "Enter a first name", "box": [100, 137, 296, 16]},
            {"id": 1, "label": "Last name", "guidance": "Enter a last name", "box": [396, 137, 297, 16]},
        ])

    def test_tenth_numbered_box_is_recovered(self):
        fields = [json.dumps({"label": f"Field {number}", "guidance": "Enter the value", f"box{number}": [10, 20, 100, 40]}) for number in range(2, 11)]
        answer = '{"fields": ' + ', '.join(fields) + '}'
        response_stream = FakeResponse([])
        response_stream.choices[0].message.content = answer
        with patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "test-key"}), patch("ai_client.OpenAI") as client, redirect_stdout(io.StringIO()):
            client.return_value.chat.completions.create.return_value = response_stream
            response = self.upload()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json["fields"]), 9)

    def test_incomplete_or_missing_box_in_unbracketed_fields_is_rejected(self):
        answers = (
            '{"fields": {"label":"Name","guidance":"Enter a name","box":[10,20,50,80]},',
            '{"fields": {"label":"Name","guidance":"Enter a name","box":[10,20,50,80]}, {"label":"Date","guidance":"Enter a date"}}',
        )
        for answer in answers:
            with self.subTest(answer=answer), patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "test-key"}), patch("ai_client.OpenAI") as client, redirect_stdout(io.StringIO()):
                response_stream = FakeResponse([])
                response_stream.choices[0].message.content = answer
                client.return_value.chat.completions.create.return_value = response_stream
                response = self.upload()
                self.assertEqual(response.status_code, 502)

    def test_model_connection_error_is_safe(self):
        error = APIConnectionError(request=httpx.Request("POST", "https://api.openai.com"), message="private path")
        with patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "test-key"}), patch("ai_client.OpenAI") as client:
            client.return_value.chat.completions.create.side_effect = error
            response = self.upload()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private path", response.get_data(as_text=True))
        self.assertIn("gpt-6.1-sol", response.json["error"])

    def test_model_name_in_request_and_error_follows_ai_model_setting(self):
        error = APIConnectionError(request=httpx.Request("POST", "https://api.openai.com"), message="offline")
        for model in ("gpt-6.1-sol", "alternate-model"):
            with self.subTest(model=model), patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "AI_MODEL": model, "OPENAI_API_KEY": "test-key"}), patch("ai_client.OpenAI") as client:
                client.return_value.chat.completions.create.side_effect = error
                response = self.upload()
                self.assertEqual(response.status_code, 503)
                self.assertEqual(client.return_value.chat.completions.create.call_args.kwargs["model"], model)
                self.assertIn(model, response.json["error"])

    def test_missing_key_does_not_call_provider(self):
        with tempfile.TemporaryDirectory() as directory, patch("ai_client.OPENAI_KEY_FILE", Path(directory) / "missing"), patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low"}, clear=True), patch("ai_client.OpenAI") as client:
            response = self.upload()
        self.assertEqual(response.status_code, 503)
        self.assertIn("OPENAI_API_KEY", response.json["error"])
        client.assert_not_called()

    def test_private_key_file_is_used_without_environment_variable(self):
        with tempfile.TemporaryDirectory() as directory:
            key_file = Path(directory) / "openai-key"
            key_file.write_text("file-test-key\n", encoding="utf-8")
            key_file.chmod(0o600)
            with patch("ai_client.OPENAI_KEY_FILE", key_file), patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low"}, clear=True), patch("ai_client.OpenAI") as client, redirect_stdout(io.StringIO()):
                client.return_value.chat.completions.create.return_value = FakeResponse([])
                response = self.upload()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(client.call_args.kwargs["api_key"], "file-test-key")

    def test_key_file_with_public_permissions_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            key_file = Path(directory) / "openai-key"
            key_file.write_text("file-test-key\n", encoding="utf-8")
            key_file.chmod(0o644)
            with patch("ai_client.OPENAI_KEY_FILE", key_file), patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low"}, clear=True), patch("ai_client.OpenAI") as client:
                response = self.upload()
            self.assertEqual(response.status_code, 503)
            self.assertIn("chmod 600", response.json["error"])
            client.assert_not_called()

    def test_provider_http_error_is_not_reported_as_unreachable(self):
        response_data = httpx.Response(401, request=httpx.Request("POST", "https://api.openai.com"), json={"error": "sensitive details"})
        error = APIStatusError("failed", response=response_data, body=response_data.json())
        with patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "test-key"}), patch("ai_client.OpenAI") as client:
            client.return_value.chat.completions.create.side_effect = error
            response = self.upload()
        self.assertEqual(response.status_code, 502)
        self.assertIn("HTTP 401", response.json["error"])
        self.assertNotIn("Could not reach", response.json["error"])
        self.assertNotIn("sensitive details", response.get_data(as_text=True))

    def test_provider_413_reports_request_size_not_key_access(self):
        response_data = httpx.Response(413, request=httpx.Request("POST", "https://api.openai.com"), json={"error": "sensitive details"})
        error = APIStatusError("failed", response=response_data, body=response_data.json())
        with patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "test-key"}), patch("ai_client.OpenAI") as client:
            client.return_value.chat.completions.create.side_effect = error
            response = self.upload()
        self.assertEqual(response.status_code, 502)
        self.assertIn("HTTP 413", response.json["error"])
        self.assertIn("too large", response.json["error"])
        self.assertNotIn("API key", response.json["error"])
        self.assertNotIn("sensitive details", response.get_data(as_text=True))

    def test_slow_model_reports_timeout_not_connection_failure(self):
        error = APITimeoutError(request=httpx.Request("POST", "https://api.openai.com"))
        with patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "test-key"}), patch("ai_client.OpenAI") as client:
            client.return_value.chat.completions.create.side_effect = error
            response = self.upload()
        self.assertEqual(response.status_code, 504)
        self.assertIn("longer", response.json["error"])
        self.assertNotIn("Could not reach", response.json["error"])
        self.assertEqual(client.call_args.kwargs["timeout"], 200)
        self.assertIn("200 seconds", response.json["error"])

    def test_page_serves_dashboard(self):
        with patch.dict("app.os.environ", {}, clear=True):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"FormFriend", response.data)
        self.assertIn(b"Images and selected PDF pages are sent to Anthropic", response.data)



class AskValidationTests(unittest.TestCase):
    valid = {"label": "Fictional name", "guidance": "Enter your full name", "question": "Should I include my middle name?"}

    def post(self, payload):
        return app.test_client().post("/api/ask", json=payload)

    def test_question_cases_rejected_before_provider_call(self):
        cases = [
            {k: v for k, v in self.valid.items() if k != "question"},
            {**self.valid, "question": ""},
            {**self.valid, "question": "   \n\t "},
            {**self.valid, "question": None},
            {**self.valid, "question": 42},
            {**self.valid, "question": ["Why?"]},
            {**self.valid, "question": "x" * 301},
            {**self.valid, "example": "x" * 61},
            {**self.valid, "example": 5},
            {**self.valid, "language": "xx"},
            {**self.valid, "label": ""},
            {**self.valid, "guidance": "x" * 601},
        ]
        for payload in cases:
            with self.subTest(payload={k: (v[:20] if isinstance(v, str) else v) for k, v in payload.items()}), \
                    patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "fictional-key"}, clear=True), patch("ai_client.OpenAI") as client:
                response = self.post(payload)
            self.assertEqual(response.status_code, 400)
            self.assertIn("error", response.json)
            client.assert_not_called()

    def test_question_at_limit_and_optional_example_are_sent_as_data(self):
        completion = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=json.dumps({"lines": ["Yes, if the form asks for your full legal name."]})))])
        payload = {**self.valid, "question": "q" * 300, "example": "Alex Smith"}
        with patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "fictional-key"}, clear=True), patch("ai_client.OpenAI") as client:
            client.return_value.chat.completions.create.return_value = completion
            response = self.post(payload)
        self.assertEqual(response.status_code, 200)
        sent = json.loads(client.return_value.chat.completions.create.call_args.kwargs["messages"][1]["content"])
        self.assertEqual(sent, {"label": "Fictional name", "guidance": "Enter your full name", "question": "q" * 300, "example": "Alex Smith"})

    def test_old_explain_route_is_removed(self):
        with patch("ai_client.OpenAI") as client:
            response = app.test_client().post("/api/explain", json={"label": "Name", "guidance": "Enter your name"})
        self.assertIn(response.status_code, (404, 405))
        client.assert_not_called()

if __name__ == "__main__":
    unittest.main()
