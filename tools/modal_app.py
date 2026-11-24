"""Modal deployment: runs the rank tracker on a weekly cron (default Monday 08:00, TIMEZONE).

    modal deploy tools/modal_app.py   # deploy / update the schedule
    modal run tools/modal_app.py      # trigger one run in the cloud now

App name, secret name and schedule come from .env (MODAL_APP_NAME, MODAL_SECRET_NAME,
SCHEDULE_CRON, TIMEZONE). push_modal_secret.py copies the same values into the secret, so the
deploying machine and the container agree.
"""
import os
from pathlib import Path

import modal

try:  # python-dotenv is only needed locally; on Modal the env comes from the Secret
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

APP_NAME = os.environ.get("MODAL_APP_NAME") or "weekly-rank-tracker"
SECRET_NAME = os.environ.get("MODAL_SECRET_NAME") or APP_NAME

app = modal.App(APP_NAME)

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("requests", "google-api-python-client", "google-auth")
    .add_local_python_source("rank_tracker")
)


@app.function(
    image=image,
    secrets=[modal.Secret.from_name(SECRET_NAME)],
    schedule=modal.Cron(os.environ.get("SCHEDULE_CRON") or "0 8 * * 1",
                        timezone=os.environ.get("TIMEZONE") or "UTC"),
    timeout=7200,  # dozens of searches x up to 12 pages, 3 in parallel, with retry backoff
)
def weekly_rank_check():
    import rank_tracker

    rank_tracker.run()


@app.local_entrypoint()
def main():
    weekly_rank_check.remote()
