"""Idempotent source discovery with bounded calls and canonical URL deduplication."""

import ipaddress
import json
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from gridlens.contracts import (
    DiscoveryRequest,
    SearchCandidate,
    SearchHitDTO,
    SearchProvider,
    SearchRunDetail,
)
from gridlens.db import Database, now
from gridlens.errors import AppError
from gridlens.repositories.sources import SourceRepository

TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
}


def canonicalize_public_url(value: str) -> str:
    try:
        parts = urlsplit(value.strip())
        port = parts.port
    except ValueError:
        raise AppError("INVALID_URL", "Enter a valid public HTTP(S) URL.") from None
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username:
        raise AppError("INVALID_URL", "Enter a valid public HTTP(S) URL.")
    hostname = parts.hostname.casefold().rstrip(".")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if hostname == "localhost" or (address and not address.is_global):
        raise AppError("URL_BLOCKED", "Local addresses cannot be added as sources.")
    netloc = hostname
    if port and not (
        (parts.scheme == "http" and port == 80) or (parts.scheme == "https" and port == 443)
    ):
        netloc = f"{hostname}:{port}"
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_") and key.casefold() not in TRACKING_PARAMETERS
    ]
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.casefold(), netloc, path, urlencode(sorted(query)), ""))


def queries_for(request: DiscoveryRequest) -> list[str]:
    candidates = [request.topic]
    region = {"NZ": "New Zealand", "US": "United States", "ALL": ""}[request.region]
    if region and region.casefold() not in request.topic.casefold():
        candidates.append(f"{request.topic} {region}")
    if request.source_types:
        label = " ".join(value.replace("_", " ") for value in request.source_types)
        candidates.append(f"{request.topic} {label}")
    unique: list[str] = []
    for query in candidates:
        query = " ".join(query.split())
        if query.casefold() not in {item.casefold() for item in unique}:
            unique.append(query)
    return unique[:3]


@dataclass
class DiscoveryService:
    db: Database
    sources: SourceRepository
    provider: SearchProvider | None
    mode: str
    max_calls: int = 3
    max_results: int = 10

    def discover(self, request: DiscoveryRequest, operation_key: str) -> SearchRunDetail:
        operation_key = operation_key.strip()
        if not operation_key:
            raise AppError("INVALID_INPUT", "A search operation key is required.")
        existing = self.sources.get_search_run(operation_key, self.mode)
        if existing:
            return existing
        if self.provider is None:
            raise AppError("CONFIG_MISSING", "Live search is not configured.")
        queries = queries_for(request)
        run_id = str(uuid4())
        started = now()
        filters = {
            "region": request.region,
            "source_types": request.source_types,
            "error_codes": [],
        }
        try:
            with self.db.transaction() as c:
                c.execute(
                    "INSERT INTO search_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        run_id,
                        operation_key,
                        request.topic,
                        json.dumps(filters),
                        json.dumps(queries),
                        "fixture" if self.mode == "fixture" else "tavily",
                        "running",
                        0,
                        started,
                        None,
                        None,
                    ),
                )
        except Exception as error:
            existing = self.sources.get_search_run(operation_key, self.mode)
            if existing:
                return existing
            raise error

        hits_by_url: dict[str, tuple[SearchHitDTO, str]] = {}
        errors: list[str] = []
        calls = 0
        for query in queries:
            if calls >= self.max_calls:
                break
            calls += 1
            try:
                hits = self.provider.search(query, self.max_results)
            except AppError as error:
                errors.append(error.code)
                continue
            for hit in hits:
                try:
                    canonical = canonicalize_public_url(hit.url)
                except AppError:
                    continue
                current = hits_by_url.get(canonical)
                if current is None or hit.provider_rank < current[0].provider_rank:
                    hits_by_url[canonical] = (hit, query)

        ordered = sorted(
            hits_by_url.items(),
            key=lambda item: (
                item[1][0].provider_rank,
                -(item[1][0].metadata_evidence.get("provider_score") or 0),
                item[0],
            ),
        )[: self.max_results]
        status = "partial" if errors and ordered else "failed" if errors else "completed"
        error_code = errors[0] if status == "failed" and errors else None
        filters["error_codes"] = errors
        with self.db.transaction() as c:
            for rank, (canonical, (hit, query)) in enumerate(ordered, start=1):
                source_id = self.sources.save_candidate_with_connection(
                    c, hit, canonical, topic=request.topic
                )
                c.execute(
                    "INSERT INTO search_hits VALUES (?,?,?,?,?,?,?)",
                    (
                        str(uuid4()),
                        run_id,
                        source_id,
                        rank,
                        hit.snippet,
                        f"Returned for “{query}”; review the original before approval.",
                        json.dumps(
                            {
                                **hit.metadata_evidence,
                                "published_at": hit.published_at,
                                "provider_rank": hit.provider_rank,
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
            c.execute(
                "UPDATE search_runs SET status=?, calls_used=?, finished_at=?, error_code=?, "
                "filters_json=? WHERE id=?",
                (status, calls, now(), error_code, json.dumps(filters), run_id),
            )
        result = self.sources.get_search_run(operation_key, self.mode)
        if result is None:
            raise AppError("SEARCH_SAVE_FAILED", "The completed search could not be loaded.")
        return result

    def add_source(self, url: str, *, topic: str = "Manual source") -> SearchCandidate:
        canonical = canonicalize_public_url(url)
        host = urlsplit(canonical).hostname or "Unknown source"
        hit = SearchHitDTO(
            title=host,
            url=url.strip(),
            snippet="Manually added source; content has not been fetched or reviewed.",
            provider_rank=1,
            publisher=None,
            metadata_evidence={"provider": "manual"},
        )
        source_id = self.sources.save_candidate(hit, canonical, topic=topic)
        return SearchCandidate(
            source_id=source_id,
            title=hit.title,
            url=hit.url,
            snippet=hit.snippet,
            relevance_reason="Added manually; review the original before approval.",
            provider_rank=1,
        )
