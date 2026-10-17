"""Hidden form context from /api/analyze. Fictional provider fixtures only; never makes an inference request."""
import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from app import ASK_PROMPT, app, clean_context

FIELD = {"label": "Full name", "guidance": "Enter your full name.", "box": [10, 20, 100, 80]}


class FormContextTests(unittest.TestCase):
    def analyze(self, raw, language="en"):
        image = io.BytesIO()
        Image.new("RGB", (80, 100), "white").save(image, format="PNG")
        image.seek(0)
        completion = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=raw))])
        with patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "fictional-test-key"}, clear=True), patch("ai_client.OpenAI") as client, redirect_stdout(io.StringIO()):
            client.return_value.chat.completions.create.return_value = completion
            response = app.test_client().post("/api/analyze", data={"image": (image, "fictional.png"), "language": language})
        self.create = client.return_value.chat.completions.create
        return response

    def analyze_obj(self, obj, language="en"):
        return self.analyze(json.dumps(obj), language)

    def test_context_is_returned_with_fields(self):
        context = "Fictional library card application from the Example County Library. Applicants must be county residents."
        response = self.analyze_obj({"fields": [FIELD], "context": context})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["context"], context)
        self.assertEqual(response.json["fields"][0]["box"], [10, 20, 90, 60])
        self.assertEqual(set(response.json), {"fields", "context"})

    def test_missing_context_returns_empty_string(self):
        response = self.analyze_obj({"fields": [FIELD]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["context"], "")
        self.assertEqual(len(response.json["fields"]), 1)

    def test_nonstring_context_does_not_fail_layout(self):
        for value in (None, 42, ["a"], {"a": "b"}, True):
            with self.subTest(value=value):
                response = self.analyze_obj({"fields": [FIELD], "context": value})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json["context"], "")
                self.assertEqual(len(response.json["fields"]), 1)

    def test_long_context_is_truncated_not_rejected(self):
        response = self.analyze_obj({"fields": [FIELD], "context": "A" * 5000})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["context"], "A" * 1500)
        self.assertEqual(len(response.json["fields"]), 1)

    def test_context_whitespace_is_collapsed(self):
        response = self.analyze_obj({"fields": [FIELD], "context": "  Fictional\n\nform.\t Section A:\r\n  details.  "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["context"], "Fictional form. Section A: details.")

    def test_context_allowed_with_no_fields(self):
        response = self.analyze_obj({"fields": [], "context": "Fictional informational notice with no fillable areas."})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"fields": [], "context": "Fictional informational notice with no fillable areas."})

    def test_bracketless_fallback_returns_empty_context(self):
        item = '{"label": "Full name", "guidance": "Enter your full name.", "box": [10, 20, 100, 80]}'
        response = self.analyze('{"fields": ' + item + ", " + item + "}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["context"], "")
        self.assertEqual(len(response.json["fields"]), 2)

    def test_prompt_requests_english_context_of_blank_form_only(self):
        self.analyze_obj({"fields": [], "context": ""}, "es")
        self.assertEqual(self.create.call_count, 1)
        system = self.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn('"fields" and "context"', system)
        self.assertIn("1500 characters", system)
        self.assertIn("NEVER copy", system)
        self.assertIn('Always write "context" in English', system)
        self.assertIn("Spanish", system)

    def test_long_guidance_is_truncated_to_600_and_accepted_by_ask(self):
        response = self.analyze_obj({"fields": [{**FIELD, "guidance": "  " + "G" * 900 + "  "}], "context": ""})
        self.assertEqual(response.status_code, 200)
        guidance = response.json["fields"][0]["guidance"]
        self.assertEqual(guidance, "G" * 600)
        completion = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=json.dumps({"lines": ["Write your full name."]})))])
        with patch.dict("app.os.environ", {"AI_PROVIDER": "openai", "AI_REASONING": "low", "OPENAI_API_KEY": "fictional-test-key"}, clear=True), patch("ai_client.OpenAI") as client:
            client.return_value.chat.completions.create.return_value = completion
            ask = app.test_client().post("/api/ask", json={"label": "Full name", "guidance": guidance, "question": "What goes here?"})
        self.assertEqual(ask.status_code, 200)
        self.assertEqual(ask.json, {"lines": ["Write your full name."]})

    def test_prompt_requests_one_to_two_plain_sentences_of_guidance(self):
        self.analyze_obj({"fields": [], "context": ""})
        system = self.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn('"guidance": 1 to 2 full, plain-language sentences', system)
        self.assertIn("at most 300 characters", system)
        self.assertIn("written simply for a beginner", system)
        self.assertNotIn("a short description of what belongs there", system)

    def test_ask_prompt_requires_basic_plain_language(self):
        self.assertIn("someone who only understands basic terms", ASK_PROMPT)
        self.assertIn("5th to 6th grade reading level", ASK_PROMPT)
        self.assertIn("no jargon", ASK_PROMPT)
        self.assertIn("explain what it means in simple words", ASK_PROMPT)
        for rule in ("1 to 5", "300 characters", "untrusted data", "Do not invent personal facts",
                     "official instructions", "only help with this form field", "'lines'"):
            self.assertIn(rule, ASK_PROMPT)

    def test_clean_context_unit(self):
        self.assertEqual(clean_context(None), "")
        self.assertEqual(clean_context(7), "")
        self.assertEqual(clean_context("   "), "")
        self.assertEqual(clean_context(" a \n b "), "a b")
        self.assertEqual(len(clean_context("x " * 2000)), 1500 - 1)  # trailing space stripped after truncation


if __name__ == "__main__":
    unittest.main()
