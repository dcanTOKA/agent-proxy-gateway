import shutil
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.config import Settings
from app.web import Resource
from browser.main import render


@pytest.fixture
def settings():
    executable = shutil.which("chromium")
    if executable is None:
        pytest.skip("System Chromium is not installed")
    return Settings(
        _env_file=None,
        api_token="a" * 40,
        allowed_domains=["example.com"],
        chromium_executable=executable,
    )


async def test_chromium_executes_javascript_and_loads_resources_via_safe_client(
    settings, monkeypatch
):
    monkeypatch.setattr("browser.main.validate_target", AsyncMock())
    html = b"""<body><p id="result">before</p><script>
    fetch('/data').then(r => r.json()).then(data => {
        document.getElementById('result').innerText = data.message;
    });
    </script></body>"""

    async def resource(self, url):
        if url.endswith("/data"):
            return Resource(
                200, {"content-type": "application/json"}, b'{"message":"rendered by JavaScript"}'
            )
        return Resource(200, {"content-type": "text/html"}, html)

    monkeypatch.setattr("browser.main.WebClient.resource", resource)
    result = await render("https://example.com", settings)
    assert result["text"] == "rendered by JavaScript"


async def test_chromium_aborts_blocked_subresources(settings, monkeypatch):
    monkeypatch.setattr("browser.main.validate_target", AsyncMock())
    html = b'<body><script src="http://169.254.169.254/metadata"></script></body>'

    async def resource(self, url):
        if "169.254.169.254" in url:
            raise HTTPException(403, "Private destinations are blocked")
        return Resource(200, {"content-type": "text/html"}, html)

    monkeypatch.setattr("browser.main.WebClient.resource", resource)
    with pytest.raises(HTTPException) as error:
        await render("https://example.com", settings)
    assert error.value.status_code == 403
