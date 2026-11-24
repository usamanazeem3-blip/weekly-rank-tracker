import json

import pytest

from conftest import EXAMPLE, competitors, serp


def test_sample_response_ranks_third_ignoring_ads(tracker, monkeypatch):
    sample = json.loads((EXAMPLE / "sample_oxylabs_response.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(tracker, "fetch_serp_page", lambda kw, m, p: sample)
    assert tracker.check_ranking("boat rental software", "UK") == {
        "position": 3, "url": "https://www.harbourly.example/software/"}


def test_position_counts_across_pages_and_stops_when_found(tracker, monkeypatch):
    pages = [serp(competitors(9)), serp(competitors(4, 9) + ["https://blog.harbourly.example/tips/"]), serp([])]
    calls = []
    monkeypatch.setattr(tracker, "fetch_serp_page", lambda kw, m, p: calls.append(p) or pages[p - 1])
    assert tracker.check_ranking("kw", "US") == {"position": 14, "url": "https://blog.harbourly.example/tips/"}
    assert calls == [1, 2]


def test_not_found_within_max_results(load_tracker, monkeypatch):
    rt = load_tracker(MAX_RESULTS="20")
    pages = [serp(competitors(10, 10 * i)) for i in range(5)]
    calls = []
    monkeypatch.setattr(rt, "fetch_serp_page", lambda kw, m, p: calls.append(p) or pages[p - 1])
    assert rt.check_ranking("kw", "US") == {"position": None, "url": ""}
    assert calls == [1, 2]


def test_result_beyond_max_results_is_not_counted(load_tracker, monkeypatch):
    rt = load_tracker(MAX_RESULTS="5")
    monkeypatch.setattr(rt, "fetch_serp_page",
                        lambda kw, m, p: serp(competitors(5) + ["https://www.harbourly.example/"]))
    assert rt.check_ranking("kw", "US")["position"] is None


def test_stops_at_last_visible_page(tracker, monkeypatch):
    calls = []
    monkeypatch.setattr(tracker, "fetch_serp_page",
                        lambda kw, m, p: calls.append(p) or serp(competitors(8, 8 * p), last_page=3))
    assert tracker.check_ranking("kw", "UK")["position"] is None
    assert calls == [1, 2, 3]


def test_unexpected_response_shape_raises(tracker, monkeypatch):
    monkeypatch.setattr(tracker, "fetch_serp_page", lambda kw, m, p: {"state": "done", "results": []})
    with pytest.raises(RuntimeError, match="No organic results"):
        tracker.check_ranking("kw", "UK")


def test_find_organic_accepts_alternative_key(tracker):
    assert tracker.find_organic({"a": [{"b": {"organic_results": [{"link": "x"}]}}]}) == [{"link": "x"}]


@pytest.mark.parametrize("url,expected", [
    ("https://www.harbourly.example/software/", True),
    ("https://harbourly.example", True),
    ("https://blog.harbourly.example:443/x", True),
    ("https://notharbourly.example/", False),
    ("https://harbourly.example.evil.example/", False),
    ("", False),
    (None, False),
])
def test_is_target(tracker, url, expected):
    assert tracker.is_target(url) is expected


def test_fetch_builds_oxylabs_request(tracker, monkeypatch):
    sent = {}

    class Resp:
        status_code, ok = 200, True

        def json(self):
            return serp(["https://www.harbourly.example/"])

    def post(url, headers, json, timeout):
        sent.update(url=url, headers=headers, payload=json)
        return Resp()

    monkeypatch.setattr(tracker.requests, "post", post)
    tracker.fetch_serp_page("boat hire booking app", "UK", 2)
    assert sent["url"] == tracker.OXYLABS_URL
    assert sent["headers"] == {"Authorization": "Bearer example-not-a-real-key"}
    assert sent["payload"] | {} == {"query": "boat hire booking app", "domain": "co.uk", "location": "GB",
                                    "locale": "en_GB", "device": "desktop", "start_page": 2, "pages": 1,
                                    "output": ["json"]}


def test_fetch_retries_server_errors(tracker, monkeypatch):
    statuses = iter([500, 429, 200])

    class Resp:
        def __init__(self):
            self.status_code = next(statuses)
            self.ok = self.status_code == 200
            self.text = ""

        def json(self):
            return serp([])

    monkeypatch.setattr(tracker.requests, "post", lambda *a, **k: Resp())
    monkeypatch.setattr(tracker.time, "sleep", lambda s: None)
    assert tracker.fetch_serp_page("kw", "US", 1)["state"] == "done"


def test_fetch_rejects_faulted_job(tracker, monkeypatch):
    class Resp:
        status_code, ok, text = 200, True, ""

        def json(self):
            return {"state": "faulted", "metadata": {"request_id": "r-1"}}

    monkeypatch.setattr(tracker.requests, "post", lambda *a, **k: Resp())
    with pytest.raises(RuntimeError, match="faulted"):
        tracker.fetch_serp_page("kw", "US", 1)
