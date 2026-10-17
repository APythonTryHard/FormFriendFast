"""Provider configuration and Anthropic adapter checks; never contacts a provider."""
import base64
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import anthropic
import httpx
from anthropic import Anthropic
from PIL import Image

import ai_client
from app import app

FIELD = {"label": "Full name", "guidance": "Enter your legal full name.", "question": "Middle name too?"}
ANTHROPIC_ENV = {"ANTHROPIC_API_KEY": "fictional-anthropic-key"}
LAYOUT = '{"fields":[{"label":"Full name","guidance":"Your name.","box":[100,200,500,280]}],"context":"Fictional library card form."}'


def png_bytes():
    output = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(output, "PNG")
    return output.getvalue()


def message(*blocks, stop_reason="end_turn"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason)


def text(value):
    return SimpleNamespace(type="text", text=value)


def thinking(value):
    return SimpleNamespace(type="thinking", thinking=value, signature="fictional-signature")


def upload():
    return app.test_client().post("/api/analyze", data={"image": (io.BytesIO(png_bytes()), "form.png")}, content_type="multipart/form-data")


class ConfigTests(unittest.TestCase):
    def config(self, task, env):
        with patch.dict("os.environ", env, clear=True):
            return ai_client.get_config(task)

    def test_defaults_are_anthropic_opus_medium_for_both_tasks(self):
        for task in ("analyze", "ask"):
            self.assertEqual(self.config(task, {}), ai_client.AIConfig("anthropic", "claude-opus-5-5", "medium"))

    def test_openai_provider_uses_its_default_model(self):
        self.assertEqual(self.config("ask", {"AI_PROVIDER": "openai"}), ai_client.AIConfig("openai", "gpt-6.1-sol", "medium"))

    def test_global_settings_apply_to_both_tasks(self):
        env = {"AI_PROVIDER": "OpenAI", "AI_MODEL": "fictional-model", "AI_REASONING": "Low"}
        for task in ("analyze", "ask"):
            self.assertEqual(self.config(task, env), ai_client.AIConfig("openai", "fictional-model", "low"))

    def test_task_overrides_win_over_global_settings(self):
        env = {"AI_PROVIDER": "anthropic", "AI_MODEL": "claude-fictional", "AI_REASONING": "medium",
               "ASK_MODEL": "claude-fictional-fast", "ASK_REASONING": "low", "ANALYZE_REASONING": "high"}
        self.assertEqual(self.config("ask", env), ai_client.AIConfig("anthropic", "claude-fictional-fast", "low"))
        self.assertEqual(self.config("analyze", env), ai_client.AIConfig("anthropic", "claude-fictional", "high"))

    def test_task_provider_override_uses_that_providers_default_model(self):
        env = {"AI_MODEL": "claude-fictional", "ASK_PROVIDER": "openai"}
        self.assertEqual(self.config("ask", env), ai_client.AIConfig("openai", "gpt-6.1-sol", "medium"))
        self.assertEqual(self.config("analyze", env), ai_client.AIConfig("anthropic", "claude-fictional", "medium"))

    def test_invalid_values_raise_config_error(self):
        for env in ({"AI_REASONING": "extreme"}, {"ASK_REASONING": "max"}, {"AI_PROVIDER": "fictional-cloud"}):
            with self.subTest(env=env), self.assertRaises(ai_client.AIConfigError):
                self.config("ask", env)

    def test_invalid_reasoning_returns_503_from_both_routes_without_calling_provider(self):
        with patch.dict("app.os.environ", {**ANTHROPIC_ENV, "AI_REASONING": "extreme"}, clear=True), \
                patch("ai_client.Anthropic") as client, patch("ai_client.OpenAI") as openai_client:
            ask = app.test_client().post("/api/ask", json=FIELD)
            analyze = upload()
        for response in (ask, analyze):
            self.assertEqual(response.status_code, 503)
            self.assertIn("AI_REASONING", response.json["error"])
            self.assertIn("low, medium or high", response.json["error"])
        client.assert_not_called()
        openai_client.assert_not_called()


class AnthropicRequestTests(unittest.TestCase):
    def test_analyze_request_shape(self):
        with patch.dict("app.os.environ", ANTHROPIC_ENV, clear=True), patch("ai_client.Anthropic") as client, redirect_stdout(io.StringIO()):
            client.return_value.messages.create.return_value = message(thinking("private reasoning"), text(LAYOUT))
            response = upload()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["fields"][0]["box"], [100, 200, 400, 80])
        self.assertEqual(response.json["context"], "Fictional library card form.")
        self.assertNotIn("private reasoning", response.get_data(as_text=True))
        self.assertEqual(client.call_args.kwargs, {"api_key": "fictional-anthropic-key", "timeout": 200, "max_retries": 0})
        payload = client.return_value.messages.create.call_args.kwargs
        self.assertEqual(payload["model"], "claude-opus-5-5")
        self.assertEqual(payload["max_tokens"], 32_000)
        self.assertEqual(payload["thinking"], {"type": "adaptive"})
        self.assertEqual(payload["output_config"], {"effort": "medium"})
        self.assertFalse(payload["stream"])
        self.assertIn("Inspect the attached form image", payload["system"])
        self.assertNotIn("response_format", payload)
        self.assertNotIn("format", payload["output_config"])
        [user] = payload["messages"]
        self.assertEqual(user["role"], "user")
        image, instruction = user["content"]
        self.assertEqual(image["type"], "image")
        self.assertEqual(image["source"]["type"], "base64")
        self.assertEqual(image["source"]["media_type"], "image/jpeg")
        with Image.open(io.BytesIO(base64.b64decode(image["source"]["data"]))) as sent:
            self.assertEqual(sent.format, "JPEG")
        self.assertEqual(instruction["type"], "text")
        self.assertIn("Return only the JSON object", instruction["text"])

    def test_ask_request_shape_and_text_only_concatenation(self):
        with patch.dict("app.os.environ", {**ANTHROPIC_ENV, "ASK_REASONING": "low"}, clear=True), patch("ai_client.Anthropic") as client:
            client.return_value.messages.create.return_value = message(
                thinking('{"lines":["not this"]}'), text('{"lines":["Include it'), text(' if the form asks."]}'))
            response = app.test_client().post("/api/ask", json=FIELD)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"lines": ["Include it if the form asks."]})
        self.assertEqual(client.call_args.kwargs["timeout"], 90)
        payload = client.return_value.messages.create.call_args.kwargs
        self.assertEqual(payload["max_tokens"], 8_000)
        self.assertEqual(payload["thinking"], {"type": "adaptive"})
        self.assertEqual(payload["output_config"], {"effort": "low"})
        self.assertIn("1 to 5", payload["system"])
        [block] = payload["messages"][0]["content"]
        self.assertEqual(block["type"], "text")
        self.assertEqual(json.loads(block["text"]), FIELD)

    def test_ask_accepts_single_json_fence(self):
        for provider in ("anthropic", "openai"):
            raw = '\n```json\n{"lines":["Use your legal name."]}\n```\n'
            env = {**ANTHROPIC_ENV, "OPENAI_API_KEY": "fictional-openai-key", "AI_PROVIDER": provider}
            with self.subTest(provider=provider), patch.dict("app.os.environ", env, clear=True), \
                    patch("ai_client.Anthropic") as claude, patch("ai_client.OpenAI") as openai_client:
                claude.return_value.messages.create.return_value = message(text(raw))
                openai_client.return_value.chat.completions.create.return_value = SimpleNamespace(
                    choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=raw))])
                response = app.test_client().post("/api/ask", json=FIELD)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json, {"lines": ["Use your legal name."]})

    def test_non_end_turn_stop_reason_is_incomplete_502(self):
        for stop_reason in ("max_tokens", "refusal", "pause_turn"):
            with self.subTest(stop_reason=stop_reason), patch.dict("app.os.environ", ANTHROPIC_ENV, clear=True), \
                    patch("ai_client.Anthropic") as client, redirect_stdout(io.StringIO()):
                client.return_value.messages.create.return_value = message(text(LAYOUT), stop_reason=stop_reason)
                analyze = upload()
                client.return_value.messages.create.return_value = message(text('{"lines":["One"]}'), stop_reason=stop_reason)
                ask = app.test_client().post("/api/ask", json=FIELD)
            self.assertEqual(analyze.status_code, 502)
            self.assertIn("claude-opus-5-5 did not finish", analyze.json["error"])
            self.assertEqual(ask.status_code, 502)
            self.assertIn("answer", ask.json["error"])

    def test_sdk_errors_map_to_safe_statuses(self):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        cases = [
            (anthropic.APITimeoutError(request=request), 504, "took longer than 200 seconds"),
            (anthropic.APIConnectionError(request=request, message="private path"), 503, "Could not reach Anthropic for claude-opus-5-5"),
            (anthropic.APIStatusError("private details", response=httpx.Response(429, request=request), body={"error": "private"}), 502,
             "Anthropic rejected the claude-opus-5-5 request (HTTP 429)"),
        ]
        for error, status, expected in cases:
            with self.subTest(status=status), patch.dict("app.os.environ", ANTHROPIC_ENV, clear=True), patch("ai_client.Anthropic") as client:
                client.return_value.messages.create.side_effect = error
                response = upload()
            self.assertEqual(response.status_code, status)
            self.assertIn(expected, response.json["error"])
            self.assertNotIn("private", response.get_data(as_text=True))

    def test_ask_sdk_errors_map_to_safe_statuses(self):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        cases = [(anthropic.APITimeoutError(request=request), 504),
                 (anthropic.APIConnectionError(request=request, message="private path"), 503),
                 (anthropic.APIStatusError("private details", response=httpx.Response(401, request=request), body=None), 502)]
        for error, status in cases:
            with self.subTest(status=status), patch.dict("app.os.environ", ANTHROPIC_ENV, clear=True), patch("ai_client.Anthropic") as client:
                client.return_value.messages.create.side_effect = error
                response = app.test_client().post("/api/ask", json=FIELD)
            self.assertEqual(response.status_code, status)
            self.assertNotIn("private", response.get_data(as_text=True))

    def test_missing_anthropic_key_returns_503_naming_variable(self):
        with tempfile.TemporaryDirectory() as directory, patch("ai_client.ANTHROPIC_KEY_FILE", Path(directory) / "missing"), \
                patch.dict("app.os.environ", {"OPENAI_API_KEY": "fictional-openai-key"}, clear=True), patch("ai_client.Anthropic") as client:
            analyze = upload()
            ask = app.test_client().post("/api/ask", json=FIELD)
        for response in (analyze, ask):
            self.assertEqual(response.status_code, 503)
            self.assertIn("ANTHROPIC_API_KEY", response.json["error"])
        client.assert_not_called()

    def test_private_anthropic_key_file_is_used(self):
        with tempfile.TemporaryDirectory() as directory:
            key_file = Path(directory) / "anthropic-key"
            key_file.write_text("fictional-file-key\n", encoding="utf-8")
            key_file.chmod(0o600)
            with patch("ai_client.ANTHROPIC_KEY_FILE", key_file), patch.dict("app.os.environ", {}, clear=True), patch("ai_client.Anthropic") as client:
                client.return_value.messages.create.return_value = message(text('{"lines":["One"]}'))
                response = app.test_client().post("/api/ask", json=FIELD)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(client.call_args.kwargs["api_key"], "fictional-file-key")
            key_file.chmod(0o644)
            with patch("ai_client.ANTHROPIC_KEY_FILE", key_file), patch.dict("app.os.environ", {}, clear=True), patch("ai_client.Anthropic") as client:
                response = app.test_client().post("/api/ask", json=FIELD)
            self.assertEqual(response.status_code, 503)
            self.assertIn("chmod 600", response.json["error"])
            client.assert_not_called()

    def test_real_sdk_serializes_adaptive_thinking_and_effort(self):
        requests = []

        def respond(request):
            self.assertEqual(str(request.url), "https://api.anthropic.com/v1/messages")
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={
                "id": "msg_fictional", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
                "content": [{"type": "thinking", "thinking": "private", "signature": "fictional"},
                            {"type": "text", "text": '{"lines":["One","Two"]}'}],
                "stop_reason": "end_turn", "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}})

        with Anthropic(api_key="fictional-key", http_client=httpx.Client(transport=httpx.MockTransport(respond))) as real_client:
            with patch.dict("app.os.environ", ANTHROPIC_ENV, clear=True), patch("ai_client.Anthropic", return_value=real_client):
                response = app.test_client().post("/api/ask", json=FIELD)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"lines": ["One", "Two"]})
        sent = requests[0]
        self.assertEqual(sent["model"], "claude-opus-5-5")
        self.assertEqual(sent["thinking"], {"type": "adaptive"})
        self.assertEqual(sent["output_config"], {"effort": "medium"})
        self.assertEqual(sent["max_tokens"], 8_000)
        self.assertIsInstance(sent["system"], str)


class TemplateProviderTests(unittest.TestCase):
    def page(self, env):
        with patch.dict("app.os.environ", env, clear=True):
            return app.test_client().get("/").get_data(as_text=True)

    def test_default_page_names_anthropic(self):
        page = self.page({})
        self.assertIn("Images and selected PDF pages are sent to Anthropic for analysis.", page)
        self.assertIn('aria-valuetext="Analyzing with Anthropic"', page)
        self.assertIn("summary of the form to Anthropic.", page)
        self.assertNotIn("OpenAI", page)

    def test_openai_provider_page_names_openai(self):
        page = self.page({"AI_PROVIDER": "openai"})
        self.assertIn("Images and selected PDF pages are sent to OpenAI for analysis.", page)
        self.assertIn('aria-valuetext="Analyzing with OpenAI"', page)
        self.assertIn("summary of the form to OpenAI.", page)
        self.assertNotIn("Anthropic", page)

    def test_per_task_providers_are_named_separately(self):
        page = self.page({"ASK_PROVIDER": "openai"})
        self.assertIn("sent to Anthropic for analysis.", page)
        self.assertIn("summary of the form to OpenAI.", page)


if __name__ == "__main__":
    unittest.main()
