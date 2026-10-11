"""Markdown research log: traceable records only, never generated conclusions.

Everything user- or source-provided is escaped; raw HTML cannot render; only HTTP(S) links
are emitted; snapshot paths, credentials and provider payloads are never read here.
"""

import json
import re
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

from pydantic import Field

from gridlens.contracts import DTO
from gridlens.db import Database
from gridlens.services.citations import source_statuses

DISPLAY_ZONE = ZoneInfo("Pacific/Auckland")
_MARKDOWN = re.compile(r"([\\`*_{}\[\]()#+\-.!|~>])")
_LINE_START = re.compile(r"^(\s*)(\d+)\.", re.MULTILINE)


class ExportSelection(DTO):
    version_ids: list[str] = Field(default_factory=list)
    qa_ids: list[str] = Field(default_factory=list)
    gap_ids: list[str] = Field(default_factory=list)
    include_open_gaps: bool = True


def md(text) -> str:
    """Escapes one inline value: no Markdown structure, no HTML, one line."""
    value = " ".join(str(text if text is not None else "").split())
    value = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return _MARKDOWN.sub(r"\\\1", value)


def safe_url(url) -> str | None:
    if not isinstance(url, str) or any(ch.isspace() or ord(ch) < 32 for ch in url):
        return None
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    # Percent-encode anything that could end or break a Markdown link.
    return quote(url, safe=":/?#@!$&'*+,;=%-._~")


def link(title, url) -> str:
    target = safe_url(url)
    label = md(title or "Untitled")
    return f"[{label}]({target})" if target else f"{label} (link withheld: not an HTTP(S) URL)"


class ExportService:
    def __init__(self, db: Database, *, mode: str, index_fingerprint: str | None):
        self.db = db
        self.mode = mode
        self.index_fingerprint = index_fingerprint

    def export(self, selection: ExportSelection, *, generated_at: datetime | None = None) -> str:
        generated_at = generated_at or datetime.now(UTC)
        lines = [
            "# GridLens research log",
            "",
            f"- Generated: {generated_at.strftime('%Y-%m-%d %H:%M UTC')} "
            f"({generated_at.astimezone(DISPLAY_ZONE).strftime('%Y-%m-%d %H:%M %Z')})",
            f"- Mode: {md(self.mode)}",
            "- Contents: selected records only. This log contains no generated conclusions.",
        ]
        if self.mode == "fixture":
            lines.append("- Warning: synthetic development data, not real grid research.")
        with self.db.connect() as c:
            versions = self._rows(c, "document_versions", selection.version_ids)
            qa = self._rows(c, "qa_records", selection.qa_ids)
            gaps = self._rows(c, "knowledge_gaps", selection.gap_ids)
            if selection.include_open_gaps:
                known = {g["id"] for g in gaps}
                gaps += [
                    dict(g)
                    for g in c.execute(
                        "SELECT * FROM knowledge_gaps WHERE status='open' ORDER BY updated_at"
                    )
                    if g["id"] not in known
                ]
            events = {
                v["id"]: [
                    dict(e)
                    for e in c.execute(
                        "SELECT * FROM review_events WHERE version_id=? ORDER BY created_at",
                        (v["id"],),
                    )
                ]
                for v in versions
            }
        cited = sorted(
            {
                citation["source"]["version_id"]
                for record in qa
                if record["answer_json"]
                for citation in json.loads(record["answer_json"])["citations"]
            }
            | {v["id"] for v in versions}
        )
        statuses = source_statuses(self.db, cited, self.index_fingerprint)
        lines += self._sources(versions, statuses, events)
        lines += self._answers(qa, statuses)
        lines += self._gaps(gaps)
        return "\n".join(lines).rstrip() + "\n"

    def _sources(self, versions, statuses, events) -> list[str]:
        current = [v for v in versions if statuses.get(v["id"]) == "current"]
        historical = [
            v
            for v in versions
            if v["review_status"] == "revoked" or v["version_status"] == "superseded"
        ]
        leads = [
            v
            for v in versions
            if v["review_status"] in {"pending", "rejected"} and v["version_status"] != "superseded"
        ]
        other = [v for v in versions if v not in current + historical + leads]
        lines: list[str] = []
        if current:
            lines += ["", "## Current approved sources", ""]
            for v in current:
                lines += self._source_entry(v, "current", events[v["id"]])
        if historical or other:
            lines += ["", "## Historical or not current sources", ""]
            for v in historical + other:
                status = statuses.get(v["id"], "not_current")
                lines += self._source_entry(v, status, events[v["id"]])
        if leads:
            lines += ["", "## Leads awaiting review (no document text exported)", ""]
            for v in leads:
                lines += self._source_entry(v, v["review_status"], events[v["id"]])
        return lines

    @staticmethod
    def _source_entry(version, status, events) -> list[str]:
        meta = json.loads(version["metadata_json"])
        entry = [
            f"- {link(meta.get('title'), meta.get('original_url'))}",
            f"  - Status: {md(status)} · version {md(version['id'][:8])} · snapshot "
            f"{md(version['snapshot_sha256'][:12])}",
            f"  - {md(meta.get('publisher') or 'Publisher unknown')} · "
            f"{md(meta.get('published_at') or 'Date unknown')} · "
            f"{md(meta.get('jurisdiction') or 'UNKNOWN')} · "
            f"{md(meta.get('source_type') or 'unknown')}",
        ]
        for event in events:
            note = f": {md(event['reason'])}" if event["reason"] else ""
            entry.append(
                f"  - Review: {md(event['action'])} by {md(event['reviewer_label'])} on "
                f"{md(event['created_at'][:10])}{note}"
            )
        return entry

    def _answers(self, records, statuses) -> list[str]:
        if not records:
            return []
        lines = ["", "## Questions and answers"]
        for record in records:
            lines += ["", f"### {md(record['question'])}", ""]
            filters = json.loads(record["filters_json"])
            lines.append(
                f"- Asked: {md(record['created_at'][:16])} UTC · region "
                f"{md(filters.get('region'))} · status {md(record['execution_status'])}"
                + (f"/{md(record['evidence_status'])}" if record["evidence_status"] else "")
            )
            if record["execution_status"] != "completed":
                lines.append(
                    f"- No answer was published ({md(record['error_code'] or 'unknown')})."
                )
                continue
            answer = json.loads(record["answer_json"])
            citations = answer["citations"]
            source_states = {statuses.get(c["source"]["version_id"]) for c in citations}
            if "revoked" in source_states or "not_current" in source_states:
                lines.append(
                    "- Historical answer: it cites sources that are no longer approved; "
                    "treat it as a record, not current evidence."
                )
            numbers = {c["chunk_id"]: c["number"] for c in citations}
            usable = {
                c["chunk_id"]
                for c in citations
                if statuses.get(c["source"]["version_id"]) in {"current", "superseded"}
            }
            for claim in answer["draft"]["claims"]:
                if not any(e["chunk_id"] in usable for e in claim["evidence"]):
                    # Claim wording can reproduce a revoked source; keep only the record.
                    lines.append(
                        f"- Claim {md(claim['claim_id'])} omitted: it relied only on sources "
                        "that are no longer approved."
                    )
                    continue
                marks = "".join(
                    f" \\[{numbers[e['chunk_id']]}\\]"
                    for e in claim["evidence"]
                    if e["chunk_id"] in numbers
                )
                kind = "Fact" if claim["kind"] == "fact" else "Inference"
                lines.append(f"- {kind}: {md(claim['text'])}{marks}")
            for limitation in answer["draft"]["limitations"]:
                lines.append(f"- Limitation: {md(limitation)}")
            for missing in answer["draft"]["missing_evidence"]:
                lines.append(
                    f"- Missing evidence: {md(missing['subquestion'])} — "
                    f"{md(missing['needed_evidence'])}"
                )
            for citation in citations:
                source = citation["source"]
                status = statuses.get(source["version_id"], "not_current")
                target = link(source.get("title"), source.get("original_url"))
                lines.append(
                    f"- \\[{citation['number']}\\] {target}"
                    f" · {md(self._location(citation['locator']))} · source {md(status)}"
                )
                if status in {"current", "superseded"}:
                    label = " (superseded version)" if status == "superseded" else ""
                    lines.append(f"  - Quote{label}: “{md(citation['quote'])}”")
                else:
                    lines.append("  - Quote omitted: the source is no longer approved.")
        return lines

    @staticmethod
    def _gaps(gaps) -> list[str]:
        if not gaps:
            return []
        lines = ["", "## Knowledge gaps", ""]
        for gap in gaps:
            scope = json.loads(gap["scope_json"])
            queries = json.loads(gap["suggested_queries_json"])
            lines += [
                f"- {md(gap['question'])}",
                f"  - Status: {md(gap['status'])} · reason {md(gap['reason_type'])} · region "
                f"{md(scope.get('filters', {}).get('region'))}",
                f"  - Missing evidence: {md(gap['missing_evidence'])}",
                f"  - Suggested searches: {'; '.join(md(q) for q in queries)}",
            ]
            if gap["resolution_note"]:
                lines.append(f"  - Note: {md(gap['resolution_note'])}")
        return lines

    @staticmethod
    def _location(locator: dict) -> str:
        if locator.get("kind") == "pdf":
            text = f"file page {locator.get('file_page')}"
            if locator.get("printed_page"):
                text += f" (printed {locator['printed_page']})"
            return text
        return " › ".join(
            [*(locator.get("heading_path") or []), f"paragraph {locator.get('paragraph_index')}"]
        )

    @staticmethod
    def _rows(c, table: str, ids: list[str]) -> list[dict]:
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = c.execute(f"SELECT * FROM {table} WHERE id IN ({placeholders})", tuple(ids))
        order = {identifier: index for index, identifier in enumerate(ids)}
        return sorted((dict(r) for r in rows), key=lambda r: order[r["id"]])
