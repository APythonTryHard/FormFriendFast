"""Provider-neutral model calls for FormFriend (Anthropic or OpenAI).

Configuration is read from the environment on every call so it can be changed
per deployment (and patched in tests) without code edits:

    AI_PROVIDER    anthropic | openai             (default: anthropic)
    AI_MODEL       model ID                        (default depends on provider)
    AI_REASONING   low | medium | high             (default: medium)

Per-task overrides take precedence over the global values:
ANALYZE_PROVIDER / ANALYZE_MODEL / ANALYZE_REASONING and
ASK_PROVIDER / ASK_MODEL / ASK_REASONING.
"""
import base64
import os
import stat
from dataclasses import dataclass
from pathlib import Path

import anthropic
from anthropic import Anthropic
from openai import OpenAI
import openai

OPENAI_URL = "https://api.openai.com/v1"
_KEY_DIR = Path.home() / ".config" / "formfriend"
OPENAI_KEY_FILE = _KEY_DIR / "openai-key"
ANTHROPIC_KEY_FILE = _KEY_DIR / "anthropic-key"

DEFAULT_PROVIDER = "anthropic"
DEFAULT_MODELS = {"anthropic": "claude-opus-5-5", "openai": "gpt-6.1-sol"}
DEFAULT_REASONING = "medium"
REASONING_LEVELS = ("low", "medium", "high")
DISPLAY_NAMES = {"anthropic": "Anthropic", "openai": "OpenAI"}
KEY_ENV_VARS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
TASKS = ("analyze", "ask")


class AIError(Exception):
    """Base class for provider-neutral model failures."""


class AIConfigError(AIError):
    """Configuration or API key problem; message is safe to show the user."""


class AITimeout(AIError):
    pass


class AIConnectionError(AIError):
    pass


class AIStatusError(AIError):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class AIIncomplete(AIError):
    """The model stopped for a reason other than a normal completion."""


@dataclass(frozen=True)
class AIConfig:
    provider: str
    model: str
    reasoning: str

    @property
    def display_name(self):
        return DISPLAY_NAMES[self.provider]


def _env(name):
    value = os.environ.get(name, "").strip()
    return value or None


def get_config(task):
    """Resolve provider/model/reasoning: task override > global > default."""
    if task not in TASKS:
        raise AIConfigError(f"Unknown AI task {task!r}.")
    prefix = task.upper()
    global_provider = (_env("AI_PROVIDER") or DEFAULT_PROVIDER).lower()
    provider = (_env(f"{prefix}_PROVIDER") or global_provider).lower()
    if provider not in DEFAULT_MODELS:
        raise AIConfigError(f"Unsupported AI provider {provider!r}. Set {prefix}_PROVIDER or AI_PROVIDER to 'anthropic' or 'openai'.")
    # AI_MODEL belongs to AI_PROVIDER: when a task switches to another provider
    # without its own model, use that provider's default instead.
    global_model = _env("AI_MODEL") if provider == global_provider else None
    model = _env(f"{prefix}_MODEL") or global_model or DEFAULT_MODELS[provider]
    reasoning = (_env(f"{prefix}_REASONING") or _env("AI_REASONING") or DEFAULT_REASONING).lower()
    if reasoning not in REASONING_LEVELS:
        raise AIConfigError(f"Invalid AI reasoning level {reasoning!r}. Set {prefix}_REASONING or AI_REASONING to low, medium or high.")
    return AIConfig(provider, model, reasoning)


def display_name(task):
    """Provider name for UI text; falls back to the default if misconfigured."""
    try:
        return get_config(task).display_name
    except AIConfigError:
        return DISPLAY_NAMES[DEFAULT_PROVIDER]


def load_api_key(provider):
    env_var = KEY_ENV_VARS[provider]
    key_file = ANTHROPIC_KEY_FILE if provider == "anthropic" else OPENAI_KEY_FILE
    name = DISPLAY_NAMES[provider]
    api_key = os.environ.get(env_var)
    if not api_key:
        try:
            info = key_file.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                raise AIConfigError(f"{name} key file must be a private regular file (chmod 600).")
            api_key = key_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            pass
        except (OSError, UnicodeError):
            raise AIConfigError(f"Could not read the {name} key file. Check its permissions.") from None
    if not api_key:
        raise AIConfigError(f"Set {env_var} or add your key to ~/.config/formfriend/{key_file.name}.")
    return api_key


def complete_json(task, system_prompt, user_text, image_jpeg_bytes=None, *, max_tokens, timeout, config=None):
    """Return the model's raw text answer (expected to be JSON).

    `max_tokens` applies to OpenAI; Anthropic uses ANTHROPIC_MAX_TOKENS because
    its budget must also cover adaptive thinking. Raises AIError subclasses.
    """
    config = config or get_config(task)
    api_key = load_api_key(config.provider)
    if config.provider == "openai":
        return _openai_complete(config, api_key, system_prompt, user_text, image_jpeg_bytes, max_tokens, timeout)
    return _anthropic_complete(config, api_key, system_prompt, user_text, image_jpeg_bytes, ANTHROPIC_MAX_TOKENS[task], timeout)


# Adaptive thinking shares max_tokens with the visible answer.
ANTHROPIC_MAX_TOKENS = {"analyze": 32_000, "ask": 8_000}


def _openai_complete(config, api_key, system_prompt, user_text, image, max_tokens, timeout):
    if image is None:
        user_content = user_text
    else:
        user_content = [
            {"type": "text", "text": user_text},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64.b64encode(image).decode('ascii')}"}},
        ]
    try:
        client = OpenAI(base_url=OPENAI_URL, api_key=api_key, timeout=timeout, max_retries=0)
        request = dict(
            model=config.model,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}],
            max_completion_tokens=max_tokens,
            reasoning_effort=config.reasoning,
            response_format={"type": "json_object"},
        )
        if image is not None:
            request["stream"] = False
        completion = client.chat.completions.create(**request)
    except openai.APITimeoutError:
        raise AITimeout() from None
    except openai.APIConnectionError:
        raise AIConnectionError() from None
    except openai.APIStatusError as error:
        raise AIStatusError(error.status_code) from None
    if not completion.choices:
        return ""  # Callers treat an empty answer as "no JSON answer".
    choice = completion.choices[0]
    raw = choice.message.content or ""
    if raw and choice.finish_reason != "stop":
        raise AIIncomplete(f"finish_reason={choice.finish_reason}")
    return raw


def _anthropic_complete(config, api_key, system_prompt, user_text, image, max_tokens, timeout):
    content = []
    if image is not None:
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                    "data": base64.b64encode(image).decode("ascii")}})
    content.append({"type": "text", "text": user_text})
    try:
        client = Anthropic(api_key=api_key, timeout=timeout, max_retries=0)
        message = client.messages.create(
            model=config.model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": content}],
            thinking={"type": "adaptive"},
            output_config={"effort": config.reasoning},
            stream=False,
        )
    except anthropic.APITimeoutError:
        raise AITimeout() from None
    except anthropic.APIConnectionError:
        raise AIConnectionError() from None
    except anthropic.APIStatusError as error:
        raise AIStatusError(error.status_code) from None
    raw = "".join(getattr(block, "text", "") or "" for block in (message.content or []) if getattr(block, "type", None) == "text")
    if message.stop_reason != "end_turn":
        raise AIIncomplete(f"stop_reason={message.stop_reason}")
    return raw
