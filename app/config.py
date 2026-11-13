from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Proxy(BaseModel):
    name: str = Field(min_length=1)
    url: str

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Proxy must be an HTTP URL without credentials")
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise ValueError("Proxy URL must not include a path, query or fragment")
        return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GATEWAY_", env_file=".env", extra="ignore")

    api_token: str = Field(min_length=32)
    proxies: list[Proxy] = Field(min_length=1)
    allowed_domains: list[str] = Field(min_length=1)
    search_api_key: str = ""
    requests_per_minute: int = Field(default=60, ge=1)
    timeout_seconds: float = Field(default=30, gt=0, le=120)
    max_response_bytes: int = Field(default=2_000_000, ge=1024, le=10_000_000)
    max_concurrent_requests: int = Field(default=20, ge=1, le=200)

    @field_validator("allowed_domains")
    @classmethod
    def normalize_domains(cls, domains: list[str]) -> list[str]:
        normalized = [domain.lower().strip().rstrip(".") for domain in domains]
        if any(not domain or any(c in domain for c in "/:*@ ") for domain in normalized):
            raise ValueError("Use explicit domain names without wildcards, schemes or ports")
        return normalized

    @field_validator("proxies")
    @classmethod
    def unique_proxy_names(cls, proxies: list[Proxy]) -> list[Proxy]:
        if len({proxy.name for proxy in proxies}) != len(proxies):
            raise ValueError("Proxy names must be unique")
        return proxies
