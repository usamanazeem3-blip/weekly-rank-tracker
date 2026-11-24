"""Checks on the repo itself: the templates stay in sync with the code and the scanner works."""
import csv
import re

import pytest
from dotenv import dotenv_values

import scan_secrets
from conftest import CONFIG_KEYS, EXAMPLE, REPO


def test_env_example_documents_every_setting():
    documented = set(dotenv_values(REPO / ".env.example"))
    code = (REPO / "tools" / "rank_tracker.py").read_text() + (REPO / "tools" / "modal_app.py").read_text()
    used = set(re.findall(r'(?:setting|os\.environ\.get|require_env)\("([A-Z_]+)"', code))
    assert used - {"GOOGLE_TOKEN_JSON"} <= documented
    assert set(dotenv_values(EXAMPLE / "example.env")) <= documented
    assert documented <= set(CONFIG_KEYS)


def test_blank_template_matches_tracker_layout():
    with open(REPO / "templates" / "tracker_template.csv", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[1] == ["URL", "Keywords", "Volume"]
    assert all(len(r) == 3 and r[1] and r[2] for r in rows[2:])


def test_repo_scan_is_clean(monkeypatch):
    monkeypatch.setattr(scan_secrets, "load_denylist", lambda extra: [])
    assert scan_secrets.scan([]) == []


@pytest.mark.parametrize("line,label", [
    ("REPORT_EMAIL_TO=sam.lee@realcompany.test", "email address"),  # scan:allow (planted test value)
    ("OXYLABS_API_KEY=Zq81vYt0LmP3kR7wXa9c", "hard-coded secret"),  # scan:allow (planted test value)
    ('"client_secret": "GOCSPX-abcdefghijklmnop"', "Google OAuth client secret"),  # scan:allow (planted test value)
    ("https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcdEF/edit", "Google Drive/Sheet/Doc ID"),  # scan:allow (planted test value)
    ("open C:\\Users\\sam\\Desktop\\file.txt", "local file path"),  # scan:allow (planted test value)
    ('"refresh_token": "1//0gAbCdEfGhIjKlMnOpQrStUv"', "Google refresh token"),  # scan:allow (planted test value)
])
def test_scanner_flags_planted_secrets(tmp_path, monkeypatch, line, label):
    (tmp_path / "leak.txt").write_text(line + "\n")
    monkeypatch.setattr(scan_secrets, "ROOT", tmp_path)
    assert label in {f[2] for f in scan_secrets.scan([])}


def test_scanner_allows_example_domains_and_denylist(tmp_path, monkeypatch):
    (tmp_path / "ok.txt").write_text("jonas.okafor@harbourly.example\nhttps://www.harbourly.example/\nAcme Ltd\n")
    monkeypatch.setattr(scan_secrets, "ROOT", tmp_path)
    assert scan_secrets.scan([]) == []
    assert [f[3] for f in scan_secrets.scan(scan_secrets.load_denylist(["acme"]))] == ["Acme"]


def test_scanner_flags_private_files(tmp_path, monkeypatch):
    (tmp_path / "token.json").write_text("{}")
    monkeypatch.setattr(scan_secrets, "ROOT", tmp_path)
    assert scan_secrets.scan([])[0][2] == "private file present in repo folder"
