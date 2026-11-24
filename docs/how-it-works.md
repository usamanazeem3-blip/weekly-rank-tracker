# How it works

This page follows one weekly run from trigger to inbox. The code is in
[tools/rank_tracker.py](../tools/rank_tracker.py), and the examples use the fictional Harbourly project in
[examples/harbourly/](../examples/harbourly/).

```
 Modal cron (weekly)
        │
        ▼
 1. Load configuration (.env / Modal secret)
        │
        ▼
 2. Read the tracker tab ──────────────► Google Sheets API
        │   keywords = rows with a keyword (B) and a volume (C)
        ▼
 3. For each keyword × market (3 in parallel)
        │   fetch Google results page by page ─► Oxylabs Web API
        │   stop when the domain appears or after MAX_RESULTS organic results
        ▼
 4. Compare with the previous column group  →  +3 / -5 / entered / dropped out
        │
        ▼
 5. Write a new column group + ranking-URL notes ─► Google Sheets API
        │
        ▼
 6. Email an HTML table + CSV of the full tracker ─► Gmail API
```

## 1. Configuration

At import time, `rank_tracker.py` reads its settings from environment variables. Locally they come from `.env`
via python-dotenv. On Modal they come from a secret that `push_modal_secret.py` fills from the same `.env`.
Blank values fall back to their defaults, so you can keep a full `.env` with lines left empty.

`MARKETS` becomes an ordered dictionary. Each market code maps to the three things Oxylabs needs: the Google
domain (`co.uk`), the country (`GB`) and the locale (`en_GB`). Common codes have presets, and any other market
can be written inline as `NL=nl:NL:nl_NL`. The order matters, because it is also the column order in the sheet.

## 2. Reading the tracker

The sheet is both the input and the output. It uses a wide layout that people can read without any tooling:

| | A | B | C | D | E | F | G |
|---|---|---|---|---|---|---|---|
| **1** | | | | 2026-01-05 | | 2026-01-12 | |
| **2** | URL | Keywords | Volume | UK | US | UK | US |
| **3** | …/software/ | boat rental software | 1900 | 12 | 18 | 9 | 15 |

- Rows 1–2 are headers. Every later row with both a keyword and a volume is tracked, so you can pause a
  keyword by clearing its volume.
- The next run writes to the first column after the **widest** row. Here that is H:I.
- The previous group is found by scanning row 2 leftwards for the first market's code (`UK`).

## 3. Finding the position

`check_ranking` asks Oxylabs for one results page at a time (`start_page = 1, 2, 3…`) and counts organic
results across pages. Ads, AI Overviews and other SERP features don't count. It stops at the first result whose
host is the target domain or a subdomain of it (`blog.harbourly.example` counts, `notharbourly.example`
doesn't). It also stops after `MAX_RESULTS` organic results, at Google's last visible page, or at `MAX_PAGES`.

Stopping early keeps costs down: a keyword ranking #5 costs one request, and one outside the top 100 costs
about 11–12.

Oxylabs sometimes returns `429` or `5xx` (`faulted` jobs are not billed). Each request is retried up to 8 times
with growing backoff. If a lookup still fails, its cell is set to `ERROR` and the rest of the run carries on.

## 4. Week-over-week change

Each previous cell is parsed leniently. `12` → 12, `-` → not ranked, and hand-typed values such as `64/blog`
→ 64. Blank or unreadable cells mean "no comparison". The change is then:

| Previous | Now | Shown |
|---|---|---|
| 9 | 5 | `+4` (improved) |
| 7 | 12 | `-5` (lost ground) |
| `-` | 32 | `entered` |
| 41 | `-` | `dropped out` |

## 5. Writing the sheet

One `values.update` call writes the whole new group: the date in row 1, the market codes in row 2, and the
positions below. Values use `USER_ENTERED`, so numbers stay numbers. The grid gets wider first if needed.
Each ranking URL is attached as a **cell note**, so hovering over a position shows which page ranked. Comparing
it with column A shows when Google prefers a different page than the one you're targeting.

## 6. The email

The Gmail API sends an HTML table with each keyword's position and change per market. Each position links
to the ranking page. The full tracker (history plus the new group) is attached as a UTF-8 CSV that opens
cleanly in Excel.

## Recovery: `--repair`

If some cells came back `ERROR`, or the run crashed after writing the sheet but before sending the email,
`--repair` reuses the **latest** column group instead of adding a new one. It re-checks only the `ERROR`
cells, keeps every other value and its note, rewrites the group in place and sends the email again.

## Scheduling

[tools/modal_app.py](../tools/modal_app.py) wraps `run()` in a Modal function with a `modal.Cron`
schedule (`SCHEDULE_CRON` in `TIMEZONE`) and a 2-hour timeout. The container image installs only what the job
needs, and adds `rank_tracker.py` as a local source.
