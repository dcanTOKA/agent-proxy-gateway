from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.config import Proxy, Settings
from app.main import create_app
from app.policy import is_public_address, validate_target
from app.proxies import ProxyPool
from app.web import Page


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        api_token="a" * 40,
        proxies=[Proxy(name="one", url="http://10.40.2.10:3128")],
        allowed_domains=["example.com", "api.search.brave.com"],
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


def test_token_required_before_network_access(client):
    client.app.state.web.fetch = AsyncMock()
    response = client.post("/fetch-page", json={"url": "https://example.com"})
    assert response.status_code == 401
    client.app.state.web.fetch.assert_not_called()


def test_fetch_returns_untrusted_text_and_selected_proxy(client):
    client.app.state.web.fetch = AsyncMock(
        return_value=Page("https://example.com/", "text/plain", "hello")
    )
    response = client.post(
        "/fetch-page",
        headers={"Authorization": "Bearer " + "a" * 40},
        json={"url": "https://example.com"},
    )
    assert response.status_code == 200
    assert response.json()["text"] == "hello"
    assert response.json()["untrusted_content"] is True
    assert response.json()["proxy"] == "one"
    assert response.headers["x-request-id"]


def test_search_requires_provider_configuration(client):
    response = client.post(
        "/web-search",
        headers={"Authorization": "Bearer " + "a" * 40},
        json={"query": "Azure"},
    )
    assert response.status_code == 503


def test_search_normalizes_provider_response(settings):
    settings.search_api_key = "test"
    with TestClient(create_app(settings)) as client:
        client.app.state.web.fetch = AsyncMock(
            return_value=Page(
                "https://api.search.brave.com",
                "application/json",
                '{"web":{"results":[{"title":"Example","url":"https://example.com",'
                '"description":"A result"}]}}',
            )
        )
        response = client.post(
            "/web-search",
            headers={"Authorization": "Bearer " + "a" * 40},
            json={"query": "Azure", "max_results": 1},
        )
        assert response.status_code == 200
        assert response.json()["results"][0]["snippet"] == "A result"
        assert client.app.state.web.fetch.call_args.args[2]["X-Subscription-Token"] == "test"


def test_gateway_rate_limit(settings):
    settings.requests_per_minute = 1
    with TestClient(create_app(settings)) as client:
        headers = {"Authorization": "Bearer " + "a" * 40}
        assert client.post("/web-search", headers=headers, json={"query": "x"}).status_code == 503
        response = client.post("/web-search", headers=headers, json={"query": "x"})
        assert response.status_code == 429
        assert response.headers["retry-after"] == "60"


def test_rotation_and_sticky_session():
    proxies = [Proxy(name=str(i), url=f"http://10.40.2.10:{3128 + i}") for i in range(3)]
    pool = ProxyPool(proxies)
    assert [pool.choose().name for _ in range(4)] == ["0", "1", "2", "0"]
    assert pool.choose("session-1") == pool.choose("session-1")
    assert ProxyPool(list(reversed(proxies))).choose("session-1") == pool.choose("session-1")


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "169.254.169.254",
        "168.63.129.16",
        "100.64.0.1",
        "::1",
        "::ffff:127.0.0.1",
        "192.0.2.1",
    ],
)
def test_reserved_addresses_blocked(address):
    assert not is_public_address(address)


async def test_private_dns_answer_blocked(monkeypatch):
    import asyncio

    monkeypatch.setattr(
        asyncio.get_running_loop(),
        "getaddrinfo",
        AsyncMock(return_value=[(2, 1, 6, "", ("10.0.0.1", 443))]),
    )
    with pytest.raises(Exception) as error:
        await validate_target("https://example.com", ["example.com"])
    assert error.value.status_code == 403


async def test_domain_matching_is_exact():
    with pytest.raises(Exception) as error:
        await validate_target("https://example.com.evil.test", ["example.com"])
    assert error.value.status_code == 403
