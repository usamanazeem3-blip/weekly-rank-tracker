# Weekly Rank Tracker

**A scheduled Google rank tracker for SEOs.** Once a week it checks where your website ranks for every keyword
in a Google Sheet, in each country you care about. It writes the positions into the sheet next to last week's,
and emails a report showing which keywords improved, which slipped, and which entered or dropped out of the top 100.

No more opening a location-spoofing search tool every Monday and copying positions by hand. The check runs
in the cloud on a timer, and you get time back for technical SEO work.

```
 Keywords in a Google Sheet ─► Oxylabs Google SERP API ─► new dated column in the sheet ─► email report
                     (runs weekly on Modal, no server to maintain)
```

## Key features

- **The sheet is the control panel.** Add a row to track a keyword and clear its volume to pause it.
  No code changes are needed.
- **Several markets.** Track any mix of countries (`UK,US,CA`, or custom ones like `NL=nl:NL:nl_NL`), each
  with the right Google domain, location and locale. You get one column per market per week.
- **True organic position.** Results are counted across pages, and ads, AI Overviews and other SERP features
  are ignored. Subdomains count as your site.
- **Week-over-week change.** The email shows `+4`, `-5`, `entered` or `dropped out` for each keyword and
  market. Each position links to the page that ranked.
- **Ranking URL in every cell.** Hover over a position in the sheet to see which page ranked, so you can catch
  the wrong page ranking.
- **Cheap by design.** Pages are fetched one at a time and the search stops as soon as your site is found.
- **Robust.** Failed lookups are retried with backoff. One failure marks a single cell `ERROR` and doesn't
  sink the run, and `--repair` fixes those cells in place without re-scraping the rest.
- **Shareable safely.** A built-in scanner checks the repo for keys, IDs, emails and local paths.

## Tech used

| | |
|---|---|
| Language | Python 3.11+ |
| SERP data | [Oxylabs Web API](https://developers.oxylabs.io/products/web-api) (Google search, parsed JSON) |
| Storage / UI | Google Sheets API (OAuth) |
| Report | Gmail API (OAuth, send-only scope) |
| Scheduling | [Modal](https://modal.com) cron function |
| Tests | pytest, with in-memory fakes for every external service |

## Repo layout

```
.
├── tools/
│   ├── rank_tracker.py        # the job: read sheet → Oxylabs → write sheet → email
│   ├── modal_app.py           # weekly cron on Modal
│   ├── push_modal_secret.py   # copies .env + token.json into the Modal secret
│   ├── google_auth.py         # one-time browser sign-in, writes token.json
│   ├── import_tracker.py      # copy an existing tracker tab in from another spreadsheet
│   └── scan_secrets.py        # pre-share check for secrets, IDs, emails and paths
├── workflows/
│   └── weekly_rank_tracking.md  # operating guide: setup, re-auth, edge cases, learnings
├── docs/
│   └── how-it-works.md        # step-by-step walkthrough of one run
├── examples/harbourly/       # fictional example project (config, tracker, Oxylabs response)
├── templates/
│   └── tracker_template.csv   # blank tracker to import into Google Sheets
├── tests/                     # public test suite (fictional data only)
├── .env.example               # every setting, documented
├── CLAUDE.md                  # instructions for running the project with an AI agent
├── requirements.txt
└── requirements-dev.txt
```

## Setup

You'll need an Oxylabs Web API account, a Google account, and a free Modal account if you want the weekly cloud schedule.

1. **Install**
   ```bash
   python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. **Create the tracker sheet.** In Google Sheets, use *File → Import* to load
   [templates/tracker_template.csv](templates/tracker_template.csv), rename the tab to `Tracker`, and replace
   the sample rows with your pages, keywords and search volumes. To see what it looks like after a few weeks,
   open [examples/harbourly/tracker_example.csv](examples/harbourly/tracker_example.csv).
3. **Google credentials.** In Google Cloud Console, create a project and enable the **Google Sheets API** and
   **Gmail API**. Configure the OAuth consent screen (add yourself as a test user), then create an OAuth client
   of type **Desktop app**. Download it as `credentials.json` into the repo root and run:
   ```bash
   python tools/google_auth.py        # opens a browser, writes token.json
   ```
4. **Configure.** Copy `.env.example` to `.env` and fill in `TARGET_DOMAIN`, `OXYLABS_API_KEY`,
   `GOOGLE_SHEET_ID` (from the sheet URL), `REPORT_EMAIL_TO` and `MARKETS`.
5. **Check, then try it.**
   ```bash
   python tools/rank_tracker.py --list-keywords    # free: shows what will be tracked
   python tools/rank_tracker.py --no-email         # real run (uses Oxylabs credits), sheet only
   python tools/rank_tracker.py                    # full run with the email
   ```
6. **Schedule it on Modal.**
   ```bash
   pip install modal && modal setup
   python tools/push_modal_secret.py              # uploads .env + token.json as a Modal secret
   python -m modal deploy tools/modal_app.py      # weekly cron from SCHEDULE_CRON / TIMEZONE
   ```

> While your Google OAuth app is in *Testing* mode, Google expires the token after 7 days. Either publish the
> consent screen, or re-run `google_auth.py` and `push_modal_secret.py` before each weekly run. Details are in
> [workflows/weekly_rank_tracking.md](workflows/weekly_rank_tracking.md#weekly-re-auth-only-while-the-oauth-app-is-in-testing).

## Changing it

| To change… | Do this |
|---|---|
| Keywords | Edit the sheet. A row needs a keyword (column B) and a volume (column C). |
| Site | `TARGET_DOMAIN` in `.env` |
| Countries | `MARKETS`, e.g. `UK,US,AU` or `US,NL=nl:NL:nl_NL`. Keep existing markets in the same order and add new ones at the end. |
| Day and time | `SCHEDULE_CRON` and `TIMEZONE`, then redeploy `modal_app.py` |
| Depth or cost | `MAX_RESULTS` (default 100), `MAX_PAGES` (default 15) and `MAX_WORKERS` (default 3) |
| Date header and email subject | `DATE_FORMAT` (e.g. `%d/%m/%Y`) and `REPORT_SUBJECT` (`{domain}` and `{date}` are filled in) |
| Recipients | `REPORT_EMAIL_TO` (comma-separated) |

After editing `.env`, run `python tools/push_modal_secret.py` so the cloud job picks it up. Code, schedule and
app-name changes also need `python -m modal deploy tools/modal_app.py`.

Useful flags: `--markets US` checks one market, `--no-sheet` and `--no-email` skip those steps, and `--repair`
re-checks `ERROR` cells in the latest week and re-sends the email.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The suite runs entirely offline against the fictional Harbourly project. It covers configuration parsing,
position counting across pages, sheet layout, week-over-week changes, the email and CSV, error handling,
`--repair` and multi-market runs.

## Before sharing a copy

1. Run `python tools/scan_secrets.py`. It should print `Clean`. To also catch names specific to your setup
   (company, client or people), list them one per line in `.scan-denylist`. That file is gitignored, so the
   names stay private.
2. Make sure `.env`, `credentials.json`, `token.json` and `.tmp/` are not in the folder you share. They're
   gitignored, but a zip of the folder would still include them.
3. Check your tracker exports and email CSVs (`*_rank_tracker_*.csv`) aren't lying around. They contain real
   keyword and ranking data.
4. Run `python -m pytest` to confirm the public tests pass.

## More

- [docs/how-it-works.md](docs/how-it-works.md): what happens at each step of a run
- [workflows/weekly_rank_tracking.md](workflows/weekly_rank_tracking.md): operating guide, edge cases and lessons learned

## Licence

Released under the [MIT License](LICENSE). You're free to use, change and share it, as long as you keep the copyright notice.

The third-party services it calls (Oxylabs, Google Sheets, Gmail, Modal) have their own terms of use. The Python packages it installs keep their own licences.
