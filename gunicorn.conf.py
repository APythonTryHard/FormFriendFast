"""Loaded automatically by `gunicorn app:app` from the repository root."""
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
# Small footprint for a free instance; threaded worker keeps health checks
# responsive while another request waits for the model. PDFium has its own lock.
workers = 1
worker_class = "gthread"
threads = 2
# Must exceed the application's 180-second model timeout plus conversion time.
timeout = 240
graceful_timeout = 30
accesslog = "-"
errorlog = "-"
capture_output = True
