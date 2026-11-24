"""Weekly Google rank tracker: Oxylabs SERP -> wide-format Google Sheet tracker -> Gmail report.

The keyword list lives in the sheet itself: every row of the tracker tab with a keyword in
column B and a volume in column C is tracked (column A is the target page URL). Each run appends
a new date column group (one column per market, e.g. UK | US) to the right of the existing data,
writes positions ("-" = not in top 100) and puts the ranking URL in each cell's note.

Everything site-specific (domain, markets, timezone, date format, email subject) is configured
through environment variables; see .env.example and the README.

Usage (local):
    python tools/rank_tracker.py                  # full run: scrape, write sheet, send email
    python tools/rank_tracker.py --no-email       # skip the email
    python tools/rank_tracker.py --no-sheet       # skip writing the sheet (still reads keywords)
    python tools/rank_tracker.py --markets US     # only one market (e.g. rerun a failed one)
    python tools/rank_tracker.py --list-keywords  # show what would be tracked, no scraping

On Modal, tools/modal_app.py calls run() on a schedule.
"""
import argparse
import base64
import csv
import io
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

ROOT = Path(__file__).resolve().parent.parent

try:  # python-dotenv is only needed locally; on Modal the env comes from a Secret
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

# ---------------------------------------------------------------- Configuration

def setting(name, default):
    """Environment value, or `default` when unset or left blank in .env."""
    return os.environ.get(name, "").strip() or default


# Google domain, Oxylabs location (2-letter country) and locale for common market codes.
# Any other market can be given inline as CODE=domain:location:locale (see parse_markets).
MARKET_PRESETS = {
    "US": ("com", "US", "en_US"),
    "UK": ("co.uk", "GB", "en_GB"),
    "CA": ("ca", "CA", "en_CA"),
    "AU": ("com.au", "AU", "en_AU"),
    "NZ": ("co.nz", "NZ", "en_NZ"),
    "IE": ("ie", "IE", "en_IE"),
    "IN": ("co.in", "IN", "en_IN"),
    "DE": ("de", "DE", "de_DE"),
    "FR": ("fr", "FR", "fr_FR"),
    "ES": ("es", "ES", "es_ES"),
}


def parse_markets(spec):
    """'UK,US' or 'US,DE=de:DE:de_DE' -> {code: {domain, location, locale}}, in sheet column order."""
    markets = {}
    for item in filter(None, (part.strip() for part in spec.split(","))):
        code, _, custom = item.partition("=")
        code = code.strip().upper()
        if custom:
            parts = [p.strip() for p in custom.split(":")]
            if len(parts) != 3 or not all(parts):
                raise ValueError(f"Market '{item}' must look like CODE=google_domain:country:locale")
            domain, location, locale = parts
        elif code in MARKET_PRESETS:
            domain, location, locale = MARKET_PRESETS[code]
        else:
            raise ValueError(f"Unknown market '{code}'. Use one of {sorted(MARKET_PRESETS)} "
                             "or define it as CODE=google_domain:country:locale")
        markets[code] = {"domain": domain, "location": location, "locale": locale}
    if not markets:
        raise ValueError("MARKETS is empty")
    return markets


# The site whose rankings are tracked; subdomains count too (blog.example.com for example.com)
TARGET_DOMAIN = setting("TARGET_DOMAIN", "").lower().removeprefix("www.")
# Order matches the sheet's column groups, e.g. "UK,US" -> UK first, then US
MARKETS = parse_markets(setting("MARKETS", "US"))
# Google returns ~8-10 organic results per page, so reaching the top 100 takes ~11-12 pages.
# Pages are fetched one at a time and we stop as soon as the domain is found; MAX_PAGES is
# a hard ceiling on Oxylabs requests per keyword/market.
MAX_RESULTS = int(setting("MAX_RESULTS", "100"))
MAX_PAGES = int(setting("MAX_PAGES", "15"))
# 3 at a time: 6 parallel searches triggered Oxylabs faults on US queries
MAX_WORKERS = int(setting("MAX_WORKERS", "3"))
NOT_RANKED = "-"
TZ = ZoneInfo(setting("TIMEZONE", "UTC"))
DATE_FORMAT = setting("DATE_FORMAT", "%Y-%m-%d")  # row-1 header of each new column group
REPORT_SUBJECT = setting("REPORT_SUBJECT", "Google rankings for {domain} - {date}")

OXYLABS_URL = "https://webapi.oxylabs.io/v1/scrape/google/search"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
]
TRACKER_TAB = setting("TRACKER_TAB", "Tracker")
HEADER_ROWS = 2  # row 1: dates, row 2: URL | Keywords | Volume | <market codes> ...
KEYWORD_COL, VOLUME_COL = 1, 2  # B = keyword, C = volume (A holds the target page URL)


def require_env(name):
    value = os.environ.get(name)
    if not value:
        sys.exit(f"Missing required environment variable: {name}")
    return value


def require_target():
    if not TARGET_DOMAIN:
        sys.exit("Missing required environment variable: TARGET_DOMAIN")
    return TARGET_DOMAIN


# ---------------------------------------------------------------- Oxylabs

def fetch_serp_page(keyword, market, page):
    """Fetch one parsed Google results page from Oxylabs, retrying transient failures."""
    m = MARKETS[market]
    payload = {
        "query": keyword,
        "domain": m["domain"],
        "location": m["location"],
        "locale": m["locale"],
        "device": "desktop",
        "start_page": page,
        "pages": 1,
        "output": ["json"],
    }
    headers = {"Authorization": f"Bearer {require_env('OXYLABS_API_KEY')}"}
    # 500 REQUEST_FAILED_AFTER_TOO_MANY_RETRIES ("faulted") is common for US and low-volume
    # queries and is not billed, so retry generously with growing backoff.
    for attempt in range(8):
        resp = requests.post(OXYLABS_URL, headers=headers, json=payload, timeout=180)
        if resp.status_code == 429 or resp.status_code >= 500:
            time.sleep(min(15 * (attempt + 1), 90))
            continue
        break
    if not resp.ok:
        raise RuntimeError(f"Oxylabs HTTP {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    # Envelope: {"state": "done", "results": [{"json": {"results": {"organic": [...]}}}], "params", "metadata"}
    state = data.get("state", data.get("status")) if isinstance(data, dict) else None
    if state not in (None, "done", 200):
        raise RuntimeError(f"Oxylabs state {state!r} (request_id {data.get('metadata', {}).get('request_id')})")
    if os.environ.get("SAVE_RAW") == "1":
        out = ROOT / ".tmp" / f"serp_{market}_{keyword.replace(' ', '_')}_p{page}.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def find_organic(data):
    """Return the list of organic results wherever it sits in the response."""
    if isinstance(data, dict):
        for key in ("organic", "organic_results"):
            if isinstance(data.get(key), list):
                return data[key]
        children = data.values()
    elif isinstance(data, list):
        children = data
    else:
        return None
    for child in children:
        found = find_organic(child)
        if found is not None:
            return found
    return None


def is_target(url):
    host = urlparse(url or "").netloc.lower().split(":")[0]
    return host == TARGET_DOMAIN or host.endswith("." + TARGET_DOMAIN)


def check_ranking(keyword, market):
    """Return {position, url} for TARGET_DOMAIN's first organic result, position None if not found."""
    seen = 0
    for page in range(1, MAX_PAGES + 1):
        data = fetch_serp_page(keyword, market, page)
        organic = find_organic(data)
        if organic is None:
            keys = list(data.keys()) if isinstance(data, dict) else type(data).__name__
            raise RuntimeError(f"No organic results in Oxylabs response (top-level keys: {keys})")
        for result in organic:
            seen += 1
            if seen > MAX_RESULTS:
                return {"position": None, "url": ""}
            url = result.get("url") or result.get("link")
            if is_target(url):
                return {"position": seen, "url": url}
        try:
            last_page = int(data["results"][0]["json"]["last_visible_page"])
        except (KeyError, IndexError, TypeError, ValueError):
            last_page = None
        if not organic or seen >= MAX_RESULTS or (last_page and page >= last_page):
            break
    return {"position": None, "url": ""}


# ---------------------------------------------------------------- Sheet (wide tracker)

def google_creds():
    raw = os.environ.get("GOOGLE_TOKEN_JSON")
    info = json.loads(raw) if raw else json.loads((ROOT / "token.json").read_text())
    creds = Credentials.from_authorized_user_info(info, SCOPES)
    if not creds.valid:
        creds.refresh(Request())
    return creds


def col_letter(index):
    """0-based column index -> A1 letters (0 -> A, 26 -> AA)."""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def cell(rows, r, c):
    return rows[r][c].strip() if r < len(rows) and c < len(rows[r]) else ""


def read_tracker(sheets, sheet_id):
    """Return (rows, tab_sheet_id, column_count) for the tracker tab."""
    meta = sheets.spreadsheets().get(spreadsheetId=sheet_id).execute()
    tab = next((s["properties"] for s in meta["sheets"] if s["properties"]["title"] == TRACKER_TAB), None)
    if tab is None:
        sys.exit(f"Tab '{TRACKER_TAB}' not found in sheet {sheet_id}")
    rows = sheets.spreadsheets().values().get(
        spreadsheetId=sheet_id, range=f"'{TRACKER_TAB}'"
    ).execute().get("values", [])
    return rows, tab["sheetId"], tab["gridProperties"]["columnCount"]


def keyword_rows(rows):
    """[(row_index, keyword)] for every row with both a keyword and a volume."""
    found = []
    for r in range(HEADER_ROWS, len(rows)):
        kw, volume = cell(rows, r, KEYWORD_COL), cell(rows, r, VOLUME_COL)
        if kw and volume:
            found.append((r, " ".join(kw.split())))
    return found


def previous_group_col(rows, before):
    """Column index of the most recent group header (first market code) left of `before`, or None."""
    first = next(iter(MARKETS))
    for c in range(before - 1, VOLUME_COL, -1):
        if cell(rows, 1, c).upper() == first:
            return c
    return None


def read_notes(sheets, sheet_id, col, nrows):
    """{(row_index, market_index): note} for the column group starting at `col`."""
    rng = f"'{TRACKER_TAB}'!{col_letter(col)}1:{col_letter(col + len(MARKETS) - 1)}{nrows}"
    data = sheets.spreadsheets().get(
        spreadsheetId=sheet_id, ranges=[rng], fields="sheets(data(rowData(values(note))))"
    ).execute()
    notes = {}
    for r, row_data in enumerate(data["sheets"][0]["data"][0].get("rowData", [])):
        for c, value in enumerate(row_data.get("values", [])):
            if value.get("note"):
                notes[(r, c)] = value["note"]
    return notes


def parse_position(value):
    """Sheet cell -> int, None (not ranked) or 'unknown' (blank / unparseable)."""
    value = (value or "").strip()
    if value == NOT_RANKED:
        return None
    m = re.match(r"(\d+)", value)  # hand-typed history may hold entries like "37/blog" or "9, O"
    return int(m.group(1)) if m else "unknown"


def describe_change(prev, current):
    if prev == "unknown":
        return ""
    if current is None:
        return "dropped out" if prev is not None else ""
    if prev is None:
        return "entered"
    diff = prev - current
    return f"+{diff}" if diff > 0 else str(diff)


def write_tracker(sheets, sheet_id, tab_id, col_count, rows, new_col, date_text, results):
    """Fill the new market column group and attach ranking URLs as cell notes."""
    width = len(MARKETS)
    requests_ = []
    if new_col + width > col_count:
        requests_.append({"appendDimension": {"sheetId": tab_id, "dimension": "COLUMNS",
                                              "length": new_col + width - col_count}})
    grid = ([[date_text] + [""] * (width - 1), list(MARKETS)]
            + [[""] * width for _ in range(HEADER_ROWS, len(rows))])
    for r in results.values():
        grid[r["row"]][list(MARKETS).index(r["market"])] = r["cell"]
    for r in results.values():
        if r["url"]:
            requests_.append({"updateCells": {
                "range": {"sheetId": tab_id, "startRowIndex": r["row"], "endRowIndex": r["row"] + 1,
                          "startColumnIndex": new_col + list(MARKETS).index(r["market"]),
                          "endColumnIndex": new_col + list(MARKETS).index(r["market"]) + 1},
                "rows": [{"values": [{"note": r["url"]}]}],
                "fields": "note",
            }})
    if requests_ and requests_[0].get("appendDimension"):
        sheets.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": requests_[:1]}).execute()
        requests_ = requests_[1:]
    rng = f"'{TRACKER_TAB}'!{col_letter(new_col)}1:{col_letter(new_col + width - 1)}{len(grid)}"
    sheets.spreadsheets().values().update(
        spreadsheetId=sheet_id, range=rng, valueInputOption="USER_ENTERED", body={"values": grid}
    ).execute()
    if requests_:
        sheets.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": requests_}).execute()
    return grid


# ---------------------------------------------------------------- Email

def tracker_csv(rows, new_col, grid):
    width = max(new_col + len(MARKETS), max(len(r) for r in rows))
    merged = []
    for i in range(max(len(rows), len(grid))):
        row = list(rows[i]) if i < len(rows) else []
        row += [""] * (width - len(row))
        if i < len(grid):
            row[new_col:new_col + len(MARKETS)] = grid[i]
        merged.append(row)
    buf = io.StringIO()
    csv.writer(buf).writerows(merged)
    return buf.getvalue().encode("utf-8-sig")  # BOM so Excel reads UTF-8 correctly


def csv_filename(day):
    """e.g. example_rank_tracker_2026-01-05.csv for TARGET_DOMAIN example.com"""
    return f"{TARGET_DOMAIN.split('.')[0]}_rank_tracker_{day.strftime('%Y-%m-%d')}.csv"


def send_email(creds, to, subject, html, attachment=None):
    """attachment: optional (filename, bytes) tuple."""
    msg = MIMEMultipart()
    msg.attach(MIMEText(html, "html"))
    if attachment:
        name, data = attachment
        part = MIMEApplication(data, Name=name)
        part["Content-Disposition"] = f'attachment; filename="{name}"'
        msg.attach(part)
    msg["to"] = to
    msg["subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    build("gmail", "v1", credentials=creds).users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()


def build_email(keywords, results, markets, date_label, sheet_id):
    head = "".join(f"<th>{m}</th><th>{m} change</th>" for m in markets)
    body = ""
    for row, kw in keywords:
        cells = ""
        for m in markets:
            r = results.get((row, m))
            label = escape(str(r["cell"])) if r else ""  # cell is an int position or "-"/"ERROR"
            if r and r["url"]:
                label = f"<a href='{escape(r['url'])}'>{label}</a>"
            title = f" title='{escape(r['error'])}'" if r and r.get("error") else ""
            cells += f"<td style='text-align:center'{title}><b>{label}</b></td><td style='text-align:center'>{r['change'] if r else ''}</td>"
        body += f"<tr><td>{escape(kw)}</td>{cells}</tr>"
    link = f"https://docs.google.com/spreadsheets/d/{sheet_id}" if sheet_id else ""
    return (
        f"<p>Google rankings for <b>{TARGET_DOMAIN}</b>, {date_label}. "
        f"&quot;{NOT_RANKED}&quot; = not in the top {MAX_RESULTS}. Positions link to the ranking page.</p>"
        "<table border='1' cellpadding='5' cellspacing='0' style='border-collapse:collapse;font-size:13px'>"
        f"<tr><th>Keyword</th>{head}</tr>{body}</table>"
        + (f"<p><a href='{link}'>Open the tracker in Google Sheets</a> (full history also attached as CSV)</p>" if link else "")
    )


# ---------------------------------------------------------------- Run

def run(write_sheet=True, email=True, markets=None, repair=False):
    """repair=True: instead of adding a new column group, re-check only the ERROR cells in the
    latest group, rewrite that group in place and (re)send the email from it."""
    require_target()
    markets = list(MARKETS) if repair else (markets or list(MARKETS))
    now = datetime.now(TZ)
    sheet_id = require_env("GOOGLE_SHEET_ID")
    creds = google_creds()
    sheets = build("sheets", "v4", credentials=creds)

    rows, tab_id, col_count = read_tracker(sheets, sheet_id)
    keywords = keyword_rows(rows)
    if repair:
        target_col = previous_group_col(rows, max(len(r) for r in rows))
        date_text = cell(rows, 0, target_col)
        existing_notes = read_notes(sheets, sheet_id, target_col, len(rows))
        print(f"Repairing column group {col_letter(target_col)} ({date_text})")
    else:
        target_col = max(len(r) for r in rows)
        date_text = now.strftime(DATE_FORMAT)
        existing_notes = None
        print(f"Tracking {len(keywords)} keywords x {len(markets)} markets; new column {col_letter(target_col)}")
    prev_col = previous_group_col(rows, target_col)
    try:
        date_label = datetime.strptime(date_text, DATE_FORMAT).strftime("%d %b %Y")
    except ValueError:
        date_label = date_text

    def lookup(job):
        row, kw, market = job
        idx = list(MARKETS).index(market)
        entry = {"row": row, "keyword": kw, "market": market, "url": ""}
        prev = parse_position(cell(rows, row, prev_col + idx)) if prev_col else "unknown"
        if existing_notes is not None:
            current = cell(rows, row, target_col + idx)
            if current != "ERROR":  # keep what's already in the sheet
                pos = parse_position(current)
                pos = pos if isinstance(pos, int) else None
                entry.update(position=pos, cell=current or NOT_RANKED,
                             url=existing_notes.get((row, idx), ""), change=describe_change(prev, pos))
                return entry
        try:
            entry.update(check_ranking(kw.lower(), market))
            pos = entry["position"]
            entry["cell"] = pos if pos else NOT_RANKED
            entry["change"] = describe_change(prev, pos)
        except Exception as exc:  # one failed lookup shouldn't sink the whole report
            entry.update(position=None, cell="ERROR", change="", error=str(exc)[:300])
        return entry

    jobs = [(row, kw, m) for row, kw in keywords for m in markets]
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = {(e["row"], e["market"]): e for e in pool.map(lookup, jobs)}
    for e in results.values():
        print(f"{e['market']:2} | {e['keyword']:42} | {str(e['cell']):>5} | {e['change']:>11} | {e['url'] or e.get('error', '')}")

    grid = None
    if write_sheet:
        grid = write_tracker(sheets, sheet_id, tab_id, col_count, rows, target_col, date_text, results)

    if email:
        attachment = None
        if grid:
            attachment = (csv_filename(now), tracker_csv(rows, target_col, grid))
        send_email(creds, require_env("REPORT_EMAIL_TO"),
                   REPORT_SUBJECT.format(domain=TARGET_DOMAIN, date=date_label),
                   build_email(keywords, results, markets, date_label, sheet_id), attachment)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-sheet", action="store_true", help="don't write to Google Sheets")
    parser.add_argument("--no-email", action="store_true", help="don't send the email report")
    parser.add_argument("--markets", nargs="+", choices=list(MARKETS), help="only check these markets")
    parser.add_argument("--list-keywords", action="store_true", help="print tracked keywords and exit")
    parser.add_argument("--repair", action="store_true",
                        help="re-check ERROR cells in the latest column group in place, then send the email")
    args = parser.parse_args()

    if args.list_keywords:
        sheets = build("sheets", "v4", credentials=google_creds())
        rows, _, _ = read_tracker(sheets, require_env("GOOGLE_SHEET_ID"))
        kws = keyword_rows(rows)
        new_col = max(len(r) for r in rows)
        for row, kw in kws:
            print(f"row {row + 1:3}: {kw}")
        print(f"{len(kws)} keywords; next run writes columns "
              f"{col_letter(new_col)}:{col_letter(new_col + len(MARKETS) - 1)}")
        return
    run(write_sheet=not args.no_sheet, email=not args.no_email, markets=args.markets, repair=args.repair)


if __name__ == "__main__":
    main()
