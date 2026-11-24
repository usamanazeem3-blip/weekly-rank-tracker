"""Shared fixtures. Every test runs against the fictional Harbourly project in examples/harbourly/;
Oxylabs, Google Sheets and Gmail are replaced by in-memory fakes, so no network or credentials
are needed."""
import base64
import csv
import email
import importlib.util
import sys
from pathlib import Path

import pytest
from dotenv import dotenv_values

REPO = Path(__file__).resolve().parent.parent
EXAMPLE = REPO / "examples" / "harbourly"
CONFIG_KEYS = ["TARGET_DOMAIN", "OXYLABS_API_KEY", "GOOGLE_SHEET_ID", "REPORT_EMAIL_TO", "MARKETS",
               "TIMEZONE", "SCHEDULE_CRON", "DATE_FORMAT", "REPORT_SUBJECT", "TRACKER_TAB", "MAX_RESULTS",
               "MAX_PAGES", "MAX_WORKERS", "MODAL_APP_NAME", "MODAL_SECRET_NAME", "SAVE_RAW",
               "GOOGLE_TOKEN_JSON"]

sys.path.insert(0, str(REPO / "tools"))


@pytest.fixture
def load_tracker(monkeypatch):
    """Import a fresh tools/rank_tracker.py configured from the example .env plus overrides.

    The repo's own .env (if you have one) is never loaded, so tests can't pick up real settings."""
    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)

    def _load(**overrides):
        for key in CONFIG_KEYS:
            monkeypatch.delenv(key, raising=False)
        for key, value in {**dotenv_values(EXAMPLE / "example.env"), **overrides}.items():
            if value is not None:
                monkeypatch.setenv(key, value)
        spec = importlib.util.spec_from_file_location("rank_tracker_under_test", REPO / "tools" / "rank_tracker.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return _load


@pytest.fixture
def tracker(load_tracker):
    return load_tracker()


def serp(urls, last_page=10):
    """A minimal Oxylabs response with these organic result URLs (plus an ad that must be ignored)."""
    return {"state": "done", "results": [{"json": {"last_visible_page": last_page, "results": {
        "paid": [{"url": "https://www.harbourly.example/ad-landing/"}],
        "organic": [{"pos": i + 1, "url": u} for i, u in enumerate(urls)]}}}]}


def competitors(n, start=0):
    return [f"https://www.competitor{start + i}.example/" for i in range(n)]


@pytest.fixture
def example_rows():
    with open(EXAMPLE / "tracker_example.csv", newline="", encoding="utf-8") as f:
        return [row for row in csv.reader(f)]


class Exec:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class FakeGoogle:
    """In-memory stand-in for the Sheets and Gmail clients that records every write."""

    def __init__(self, rows, col_count=None, notes=None, tab="Tracker"):
        self.rows = rows
        self.col_count = col_count or max(len(r) for r in rows)
        self.notes, self.tab = notes or [], tab
        self.writes, self.sent = [], []

    def spreadsheets(self): return self
    def values(self): return self
    def sheets(self): return self
    def users(self): return self
    def messages(self): return self

    def get(self, spreadsheetId=None, range=None, ranges=None, fields=None):
        if range is not None:
            return Exec({"values": self.rows})
        if ranges:
            return Exec({"sheets": [{"data": [{"rowData": self.notes}]}]})
        return Exec({"sheets": [{"properties": {"title": self.tab, "sheetId": 7,
                                                "gridProperties": {"columnCount": self.col_count}}}]})

    def update(self, **kw):
        self.writes.append(("values.update", kw))
        return Exec({})

    def batchUpdate(self, **kw):
        self.writes.append(("batchUpdate", kw))
        return Exec({})

    def send(self, userId, body):
        msg = email.message_from_bytes(base64.urlsafe_b64decode(body["raw"]))
        parts = [p for p in msg.walk() if not p.is_multipart()]
        self.sent.append({
            "to": msg["to"], "subject": msg["subject"],
            "html": parts[0].get_payload(decode=True).decode(),
            "attachment": (parts[1].get_filename(), parts[1].get_payload(decode=True)) if len(parts) > 1 else None,
        })
        return Exec({})

    def value_update(self):
        return next(kw for name, kw in self.writes if name == "values.update")

    def notes_written(self):
        return [req["updateCells"] for name, kw in self.writes if name == "batchUpdate"
                for req in kw["body"]["requests"] if "updateCells" in req]


@pytest.fixture
def wire(monkeypatch):
    """wire(module, rows, serps) -> FakeGoogle. serps maps (keyword, market) -> list of pages."""

    def _wire(module, rows, serps, **fake_kwargs):
        fake = FakeGoogle(rows, **fake_kwargs)
        monkeypatch.setattr(module, "build", lambda *a, credentials=None: fake)
        monkeypatch.setattr(module, "google_creds", lambda: object())
        calls = []

        def fetch(keyword, market, page):
            calls.append((keyword, market, page))
            pages = serps.get((keyword, market))
            if pages is None:
                raise RuntimeError("Oxylabs HTTP 500: simulated failure")
            return pages[page - 1] if page <= len(pages) else serp([])

        monkeypatch.setattr(module, "fetch_serp_page", fetch)
        fake.fetch_calls = calls
        return fake

    return _wire
