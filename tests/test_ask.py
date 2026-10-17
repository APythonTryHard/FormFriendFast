import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from openai import APIStatusError, APITimeoutError, OpenAI

from app import app

FIELD = {"label": "Name", "guidance": "Enter your name", "question": "Do I include my middle name?"}


def completion(result, finish_reason="stop"):
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish_reason, message=SimpleNamespace(content=json.dumps(result)))])


class AskTests(unittest.TestCase):
    def test_ask_returns_one_to_four_lines_with_low_reasoning(self):
        lines = ["Use the amount from Form W-2 box 1.", "Check the issuer's instructions if unsure."]
        with patch.dict("app.os.environ", {"OPENAI_API_KEY": "fictional-key"}, clear=True), patch("app.OpenAI") as client:
            client.return_value.chat.completions.create.return_value = completion({"lines": lines})
            response = app.test_client().post("/api/ask", json={"label": "Income line 1a", "guidance": "Enter total wages from Form W-2 box 1.", "question": "Which box do I use?"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"lines": lines})
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        payload = client.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(payload["reasoning_effort"], "low")
        system = payload["messages"][0]["content"]
        self.assertIn("1 to 4", system)
        self.assertIn("untrusted data", system)
        self.assertIn("English", system)
        user = json.loads(payload["messages"][1]["content"])
        self.assertEqual(user, {"label": "Income line 1a", "guidance": "Enter total wages from Form W-2 box 1.", "question": "Which box do I use?"})
        self.assertNotIn("image_url", json.dumps(payload))

    def test_single_line_off_topic_style_answer_is_valid(self):
        with patch.dict("app.os.environ", {"OPENAI_API_KEY": "fictional-key"}, clear=True), patch("app.OpenAI") as client:
            client.return_value.chat.completions.create.return_value = completion({"lines": ["I can only help with this form field."]})
            response = app.test_client().post("/api/ask", json={**FIELD, "question": "What's the weather?"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json["lines"]), 1)

    def test_rejects_invalid_field_or_question_before_calling_provider(self):
        for payload in (None, [], {}, {"label": "Name", "guidance": "", "question": "Why?"}, {"label": "x" * 1001, "guidance": "Enter value", "question": "Why?"},
                        {"label": "Name", "guidance": "Enter value"}, {**FIELD, "question": "  "}, {**FIELD, "question": "x" * 301}):
            with self.subTest(payload=payload), patch("app.OpenAI") as client:
                response = app.test_client().post("/api/ask", json=payload)
            self.assertEqual(response.status_code, 400)
            client.assert_not_called()

    def test_rejects_incomplete_or_wrong_length_answers(self):
        cases = [("stop", {"lines": []}), ("length", {"lines": ["One"]}),
                 ("stop", {"lines": ["One", "Two", "Three", "Four", "Five"]}),
                 ("stop", {"lines": ["One\nMore"]}), ("stop", {"lines": ["x" * 301]}), ("stop", {"answer": "One"})]
        for finish_reason, result in cases:
            with self.subTest(result=result), patch.dict("app.os.environ", {"OPENAI_API_KEY": "fictional-key"}, clear=True), patch("app.OpenAI") as client:
                client.return_value.chat.completions.create.return_value = completion(result, finish_reason)
                response = app.test_client().post("/api/ask", json=FIELD)
            self.assertEqual(response.status_code, 502)
            self.assertNotIn("lines", response.json)
            self.assertIn("answer", response.json["error"])

    def test_missing_key_does_not_call_provider(self):
        with tempfile.TemporaryDirectory() as directory, patch("app.KEY_FILE", Path(directory) / "missing"), patch.dict("app.os.environ", {}, clear=True), patch("app.OpenAI") as client:
            response = app.test_client().post("/api/ask", json=FIELD)
        self.assertEqual(response.status_code, 503)
        client.assert_not_called()

    def test_provider_errors_are_safe_and_allow_retry(self):
        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        errors = [(APITimeoutError(request=request), 504),
                  (APIStatusError("private provider details", response=httpx.Response(401, request=request), body={"error": "private"}), 502)]
        for error, status in errors:
            with self.subTest(status=status), patch.dict("app.os.environ", {"OPENAI_API_KEY": "fictional-key"}, clear=True), patch("app.OpenAI") as client:
                client.return_value.chat.completions.create.side_effect = error
                response = app.test_client().post("/api/ask", json=FIELD)
            self.assertEqual(response.status_code, status)
            self.assertNotIn("private", response.get_data(as_text=True))

    def test_real_sdk_serializes_text_only_ask_request(self):
        requests = []

        def respond(request):
            self.assertEqual(str(request.url), "https://api.openai.com/v1/chat/completions")
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "fictional", "object": "chat.completion", "created": 1,
                                           "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": '{"lines":["One","Two"]}'}}]})

        with OpenAI(api_key="fictional-key", http_client=httpx.Client(transport=httpx.MockTransport(respond))) as real_client:
            with patch.dict("app.os.environ", {"OPENAI_API_KEY": "fictional-key"}, clear=True), patch("app.OpenAI", return_value=real_client):
                response = app.test_client().post("/api/ask", json=FIELD)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(requests[0]["reasoning_effort"], "low")
        self.assertEqual(requests[0]["response_format"], {"type": "json_object"})
        self.assertNotIn("image_url", json.dumps(requests[0]))


if __name__ == "__main__":
    unittest.main()
