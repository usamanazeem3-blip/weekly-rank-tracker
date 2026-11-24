import pytest


def test_example_config_is_loaded(tracker):
    assert tracker.TARGET_DOMAIN == "harbourly.example"
    assert list(tracker.MARKETS) == ["UK", "US"]
    assert tracker.MARKETS["UK"] == {"domain": "co.uk", "location": "GB", "locale": "en_GB"}
    assert str(tracker.TZ) == "Europe/London"


def test_defaults_when_settings_are_blank(load_tracker):
    rt = load_tracker(MARKETS="", TIMEZONE="", DATE_FORMAT="", REPORT_SUBJECT="", MAX_RESULTS="", TRACKER_TAB="")
    assert list(rt.MARKETS) == ["US"]
    assert str(rt.TZ) == "UTC"
    assert rt.DATE_FORMAT == "%Y-%m-%d"
    assert rt.MAX_RESULTS == 100
    assert rt.TRACKER_TAB == "Tracker"
    assert rt.REPORT_SUBJECT == "Google rankings for {domain} - {date}"


def test_target_domain_is_normalised(load_tracker):
    assert load_tracker(TARGET_DOMAIN=" WWW.Harbourly.Example ").TARGET_DOMAIN == "harbourly.example"


def test_markets_keep_order_and_accept_custom_definitions(tracker):
    markets = tracker.parse_markets("ca, us ,NL=nl:NL:nl_NL")
    assert list(markets) == ["CA", "US", "NL"]
    assert markets["NL"] == {"domain": "nl", "location": "NL", "locale": "nl_NL"}


@pytest.mark.parametrize("spec", ["XX", "NL=nl:NL", ",", "NL=::"])
def test_bad_market_specs_are_rejected(tracker, spec):
    with pytest.raises(ValueError):
        tracker.parse_markets(spec)


def test_missing_target_domain_stops_the_run(load_tracker):
    rt = load_tracker(TARGET_DOMAIN="")
    with pytest.raises(SystemExit, match="TARGET_DOMAIN"):
        rt.run()


def test_csv_filename_uses_domain(tracker):
    from datetime import date

    assert tracker.csv_filename(date(2026, 1, 19)) == "harbourly_rank_tracker_2026-01-19.csv"
