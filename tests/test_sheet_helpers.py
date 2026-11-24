import pytest


@pytest.mark.parametrize("index,letters", [(0, "A"), (25, "Z"), (26, "AA"), (51, "AZ"), (701, "ZZ"), (702, "AAA")])
def test_col_letter(tracker, index, letters):
    assert tracker.col_letter(index) == letters


def test_keyword_rows_skip_headers_and_rows_without_volume(tracker, example_rows):
    assert tracker.keyword_rows(example_rows) == [
        (2, "boat rental software"),
        (3, "boat hire booking app"),
        (4, "marina slip scheduling"),
        (5, "how much to charge for boat hire"),
    ]


def test_keyword_whitespace_is_collapsed(tracker):
    rows = [[], [], ["", "  boat   rental\tsoftware ", "10"]]
    assert tracker.keyword_rows(rows) == [(2, "boat rental software")]


def test_previous_group_is_latest_first_market_header(tracker, example_rows):
    assert tracker.previous_group_col(example_rows, 7) == 5
    assert tracker.previous_group_col(example_rows, 5) == 3
    assert tracker.previous_group_col(example_rows, 3) is None


@pytest.mark.parametrize("value,expected", [
    ("12", 12), (" 7 ", 7), ("-", None), ("", "unknown"), ("64/blog", 64), ("9, O", 9), ("n/a", "unknown")])
def test_parse_position(tracker, value, expected):
    assert tracker.parse_position(value) == expected


@pytest.mark.parametrize("prev,current,expected", [
    (12, 9, "+3"), (9, 12, "-3"), (7, 7, "0"), (None, 33, "entered"), (41, None, "dropped out"),
    (None, None, ""), ("unknown", 5, ""), ("unknown", None, "")])
def test_describe_change(tracker, prev, current, expected):
    assert tracker.describe_change(prev, current) == expected


def test_read_tracker_reports_missing_tab(tracker):
    from conftest import FakeGoogle

    with pytest.raises(SystemExit, match="Tracker"):
        tracker.read_tracker(FakeGoogle([[""]], tab="Other"), "example-sheet-id")
