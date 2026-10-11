import gzip
import hashlib

import httpx
import pytest

from gridlens.documents.fetch import DocumentFetcher, validate_public_url
from gridlens.errors import AppError

PUBLIC = ["93.184.216.34"]


def resolver(host, port):
    assert port in {80, 443}
    return PUBLIC


def fetcher(handler, **changes):
    values = dict(
        max_bytes=1024,
        timeout_seconds=5,
        resolver=resolver,
        transport=httpx.MockTransport(handler),
    )
    values.update(changes)
    return DocumentFetcher(**values)


def test_fetches_html_and_records_hash_metadata():
    body = b"<html><main>Public guide</main></html>"
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200, headers={"content-type": "text/html; charset=utf-8"}, content=body
        )

    result = fetcher(handler).fetch("HTTPS://Example.org/guide#part")
    assert result.final_url == "https://example.org/guide"
    assert result.content_type == "text/html"
    assert result.body == body
    assert result.raw_sha256 == hashlib.sha256(body).hexdigest()
    assert result.redirect_count == 0
    assert seen[0].headers["accept"].startswith("text/html")


def test_accepts_pdf_by_mime_and_magic_header():
    body = b"%PDF-1.4\nsynthetic"
    result = fetcher(
        lambda request: httpx.Response(
            200, headers={"content-type": "application/pdf"}, content=body
        )
    ).fetch("https://example.org/report.pdf")
    assert result.content_type == "application/pdf"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://user@example.org/x",
        "http://localhost/x",
        "http://127.0.0.1/x",
        "http://10.0.0.1/x",
        "http://169.254.1.1/x",
        "http://[::1]/x",
        "https://example.org:8443/x",
    ],
)
def test_rejects_invalid_private_and_nonstandard_targets_before_request(url):
    with pytest.raises(AppError) as raised:
        validate_public_url(url, resolver)
    assert raised.value.code in {"INVALID_URL", "URL_BLOCKED"}


def test_rejects_domain_when_any_resolved_address_is_private():
    with pytest.raises(AppError) as raised:
        validate_public_url("https://example.org/x", lambda host, port: [PUBLIC[0], "10.0.0.1"])
    assert raised.value.code == "URL_BLOCKED"


def test_checks_every_redirect_and_blocks_private_destination():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    with pytest.raises(AppError) as raised:
        fetcher(handler).fetch("https://example.org/start")
    assert raised.value.code == "URL_BLOCKED"
    assert calls == 1


def test_follows_three_relative_redirects_and_rejects_a_fourth():
    def handler(request):
        index = int(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(302, headers={"location": f"/{index + 1}"})

    with pytest.raises(AppError) as raised:
        fetcher(handler).fetch("https://example.org/0")
    assert raised.value.code == "TOO_MANY_REDIRECTS"


def test_allows_three_redirects():
    def handler(request):
        index = int(request.url.path.rsplit("/", 1)[-1])
        if index < 3:
            return httpx.Response(302, headers={"location": f"/{index + 1}"})
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<p>ok</p>")

    result = fetcher(handler).fetch("https://example.org/0")
    assert result.redirect_count == 3
    assert result.final_url == "https://example.org/3"


@pytest.mark.parametrize("declared", [True, False])
def test_rejects_declared_or_streamed_oversize(declared):
    headers = {"content-type": "text/html"}
    if declared:
        headers["content-length"] = "20"
    response_body = b"<html>too large</html>"
    with pytest.raises(AppError) as raised:
        fetcher(
            lambda request: httpx.Response(200, headers=headers, content=response_body),
            max_bytes=10,
        ).fetch("https://example.org/large")
    assert raised.value.code == "DOCUMENT_TOO_LARGE"


def test_rejects_decompressed_body_over_limit():
    compressed = gzip.compress(b"<html>" + b"x" * 200 + b"</html>")
    with pytest.raises(AppError) as raised:
        fetcher(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/html", "content-encoding": "gzip"},
                content=compressed,
            ),
            max_bytes=100,
        ).fetch("https://example.org/compressed")
    assert raised.value.code == "DOCUMENT_TOO_LARGE"


def test_rejects_unsupported_or_mismatched_content():
    with pytest.raises(AppError) as raised:
        fetcher(
            lambda request: httpx.Response(
                200, headers={"content-type": "application/pdf"}, content=b"not a pdf"
            )
        ).fetch("https://example.org/report")
    assert raised.value.code == "DOCUMENT_TYPE_UNSUPPORTED"


def test_timeout_is_safe_and_retryable():
    def handler(request):
        raise httpx.ReadTimeout("upstream secret", request=request)

    with pytest.raises(AppError) as raised:
        fetcher(handler).fetch("https://example.org/slow")
    assert raised.value.code == "FETCH_TIMEOUT"
    assert raised.value.retryable
    assert "secret" not in str(raised.value)


def test_total_elapsed_time_is_checked_while_streaming():
    moments = iter([0.0, 0.0, 6.0])
    with pytest.raises(AppError) as raised:
        fetcher(
            lambda request: httpx.Response(
                200, headers={"content-type": "text/html"}, content=b"<p>late</p>"
            ),
            clock=lambda: next(moments),
        ).fetch("https://example.org/slow-stream")
    assert raised.value.code == "FETCH_TIMEOUT"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (403, "SOURCE_ACCESS_DENIED"),
        (404, "SOURCE_NOT_FOUND"),
        (429, "FETCH_RATE_LIMITED"),
        (503, "FETCH_UNAVAILABLE"),
    ],
)
def test_maps_http_errors(status, code):
    with pytest.raises(AppError) as raised:
        fetcher(lambda request: httpx.Response(status)).fetch("https://example.org/document")
    assert raised.value.code == code
