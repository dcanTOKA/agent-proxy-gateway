from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.web import Page


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        api_token="a" * 40,
        allowed_domains=["example.com", "api.search.brave.com"],
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


AUTH = {"Authorization": "Bearer " + "a" * 40}


def test_token_required_before_network_access(client):
    client.app.state.web.fetch = AsyncMock()
    response = client.post("/fetch-page", json={"url": "https://example.com"})
    assert response.status_code == 401
    client.app.state.web.fetch.assert_not_called()


def test_fetch_reuses_cached_content(client):
    client.app.state.web.fetch = AsyncMock(
        return_value=Page("https://example.com/", "text/plain", "hello")
    )
    first = client.post("/fetch-page", headers=AUTH, json={"url": "https://example.com"})
    second = client.post("/fetch-page", headers=AUTH, json={"url": "https://example.com"})
    assert first.status_code == second.status_code == 200
    assert first.json()["cache_hit"] is False
    assert second.json()["cache_hit"] is True
    assert second.json()["untrusted_content"] is True
    assert "proxy" not in second.json()
    client.app.state.web.fetch.assert_awaited_once()


def test_no_store_response_is_not_cached(client):
    client.app.state.web.fetch = AsyncMock(
        return_value=Page("https://example.com/", "text/plain", "secret", cacheable=False)
    )
    for _ in range(2):
        client.post("/fetch-page", headers=AUTH, json={"url": "https://example.com"})
    assert client.app.state.web.fetch.await_count == 2


def test_search_is_opt_in(client):
    client.app.state.web.fetch = AsyncMock()
    response = client.post("/web-search", headers=AUTH, json={"query": "Azure"})
    assert response.status_code == 503
    client.app.state.web.fetch.assert_not_called()


def test_search_cache_avoids_duplicate_provider_calls(settings):
    settings.search_provider = "brave"
    settings.search_api_key = "test-key"
    with TestClient(create_app(settings)) as client:
        client.app.state.web.fetch = AsyncMock(
            return_value=Page(
                "https://api.search.brave.com",
                "application/json",
                '{"web":{"results":[{"title":"Example","url":"https://example.com",'
                '"description":"A result"}]}}',
            )
        )
        for cached in [False, True]:
            response = client.post("/web-search", headers=AUTH, json={"query": "Azure"})
            assert response.status_code == 200
            assert response.json()["cache_hit"] is cached
        client.app.state.web.fetch.assert_awaited_once()


def test_search_limit_is_separate_from_fetch(settings):
    settings.search_requests_per_minute = 1
    with TestClient(create_app(settings)) as client:
        client.post("/web-search", headers=AUTH, json={"query": "x"})
        assert client.post("/web-search", headers=AUTH, json={"query": "x"}).status_code == 429
        client.app.state.web.fetch = AsyncMock(
            return_value=Page("https://example.com", "text/plain", "ok")
        )
        assert (
            client.post(
                "/fetch-page", headers=AUTH, json={"url": "https://example.com"}
            ).status_code
            == 200
        )


def test_browse_delegates_to_separate_worker(client, monkeypatch):
    monkeypatch.setattr("app.main.policy.validate_target", AsyncMock())
    render = AsyncMock(
        return_value=type("Result", (), {"url": "https://example.com", "text": "rendered"})()
    )
    monkeypatch.setattr("app.main.browser_client.browse", render)
    client.app.state.web.fetch = AsyncMock()
    response = client.post("/browse-page", headers=AUTH, json={"url": "https://example.com"})
    assert response.status_code == 200
    assert response.json()["text"] == "rendered"
    render.assert_awaited_once()
    client.app.state.web.fetch.assert_not_called()


def test_browse_is_disabled_when_worker_is_not_configured(client, monkeypatch):
    monkeypatch.setattr("app.main.policy.validate_target", AsyncMock())
    response = client.post("/browse-page", headers=AUTH, json={"url": "https://example.com"})
    assert response.status_code == 503
