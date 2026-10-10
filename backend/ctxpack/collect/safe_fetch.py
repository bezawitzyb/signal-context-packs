"""Guarded download of one public web address (change V13). The only place where the server itself
downloads a URL that came from search results or a scraped page, so it refuses anything that is not
an ordinary public website:

- http or https only, standard ports, no user name or password in the URL;
- the host must resolve to public addresses only (no localhost, private, link-local, carrier-grade NAT
  or cloud metadata ranges); the connection goes to the very address that was checked (no second DNS
  lookup an attacker could change), with TLS still verified against the host name;
- redirects are followed by hand (at most feeds.redirects_max), each one checked again;
- only HTML, RSS, Atom or XML bodies, at most feeds.max_bytes, within feeds.fetch_timeout_secs.

Never used in tests or offline mode against the network: tests pass a mock transport and resolver.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from typing import Awaitable, Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from ctxpack.config import load_yaml

USER_AGENT = "SIGNAL-ContextPacks/1.0 (+https://github.com/bezawitzyb/signal-context-packs)"
CONTENT_TYPES = ("text/html", "application/xhtml+xml", "application/rss+xml", "application/atom+xml",
                 "application/rdf+xml", "application/xml", "text/xml")
Resolver = Callable[[str, int], Awaitable[list[str]]]


class FetchRefused(Exception):
    """The URL or its answer broke a rule; the message says which (no secrets, no page text)."""


@dataclass
class Fetched:
    url: str              # the final URL, after redirects
    content_type: str
    body: bytes


def _cfg() -> dict:
    return load_yaml("modes")["feeds"]


async def system_resolver(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({info[4][0] for info in infos})


def check_url(url: str) -> tuple[str, str, int]:
    """(scheme, host, port) of an allowed URL, or FetchRefused."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError as exc:
        raise FetchRefused("not a valid URL") from exc
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise FetchRefused("only http and https addresses are read")
    if parts.username or parts.password:
        raise FetchRefused("addresses with a user name or password are never read")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise FetchRefused("the address has no host")
    default = 443 if scheme == "https" else 80
    if port not in (None, default):
        raise FetchRefused("only standard ports are read")
    return scheme, host, default


def public_ip(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


async def _public_address(host: str, port: int, resolver: Resolver) -> str:
    try:
        ipaddress.ip_address(host)
        addresses = [host]
    except ValueError:
        try:
            addresses = await resolver(host, port)
        except (OSError, UnicodeError) as exc:
            raise FetchRefused("the host could not be found") from exc
    if not addresses:
        raise FetchRefused("the host could not be found")
    if not all(public_ip(a) for a in addresses):
        raise FetchRefused("the host is not a public website")
    return addresses[0]


def _pinned(url: str, address: str) -> str:
    """The same URL with the checked IP address in place of the host name."""
    parts = urlsplit(url)
    ip = f"[{address}]" if ":" in address else address
    return urlunsplit((parts.scheme, ip, parts.path or "/", parts.query, ""))


async def fetch(url: str, *, transport: httpx.AsyncBaseTransport | None = None,
                resolver: Resolver = system_resolver) -> Fetched:
    """Download one allowed URL (see the module docstring), or raise FetchRefused. The whole download,
    redirects included, must finish within fetch_timeout_secs (a slow trickle cannot hold the worker)."""
    try:
        return await asyncio.wait_for(_fetch(url, transport, resolver), timeout=_cfg()["fetch_timeout_secs"])
    except asyncio.TimeoutError as exc:
        raise FetchRefused("the site was too slow") from exc


async def _fetch(url: str, transport: httpx.AsyncBaseTransport | None, resolver: Resolver) -> Fetched:
    cfg = _cfg()
    max_bytes, redirects = cfg["max_bytes"], cfg["redirects_max"]
    timeout = httpx.Timeout(cfg["fetch_timeout_secs"])
    async with httpx.AsyncClient(transport=transport, timeout=timeout, follow_redirects=False,
                                 trust_env=False) as client:
        for _ in range(redirects + 1):
            scheme, host, port = check_url(url)
            address = await _public_address(host, port, resolver)
            # browser-style Accept: some forums (Discourse) answer 404 when a page is asked for as RSS first
            headers = {"Host": host, "User-Agent": USER_AGENT,
                       "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
            request = client.build_request("GET", _pinned(url, address), headers=headers,
                                           extensions={"sni_hostname": host} if scheme == "https" else {})
            try:
                response = await client.send(request, stream=True)
            except httpx.HTTPError as exc:
                raise FetchRefused(f"the site did not answer ({type(exc).__name__})") from exc
            try:
                if response.is_redirect:
                    target = response.headers.get("location", "")
                    if not target:
                        raise FetchRefused("a redirect without a target")
                    url = urljoin(url, target)
                    continue
                if response.status_code != 200:
                    raise FetchRefused(f"the site answered {response.status_code}")
                content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if content_type not in CONTENT_TYPES:
                    raise FetchRefused("not a web page or feed")
                declared = response.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > max_bytes:
                    raise FetchRefused("too large")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > max_bytes:
                        raise FetchRefused("too large")
                return Fetched(url=url, content_type=content_type, body=bytes(body))
            finally:
                await response.aclose()
    raise FetchRefused("too many redirects")
