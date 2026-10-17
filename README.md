# FormFriendFast

Understand what belongs in each field on a form. Upload an image or PDF, select a language, and click a highlighted field for guidance or ask a question about it.

## Features

- Image normalization, including HEIC/HEIF, with an 8 MB upload limit.
- On Android and other non-iOS touch devices, tapping the upload area offers a photo (library or camera, as the browser allows) or a PDF/file. On iPhone and iPad it opens the native chooser directly, since iOS already shows its own Photo Library / Take Photo / Choose File menu. Desktop keeps click-to-choose and drag-and-drop.
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
4. Under **Environment**, add `OPENAI_API_KEY` with your OpenAI API key. Do not put the key in source code, GitHub, or a browser-side script.
5. Set **Health Check Path** to `/healthz`, then deploy.

Alternatively create a Render Blueprint using the included `render.yaml`; it declares the same commands and prompts for the API key.

`gunicorn.conf.py` automatically binds to `0.0.0.0:$PORT`, uses one worker with two threads, and allows 240 seconds for requests so the application's 180-second analysis timeout is not cut off by Gunicorn's default. Run the start command from the repository root so this configuration is loaded. Python is pinned in `.python-version`.

### Model and account access

Both analysis and field questions request **`gpt-6.1-sol`**, set in `app.py`. The server calls the OpenAI API directly at `https://api.openai.com/v1`; it does not use a ChatGPT or Hermes session. Your API account must have access to that exact model ID and sufficient API credit. Model access has not been verified with a paid live request. An API rejection is shown as an error; there is no silent model fallback.

### Hosting and cost caveats

Render's Free service can spin down after 15 minutes without inbound traffic, so the first visit afterward can take about a minute to wake it. Free services are intended for hobby/testing use, not production guarantees. OpenAI requests are separate from Render hosting and may incur API charges.

**This app currently has no user authentication or rate limiting. Anyone with the deployed URL can submit requests billed to your server's API key.** Use it as a limited demo only; add authentication, abuse controls, and spending monitoring before promoting it publicly. A private GitHub repository does not make a deployed web service private.

## Privacy and limitations

- Images and selected PDF pages are sent to OpenAI for analysis. Asking about a field sends your question, the field's label, guidance and example, and the hidden form summary (which describes the blank form and is instructed not to copy filled-in information).
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
# Set OPENAI_API_KEY in your shell environment before analysis.
python app.py
```

Visit `http://127.0.0.1:5001`. The development entry point has debug mode disabled. For a production-server smoke test:

```sh
PORT=8000 gunicorn app:app
```

The app also supports a local key file at `~/.config/formfriend/openai-key` with permissions `600`. On Render use `OPENAI_API_KEY` instead. `.env.example` is a reference only; `.env` files are not loaded automatically.

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
- [OpenAI API quickstart](https://developers.openai.com/api/docs/quickstart)
