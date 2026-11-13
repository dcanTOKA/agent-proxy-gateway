import json
from urllib.parse import urlencode

from fastapi import HTTPException
from pydantic import BaseModel, HttpUrl

from app.config import Settings
from app.web import WebClient


class SearchResult(BaseModel):
    title: str
    url: HttpUrl
    snippet: str


async def search(query: str, count: int, settings: Settings, web: WebClient) -> list[SearchResult]:
    if settings.search_provider == "none" or not settings.search_api_key:
        raise HTTPException(503, "Search provider is disabled or not configured")
    params = urlencode({"q": query, "count": count})
    page = await web.fetch(
        f"https://api.search.brave.com/res/v1/web/search?{params}",
        {"X-Subscription-Token": settings.search_api_key},
    )
    try:
        payload = json.loads(page.text)
        return [
            SearchResult(
                title=item.get("title", ""), url=item["url"], snippet=item.get("description", "")
            )
            for item in payload.get("web", {}).get("results", [])[:count]
        ]
    except (ValueError, KeyError, TypeError, AttributeError):
        raise HTTPException(502, "Invalid search provider response") from None
