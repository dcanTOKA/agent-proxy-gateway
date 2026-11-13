import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from app.config import Settings
from app.policy import is_public_address, resolve_target
from app.web import WebClient


@pytest.fixture
def web(monkeypatch):
    settings = Settings(
        _env_file=None,
        api_token="a" * 40,
        allowed_domains=["example.com"],
        max_response_bytes=1024,
    )
    monkeypatch.setattr(
        "app.web.resolve_target", AsyncMock(return_value=("example.com", "93.184.215.14"))
    )
    return WebClient(settings)


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    options = []

    def client(**kwargs):
        options.append(kwargs)
        return original(transport=httpx.MockTransport(handler))

    monkeypatch.setattr("app.web.httpx.AsyncClient", client)
    return options


async def test_connection_uses_validated_ip_with_original_host_and_sni(web, monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200, headers={"content-type": "text/html"}, text="<h1>Hello</h1><script>bad()</script>"
        )

    options = transport(monkeypatch, handler)
    page = await web.fetch("https://example.com")
    assert page.text == "Hello"
    assert page.url == "https://example.com"
    assert calls[0].url.host == "93.184.215.14"
    assert calls[0].headers["host"] == "example.com"
    assert calls[0].extensions["sni_hostname"] == "example.com"
    assert options[0]["trust_env"] is False
    assert "proxy" not in options[0]


async def test_redirect_target_is_revalidated(web, monkeypatch):
    transport(
        monkeypatch,
        lambda request: httpx.Response(
            302, headers={"location": "http://169.254.169.254/metadata"}
        ),
    )
    check = AsyncMock(side_effect=[("example.com", "93.184.215.14"), HTTPException(403, "blocked")])
    monkeypatch.setattr("app.web.resolve_target", check)
    with pytest.raises(HTTPException) as error:
        await web.fetch("https://example.com")
    assert error.value.status_code == 403


async def test_provider_credentials_do_not_follow_redirects(web, monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "https://other.example/"})

    transport(monkeypatch, handler)
    with pytest.raises(HTTPException):
        await web.fetch("https://example.com", {"Secret": "key"})
    assert len(calls) == 1


async def test_429_preserves_retry_after(web, monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(429, headers={"retry-after": "120"}))
    with pytest.raises(HTTPException) as error:
        await web.fetch("https://example.com")
    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "120"


async def test_response_size_limit(web, monkeypatch):
    transport(
        monkeypatch,
        lambda request: httpx.Response(
            200, headers={"content-type": "text/plain"}, content=b"x" * 2048
        ),
    )
    with pytest.raises(HTTPException) as error:
        await web.fetch("https://example.com")
    assert error.value.status_code == 413


async def test_no_store_respected(web, monkeypatch):
    transport(
        monkeypatch,
        lambda request: httpx.Response(
            200, headers={"content-type": "text/plain", "cache-control": "no-store"}, text="secret"
        ),
    )
    assert (await web.fetch("https://example.com")).cacheable is False


@pytest.mark.parametrize(
    "address", ["10.0.0.1", "127.0.0.1", "168.63.129.16", "169.254.169.254", "::ffff:127.0.0.1"]
)
def test_private_and_metadata_addresses_blocked(address):
    assert not is_public_address(address)


async def test_private_dns_answer_blocked(monkeypatch):
    monkeypatch.setattr(
        asyncio.get_running_loop(),
        "getaddrinfo",
        AsyncMock(return_value=[(2, 1, 6, "", ("10.0.0.1", 443))]),
    )
    with pytest.raises(HTTPException) as error:
        await resolve_target("https://example.com", ["example.com"])
    assert error.value.status_code == 403


async def test_exact_domain_matching():
    with pytest.raises(HTTPException) as error:
        await resolve_target("https://example.com.evil.test", ["example.com"])
    assert error.value.status_code == 403
