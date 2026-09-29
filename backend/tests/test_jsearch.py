"""The JSearch adapter, against canned responses: no network."""

from __future__ import annotations

import httpx
import pytest

from app.config import settings
from app.settings_store import UserSettings
from app.sources.base import SourceError
from app.sources.jsearch import JSearchSource, _date_posted

RESULTS = {
    "status": "OK",
    "data": [
        {
            "job_id": "abc==",
            "job_title": "Junior Python Developer (m/w/d)",
            "employer_name": "Acme GmbH",
            "job_publisher": "StepStone",
            "job_city": "Berlin",
            "job_country": "DE",
            "job_is_remote": False,
            "job_apply_link": "https://google.example/apply",
            "apply_options": [
                {"publisher": "StepStone", "apply_link": "https://www.stepstone.de/job/abc"}
            ],
            "job_description": "Python, FastAPI.",
            "job_posted_at_datetime_utc": "2026-09-27T08:00:00.000Z",
        },
        {
            "job_id": "def==",
            "job_title": "Python Developer",
            "employer_name": "Beta AG",
            "job_publisher": "Indeed",
            "job_location": "Hamburg, Germany",
            "job_is_remote": True,
            "job_apply_link": "https://de.indeed.com/viewjob?jk=def",
            "job_description": "Django.",
        },
        {
            "job_id": "ghi==",
            "job_title": "Python Developer",
            "employer_name": "Gamma",
            "job_publisher": "SomeSpamBoard",
            "job_description": "x",
        },
    ],
}


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setattr(settings, "jsearch_api_key", "test-key")
    monkeypatch.setattr("app.sources.jsearch.DELAY_SECONDS", 0)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_not_configured_without_a_key():
    assert JSearchSource(UserSettings()).is_configured() is False


def test_fetch_keeps_wanted_publishers_and_prefers_their_own_link(keyed):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=RESULTS)

    config = UserSettings(keywords=["python developer"], locations=["Berlin"])
    jobs = JSearchSource(config).fetch(_client(handler))

    assert {job.raw["publisher"] for job in jobs} == {"StepStone", "Indeed"}
    stepstone = next(job for job in jobs if job.source_id == "abc==")
    assert stepstone.url == "https://www.stepstone.de/job/abc"
    assert stepstone.location == "Berlin, Germany"
    assert stepstone.posted_date is not None
    indeed = next(job for job in jobs if job.source_id == "def==")
    assert indeed.remote is True and indeed.location == "Hamburg, Germany"

    sent = requests[0]
    assert sent.url.host == "api.openwebninja.com" and sent.url.path == "/jsearch/search"
    assert sent.headers["X-API-Key"] == "test-key"
    assert sent.url.params["query"] == "python developer in Berlin, Germany"
    assert sent.url.params["country"] == "de"


def test_request_budget_is_respected(keyed):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": []})

    config = UserSettings(keywords=[f"k{i}" for i in range(10)], jsearch_max_requests=3)
    JSearchSource(config).fetch(_client(handler))
    assert len(calls) == 3


def test_bad_key_is_a_source_error(keyed):
    with pytest.raises(SourceError, match="API key"):
        JSearchSource(UserSettings()).fetch(_client(lambda r: httpx.Response(403)))


def test_date_bucket():
    assert _date_posted(1) == "today"
    assert _date_posted(7) == "week"
    assert _date_posted(20) == "month"
    assert _date_posted(90) == "all"


def test_rapidapi_host_switches_url_and_headers(keyed, monkeypatch):
    monkeypatch.setattr(settings, "jsearch_api_host", "jsearch.p.rapidapi.com")
    requests: list[httpx.Request] = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=RESULTS)

    JSearchSource(UserSettings(keywords=["x"])).fetch(_client(handler))
    assert str(requests[0].url).startswith("https://jsearch.p.rapidapi.com/search?")
    assert requests[0].headers["X-RapidAPI-Key"] == "test-key"


def test_v2_response_shape_is_read(keyed):
    v2 = {"status": "OK", "data": {"jobs": RESULTS["data"], "cursor": None}}
    jobs = JSearchSource(UserSettings(keywords=["x"])).fetch(
        _client(lambda r: httpx.Response(200, json=v2))
    )
    assert len(jobs) == 2
