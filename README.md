# FormFriendFast

Understand what belongs in each field on a form. Upload an image or PDF, select a language, and click a highlighted field for guidance or ask a question about it.

## Features

- Image normalization, including HEIC/HEIF, with an 8 MB upload limit.
- On Android and other non-iOS touch devices, tapping the upload area offers a photo (library or camera, as the browser allows) or a PDF/file. On iPhone and iPad it opens the native chooser directly, since iOS already shows its own Photo Library / Take Photo / Choose File menu. Desktop keeps click-to-choose and drag-and-drop.
- Every new upload asks you to confirm the help language (preselected to your last choice) before anything is sent; Cancel discards the file. Reloads, PDF page changes and the top language picker skip this step.
- PDFs up to 20 pages, with page selection and local rendering.
- Field overlays and plain-language guidance in 74 selectable languages, with a short fictional example entry where a safe one exists (the model is told to omit examples for IDs, payment, medical, and attestation fields; SSN- and card-shaped values are dropped server-side).
- On phones, the Fields panel shows one field at a time with previous/next controls; tapping a highlighted box jumps to it.
- Ask a question about the selected field (desktop and mobile); the latest answer per field is saved. Analysis also produces a hidden summary of the blank form (purpose, sections, printed instructions) that is sent with questions so answers can be fuller; it is never displayed.
- Per-page/per-language result and answer caching in the browser.
- The current document survives reloads; **Start over** clears its saved browser record.

## Deploy on Render (Free)

1. Push this repository to GitHub. In Render choose **New → Web Service** and connect the repository. Authorize Render to access it if it is private.
2. Choose the Python runtime, repository root (leave Root Directory blank), branch `main`, and **Free** instance.
3. Set these commands exactly:

   **Build command**
   ```sh
   pip install -r requirements.txt
   ```
   **Start command**
   ```sh
   gunicorn app:app
   ```
4. Under **Environment**, add `ANTHROPIC_API_KEY` with your Claude API key (or `OPENAI_API_KEY` if you use OpenAI) plus the model settings below. Do not put the key in source code, GitHub, or a browser-side script.
5. Set **Health Check Path** to `/healthz`, then deploy.

Alternatively create a Render Blueprint using the included `render.yaml`; it declares the same commands, the default model settings, and prompts for the API keys. A service created manually in the dashboard does not read `render.yaml`: set the environment variables in the Render dashboard (**Environment** tab) and redeploy.

`gunicorn.conf.py` automatically binds to `0.0.0.0:$PORT`, uses one worker with two threads, and allows 260 seconds for requests so the application's 200-second analysis timeout is not cut off by Gunicorn's default. Run the start command from the repository root so this configuration is loaded. Python is pinned in `.python-version`.

### Model and account access

By default both analysis and field questions use Anthropic **`claude-opus-5-5`** at **medium** effort (adaptive thinking), via the official `anthropic` SDK. The server calls the provider's API directly; it does not use a Claude, ChatGPT or Hermes session. Your API account must have access to the configured model ID and sufficient API credit. Model access has not been verified with a paid live request. An API rejection is shown as an error; there is no silent model fallback.

### Choosing the AI model

Settings are read from environment variables (on Render: dashboard → **Environment**, then redeploy). No code change is needed to switch.

| Variable | Values | Default |
| --- | --- | --- |
| `AI_PROVIDER` | `anthropic`, `openai` | `anthropic` |
| `AI_MODEL` | model ID for that provider | `claude-opus-5-5` (anthropic), `gpt-6.1-sol` (openai) |
| `AI_REASONING` | `low`, `medium`, `high` | `medium` |
| `ANTHROPIC_API_KEY` | Claude API key | — (or `~/.config/formfriend/anthropic-key`, chmod 600) |
| `OPENAI_API_KEY` | OpenAI API key | — (or `~/.config/formfriend/openai-key`, chmod 600) |

For Anthropic, `AI_REASONING` sets the effort level with adaptive thinking; for OpenAI it sets `reasoning_effort`. An invalid provider or reasoning value makes analysis and questions return a configuration error (HTTP 503) instead of calling a model.

Switch back to the previous OpenAI setup: `AI_PROVIDER=openai`, `AI_MODEL=gpt-6.1-sol`, `AI_REASONING=low` (with `OPENAI_API_KEY` set).

Per-task overrides take precedence over the global values: `ANALYZE_PROVIDER`, `ANALYZE_MODEL`, `ANALYZE_REASONING` for form analysis and `ASK_PROVIDER`, `ASK_MODEL`, `ASK_REASONING` for field questions. For example, `ASK_REASONING=low` keeps analysis at medium but answers questions faster. If a task overrides the provider without its own model, that provider's default model is used (the global `AI_MODEL` only applies to `AI_PROVIDER`). The page's privacy text names the provider each feature uses.

### Hosting and cost caveats

Render's Free service can spin down after 15 minutes without inbound traffic, so the first visit afterward can take about a minute to wake it. Free services are intended for hobby/testing use, not production guarantees. AI provider requests are separate from Render hosting and may incur API charges.

**This app currently has no user authentication or rate limiting. Anyone with the deployed URL can submit requests billed to your server's API key.** Use it as a limited demo only; add authentication, abuse controls, and spending monitoring before promoting it publicly. A private GitHub repository does not make a deployed web service private.

## Privacy and limitations

- Images and selected PDF pages are sent to the configured AI provider (Anthropic by default) for analysis. Asking about a field sends your question, the field's label, guidance and example, and the hidden form summary (which describes the blank form and is instructed not to copy filled-in information).
- The current document, previews, results, and your questions and answers are stored in IndexedDB in the user's browser. Multi-page PDFs also retain their original PDF there. Do not upload sensitive documents on shared browsers; use **Start over** or clear site data afterward.
- Application code does not write uploaded forms to server files. Extracted content is not printed to application logs; operational status and errors are logged.
- PDFs are rendered locally before inference. Encrypted PDFs are rejected. Animated or multi-page images use only the first frame/page.
- AI guidance can be incorrect. Check the original form and official instructions. This is not personalized legal, tax, medical, or financial advice.
- The app explains fields and answers questions about them; it does not fill forms or export completed documents.

## Local development

Use Python 3.12 or newer:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Set ANTHROPIC_API_KEY (or AI_PROVIDER=openai and OPENAI_API_KEY) in your shell before analysis.
python app.py
```

Visit `http://127.0.0.1:5001`. The development entry point has debug mode disabled. For a production-server smoke test:

```sh
PORT=8000 gunicorn app:app
```

The app also supports local key files at `~/.config/formfriend/anthropic-key` and `~/.config/formfriend/openai-key` with permissions `600`. On Render use `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` instead. `.env.example` is a reference only; `.env` files are not loaded automatically.

## Tests

```sh
python -m unittest discover -s tests -v
gunicorn --check-config app:app
```

Python tests use fake provider responses and do not spend API credit. Browser tests under `tests/*.cjs` include lightweight Node-only frontend checks and separate Playwright checks; the latter require Playwright and test-specific fixtures. GitHub Actions runs the Python suite and checks Gunicorn configuration.

## Dependency maintenance

`pyproject.toml` declares the runtime dependencies; `uv.lock` locks resolution. `requirements.txt` is the exported deployment dependency set, including Gunicorn. When updating dependencies with uv:

```sh
uv lock
uv export --frozen --no-dev --no-emit-project --no-hashes -o requirements.txt
```

Keep all three files in sync.

## Deployment references

- [Render Flask deployment guide](https://render.com/docs/deploy-flask)
- [Render Free service limitations](https://render.com/docs/free)
- [Anthropic API documentation](https://docs.anthropic.com/)
- [OpenAI API quickstart](https://developers.openai.com/api/docs/quickstart)
