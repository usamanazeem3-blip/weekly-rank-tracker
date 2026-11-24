"""End-to-end weekly runs on the fictional Harbourly tracker (examples/harbourly/tracker_example.csv)."""
import csv
import io
from datetime import datetime

from conftest import competitors, serp

SOFTWARE = "https://www.harbourly.example/software/"
BOOKING = "https://www.harbourly.example/booking/"
PRICING = "https://www.harbourly.example/blog/pricing-guide/"


def week3_serps():
    """Harbourly moves 9 -> 5 (UK) and 15 -> 15 (US) for its main keyword, enters the UK top 100
    for 'marina slip scheduling' on page 2, and the pricing guide drops out in the US."""
    return {
        ("boat rental software", "UK"): [serp(competitors(4) + [SOFTWARE])],
        ("boat rental software", "US"): [serp(competitors(10)), serp(competitors(4, 10) + [SOFTWARE])],
        ("boat hire booking app", "UK"): [serp(competitors(10, 0)), serp(competitors(10, 10)), serp(competitors(10, 20)),
                                          serp(competitors(1, 30) + [BOOKING])],
        ("boat hire booking app", "US"): [serp(competitors(10, 10 * i)) for i in range(10)],
        ("marina slip scheduling", "UK"): [serp(competitors(10)), serp(competitors(1, 10) + [SOFTWARE])],
        ("marina slip scheduling", "US"): [serp(competitors(10, 10 * i)) for i in range(10)],
        ("how much to charge for boat hire", "UK"): [serp(competitors(10, 10 * i)) for i in range(4)]
                                                      + [serp(competitors(1, 40) + [PRICING])],
        ("how much to charge for boat hire", "US"): [serp(competitors(10, 10 * i)) for i in range(10)],
    }


def test_weekly_run_adds_a_dated_column_group(tracker, wire, example_rows):
    fake = wire(tracker, example_rows, week3_serps())
    results = tracker.run()

    update = fake.value_update()
    assert update["range"] == "'Tracker'!H1:I7"
    today = datetime.now(tracker.TZ).strftime("%Y-%m-%d")
    assert update["body"]["values"] == [
        [today, ""], ["UK", "US"], [5, 15], [32, "-"], [12, "-"], [42, "-"], ["", ""]]
    changes = {(r["keyword"], r["market"]): r["change"] for r in results.values()}
    assert changes == {
        ("boat rental software", "UK"): "+4", ("boat rental software", "US"): "0",
        ("boat hire booking app", "UK"): "+1", ("boat hire booking app", "US"): "dropped out",
        ("marina slip scheduling", "UK"): "-5", ("marina slip scheduling", "US"): "",
        ("how much to charge for boat hire", "UK"): "+6", ("how much to charge for boat hire", "US"): "dropped out",
    }


def test_ranking_urls_become_cell_notes_and_columns_are_appended(tracker, wire, example_rows):
    fake = wire(tracker, example_rows, week3_serps(), col_count=7)
    tracker.run(email=False)
    first = fake.writes[0]
    assert first[0] == "batchUpdate"
    assert first[1]["body"]["requests"] == [
        {"appendDimension": {"sheetId": 7, "dimension": "COLUMNS", "length": 2}}]
    notes = {(n["range"]["startRowIndex"], n["range"]["startColumnIndex"]): n["rows"][0]["values"][0]["note"]
             for n in fake.notes_written()}
    assert notes == {(2, 7): SOFTWARE, (2, 8): SOFTWARE, (3, 7): BOOKING, (4, 7): SOFTWARE, (5, 7): PRICING}


def test_email_report(tracker, wire, example_rows):
    fake = wire(tracker, example_rows, week3_serps())
    tracker.run()
    [mail] = fake.sent
    date_label = datetime.now(tracker.TZ).strftime("%d %b %Y")
    assert mail["to"] == "jonas.okafor@harbourly.example"
    assert mail["subject"] == f"Harbourly weekly rankings - {date_label}"
    assert "Google rankings for <b>harbourly.example</b>" in mail["html"]
    assert f"<a href='{SOFTWARE}'>5</a>" in mail["html"]
    assert "dropped out" in mail["html"] and "+4" in mail["html"]
    assert "https://docs.google.com/spreadsheets/d/example-sheet-id" in mail["html"]

    name, data = mail["attachment"]
    assert name.startswith("harbourly_rank_tracker_") and name.endswith(".csv")
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    assert rows[1] == ["URL", "Keywords", "Volume", "UK", "US", "UK", "US", "UK", "US"]
    assert rows[2][-2:] == ["5", "15"]


def test_one_failed_lookup_does_not_stop_the_report(tracker, wire, example_rows):
    serps = week3_serps()
    del serps[("boat hire booking app", "US")]
    fake = wire(tracker, example_rows, serps)
    results = tracker.run()
    assert results[(3, "US")]["cell"] == "ERROR"
    assert fake.value_update()["body"]["values"][3] == [32, "ERROR"]
    assert "title='Oxylabs HTTP 500: simulated failure'" in fake.sent[0]["html"]


def test_single_market_run_leaves_other_column_blank(tracker, wire, example_rows):
    fake = wire(tracker, example_rows, week3_serps())
    tracker.run(markets=["US"], email=False)
    assert {m for _, m, _ in fake.fetch_calls} == {"US"}
    assert [row[0] for row in fake.value_update()["body"]["values"][2:6]] == ["", "", "", ""]


def test_no_sheet_no_email_only_reads(tracker, wire, example_rows):
    fake = wire(tracker, example_rows, week3_serps())
    tracker.run(write_sheet=False, email=False)
    assert fake.writes == [] and fake.sent == []


def test_email_without_sheet_write_has_no_attachment(tracker, wire, example_rows):
    fake = wire(tracker, example_rows, week3_serps())
    tracker.run(write_sheet=False)
    assert fake.sent[0]["attachment"] is None


def test_repair_rechecks_only_error_cells_in_place(tracker, wire, example_rows):
    rows = [list(r) for r in example_rows]
    rows[0] += ["2026-01-19", ""]
    rows[1] += ["UK", "US"]
    week3 = {2: ["5", "15"], 3: ["32", "ERROR"], 4: ["ERROR", "-"], 5: ["42", "-"]}
    for r, cells in week3.items():
        rows[r] += cells
    notes = [{}, {}, {"values": [{"note": SOFTWARE}, {"note": SOFTWARE}]}, {"values": [{"note": BOOKING}]},
             {}, {"values": [{"note": PRICING}]}]
    serps = {("boat hire booking app", "US"): [serp(competitors(10)), serp(competitors(10, 10)),
                                               serp(competitors(10, 20)), serp(competitors(9, 30) + [BOOKING])],
             ("marina slip scheduling", "UK"): [serp(competitors(10)), serp(competitors(1, 10) + [SOFTWARE])]}
    fake = wire(tracker, rows, serps, notes=notes)

    results = tracker.run(repair=True)

    assert sorted({(k, m) for k, m, _ in fake.fetch_calls}) == [
        ("boat hire booking app", "US"), ("marina slip scheduling", "UK")]
    update = fake.value_update()
    assert update["range"] == "'Tracker'!H1:I7"
    assert update["body"]["values"][:6] == [
        ["2026-01-19", ""], ["UK", "US"], ["5", "15"], ["32", 40], [12, "-"], ["42", "-"]]
    assert results[(3, "US")]["change"] == "-3"
    assert results[(2, "UK")]["url"] == SOFTWARE
    assert "19 Jan 2026" in fake.sent[0]["subject"]


def test_three_markets_use_three_column_groups(load_tracker, wire):
    rt = load_tracker(MARKETS="UK,US,CA")
    rows = [["", "", "", "2026-01-12", "", ""], ["URL", "Keywords", "Volume", "UK", "US", "CA"],
            [SOFTWARE, "boat rental software", "1900", "9", "15", "-"]]
    serps = {("boat rental software", m): [serp(competitors(n) + [SOFTWARE])] for m, n in
             [("UK", 4), ("US", 8), ("CA", 1)]}
    fake = wire(rt, rows, serps)
    results = rt.run(email=False)
    update = fake.value_update()
    assert update["range"] == "'Tracker'!G1:I3"
    assert update["body"]["values"][1:] == [["UK", "US", "CA"], [5, 9, 2]]
    assert results[(2, "CA")]["change"] == "entered"
