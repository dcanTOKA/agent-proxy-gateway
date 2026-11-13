import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from fastapi import HTTPException

AZURE_INFRASTRUCTURE_IPS = {"168.63.129.16", "169.254.169.254"}


def is_public_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_global and str(address) not in AZURE_INFRASTRUCTURE_IPS


async def resolve_target(url: str, allowed_domains: list[str]) -> tuple[str, str]:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError:
        raise HTTPException(422, "Invalid URL") from None

    if parsed.scheme not in ("http", "https") or not host:
        raise HTTPException(422, "Only HTTP and HTTPS URLs are supported")
    if parsed.username or parsed.password:
        raise HTTPException(422, "URL credentials are not supported")
    expected_port = 443 if parsed.scheme == "https" else 80
    if port is not None and port != expected_port:
        raise HTTPException(422, "Only standard HTTP and HTTPS ports are supported")
    if host not in allowed_domains:
        raise HTTPException(403, "Domain is not allowed")

    try:
        addresses = await asyncio.get_running_loop().getaddrinfo(
            host, expected_port, type=socket.SOCK_STREAM
        )
    except socket.gaierror:
        raise HTTPException(502, "Target DNS lookup failed") from None
    if not addresses or any(not is_public_address(item[4][0]) for item in addresses):
        raise HTTPException(403, "Private and reserved destinations are blocked")
    return host, addresses[0][4][0]


async def validate_target(url: str, allowed_domains: list[str]) -> str:
    host, _ = await resolve_target(url, allowed_domains)
    return host


async def inspect_input(text: str) -> None:
    """Add outbound data policies here before forwarding a query or URL."""


async def inspect_output(text: str) -> None:
    """Add Content Safety or custom model checks here before returning content."""
