"""Bounded public HTTP(S) capture with manual redirect and SSRF checks."""

import hashlib
import ipaddress
import socket
import time
from collections.abc import Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from gridlens.contracts import FetchedDocument
from gridlens.db import now
from gridlens.errors import AppError

Resolver = Callable[[str, int], list[str]]


def system_resolver(host: str, port: int) -> list[str]:
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise AppError(
            "DNS_FAILED", "The source host could not be resolved.", retryable=True
        ) from None
    return sorted({record[4][0] for record in records})


def validate_public_url(url: str, resolver: Resolver = system_resolver) -> str:
    try:
        parts = urlsplit(url.strip())
        explicit_port = parts.port
    except ValueError:
        raise AppError("INVALID_URL", "Enter a valid public HTTP(S) URL.") from None
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username:
        raise AppError("INVALID_URL", "Enter a valid public HTTP(S) URL.")
    default_port = 443 if parts.scheme == "https" else 80
    if explicit_port is not None and explicit_port != default_port:
        raise AppError("URL_BLOCKED", "The source URL uses a port that is not allowed.")
    host = parts.hostname.casefold().rstrip(".")
    if host == "localhost":
        raise AppError("URL_BLOCKED", "Local or private source addresses are not allowed.")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    addresses = [str(literal)] if literal else resolver(host, default_port)
    if not addresses:
        raise AppError("DNS_FAILED", "The source host could not be resolved.", retryable=True)
    try:
        parsed = [ipaddress.ip_address(address) for address in addresses]
    except ValueError:
        raise AppError("DNS_FAILED", "The source host returned an invalid address.") from None
    if any(not address.is_global for address in parsed):
        raise AppError("URL_BLOCKED", "Local or private source addresses are not allowed.")
    netloc = host if explicit_port is None else f"{host}:{explicit_port}"
    path = parts.path or "/"
    return urlunsplit((parts.scheme.casefold(), netloc, path, parts.query, ""))


class DocumentFetcher:
    def __init__(
        self,
        *,
        max_bytes: int,
        timeout_seconds: float,
        max_redirects: int = 3,
        resolver: Resolver = system_resolver,
        transport: httpx.BaseTransport | None = None,
        client_factory: Callable[..., httpx.Client] = httpx.Client,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.max_bytes = max_bytes
        self.timeout_seconds = timeout_seconds
        self.max_redirects = max_redirects
        self.resolver = resolver
        self.transport = transport
        self.client_factory = client_factory
        self.clock = clock

    def fetch(self, url: str) -> FetchedDocument:
        requested_url = url.strip()
        current_url = requested_url
        started = self.clock()
        redirects = 0
        while True:
            current_url = validate_public_url(current_url, self.resolver)
            remaining = self.timeout_seconds - (self.clock() - started)
            if remaining <= 0:
                raise AppError("FETCH_TIMEOUT", "Document capture timed out.", retryable=True)
            try:
                with self.client_factory(
                    timeout=remaining, transport=self.transport, follow_redirects=False
                ) as client:
                    with client.stream(
                        "GET",
                        current_url,
                        headers={
                            "Accept": "text/html,application/xhtml+xml,application/pdf",
                            "User-Agent": "GridLens/0.1 document review",
                        },
                    ) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            if not location:
                                raise AppError(
                                    "REDIRECT_INVALID", "The source redirect is invalid."
                                )
                            if redirects >= self.max_redirects:
                                raise AppError(
                                    "TOO_MANY_REDIRECTS", "The source redirected too many times."
                                )
                            current_url = urljoin(current_url, location)
                            redirects += 1
                            continue
                        self._raise_for_status(response.status_code)
                        length = response.headers.get("content-length")
                        if length and length.isdigit() and int(length) > self.max_bytes:
                            raise AppError(
                                "DOCUMENT_TOO_LARGE", "The source document is too large."
                            )
                        body = bytearray()
                        for chunk in response.iter_bytes():
                            if self.clock() - started > self.timeout_seconds:
                                raise AppError(
                                    "FETCH_TIMEOUT", "Document capture timed out.", retryable=True
                                )
                            body.extend(chunk)
                            if len(body) > self.max_bytes:
                                raise AppError(
                                    "DOCUMENT_TOO_LARGE", "The source document is too large."
                                )
                        content_type = self._content_type(
                            response.headers.get("content-type", ""), bytes(body)
                        )
            except httpx.TimeoutException:
                raise AppError(
                    "FETCH_TIMEOUT", "Document capture timed out.", retryable=True
                ) from None
            except httpx.HTTPError:
                raise AppError(
                    "FETCH_UNAVAILABLE", "The source could not be reached.", retryable=True
                ) from None
            if not body:
                raise AppError("DOCUMENT_EMPTY", "The source document is empty.")
            data = bytes(body)
            return FetchedDocument(
                requested_url=requested_url,
                final_url=current_url,
                content_type=content_type,
                body=data,
                raw_sha256=hashlib.sha256(data).hexdigest(),
                fetched_at=now(),
                redirect_count=redirects,
            )

    @staticmethod
    def _content_type(header: str, body: bytes) -> str:
        mime = header.partition(";")[0].strip().casefold()
        if body.startswith(b"%PDF-") and mime in {"application/pdf", "application/octet-stream"}:
            return "application/pdf"
        if mime in {"text/html", "application/xhtml+xml"} and not body.startswith(b"%PDF-"):
            return "text/html"
        raise AppError(
            "DOCUMENT_TYPE_UNSUPPORTED", "Only public HTML and PDF sources are supported."
        )

    @staticmethod
    def _raise_for_status(status: int) -> None:
        if status < 400:
            return
        if status in {401, 403}:
            raise AppError(
                "SOURCE_ACCESS_DENIED", "The source requires access that is unavailable."
            )
        if status == 404:
            raise AppError("SOURCE_NOT_FOUND", "The source document was not found.")
        if status == 429:
            raise AppError(
                "FETCH_RATE_LIMITED", "The source is temporarily rate limited.", retryable=True
            )
        if status >= 500:
            raise AppError(
                "FETCH_UNAVAILABLE", "The source is temporarily unavailable.", retryable=True
            )
        raise AppError("FETCH_FAILED", "The source request was rejected.")
