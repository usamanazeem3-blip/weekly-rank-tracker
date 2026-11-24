"""Copy a tracker tab from another spreadsheet into GOOGLE_SHEET_ID as the 'Tracker' tab.

Keeps formatting, notes and colours (uses the Sheets copyTo API). The source spreadsheet
must be shared with the Google account in token.json.

    python tools/import_tracker.py <source_spreadsheet_id_or_url> --tab "Rankings" [--keep-rows 40]

--keep-rows N deletes every row after N in the copy (the source is never modified).
"""
import argparse
import re
import sys

from googleapiclient.discovery import build

from rank_tracker import TRACKER_TAB, google_creds, require_env


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", help="source spreadsheet ID or URL")
    parser.add_argument("--tab", help="source tab name (default: first tab)")
    parser.add_argument("--keep-rows", type=int, help="delete rows after this one in the copy")
    args = parser.parse_args()

    m = re.search(r"/d/([a-zA-Z0-9-_]+)", args.source)
    source_id = m.group(1) if m else args.source
    target_id = require_env("GOOGLE_SHEET_ID")
    sheets = build("sheets", "v4", credentials=google_creds())

    src_tabs = sheets.spreadsheets().get(spreadsheetId=source_id).execute()["sheets"]
    names = [s["properties"]["title"] for s in src_tabs]
    tab_name = args.tab or names[0]
    if tab_name not in names:
        sys.exit(f"Tab '{tab_name}' not found. Available: {names}")
    src_tab_id = next(s["properties"]["sheetId"] for s in src_tabs if s["properties"]["title"] == tab_name)

    target_tabs = [s["properties"]["title"] for s in
                   sheets.spreadsheets().get(spreadsheetId=target_id).execute()["sheets"]]
    if TRACKER_TAB in target_tabs:
        sys.exit(f"Target already has a '{TRACKER_TAB}' tab; rename or delete it first.")

    copied = sheets.spreadsheets().sheets().copyTo(
        spreadsheetId=source_id, sheetId=src_tab_id, body={"destinationSpreadsheetId": target_id}
    ).execute()
    reqs = [{"updateSheetProperties": {"properties": {"sheetId": copied["sheetId"], "title": TRACKER_TAB},
                                       "fields": "title"}}]
    if args.keep_rows:
        rows = copied["gridProperties"]["rowCount"]
        if rows > args.keep_rows:
            reqs.append({"deleteDimension": {"range": {"sheetId": copied["sheetId"], "dimension": "ROWS",
                                                       "startIndex": args.keep_rows, "endIndex": rows}}})
    sheets.spreadsheets().batchUpdate(spreadsheetId=target_id, body={"requests": reqs}).execute()
    print(f"Copied '{tab_name}' -> '{TRACKER_TAB}' in {target_id}"
          + (f", kept rows 1-{args.keep_rows}" if args.keep_rows else ""))


if __name__ == "__main__":
    main()
