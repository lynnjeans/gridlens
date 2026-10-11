"""AnswerDraft generation through ChatGPT plan usage (official Responses route).

Per the Sign in with ChatGPT models-and-inference, preview-limitations and
errors-and-recovery pages (checked 2026-10-12): `POST /v1/responses` with the selected
account's OAuth token, `store=false`, `stream=true`, `input` array, `instructions`, and none
of the unsupported fields. Only a stream that ends in `response.completed` and parses into a
strict AnswerDraft is returned; anything else raises. Raw httpx: no hidden SDK retries.
"""

import json
import time
from dataclasses import dataclass, field
from importlib.resources import files
from typing import Literal

import httpx
from pydantic import ValidationError

from gridlens.auth.sessions import SessionHandle, SessionManager
from gridlens.contracts import AnswerDraft, RetrievalContext
from gridlens.errors import AppError

RESPONSES_URL = "https://api.openai.com/v1/responses"
PROMPT_VERSION = "answer_v1"
MAX_STREAM_BYTES = 2_000_000
# The only top-level fields this route ever receives (preview limitations whitelist).
ALLOWED_FIELDS = frozenset({"model", "instructions", "input", "store", "stream", "text"})
OutputMode = Literal["schema", "prompt_json_validated"]

_ITEM_STRING = {"type": "string"}
ANSWER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["evidence_status", "claims", "limitations", "missing_evidence"],
    "properties": {
        "evidence_status": {"type": "string", "enum": ["answered", "partial", "insufficient"]},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["claim_id", "kind", "text", "evidence"],
                "properties": {
                    "claim_id": _ITEM_STRING,
                    "kind": {"type": "string", "enum": ["fact", "inference"]},
                    "text": _ITEM_STRING,
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["chunk_id", "support_quote"],
                            "properties": {"chunk_id": _ITEM_STRING, "support_quote": _ITEM_STRING},
                        },
                    },
                },
            },
        },
        "limitations": {"type": "array", "items": _ITEM_STRING},
        "missing_evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["reason_type", "subquestion", "needed_evidence", "suggested_queries"],
                "properties": {
                    "reason_type": {
                        "type": "string",
                        "enum": [
                            "no_evidence",
                            "partial_coverage",
                            "jurisdiction_mismatch",
                            "freshness_unverified",
                            "conflicting_evidence",
                            "needs_external_validation",
                        ],
                    },
                    "subquestion": _ITEM_STRING,
                    "needed_evidence": _ITEM_STRING,
                    "suggested_queries": {"type": "array", "items": _ITEM_STRING},
                },
            },
        },
    },
}

# Errors that can arrive before or after the stream opens (errors-and-recovery page).
FAILURE_CODES = {
    "subscription_sharing_usage_limit_exceeded": "USAGE_LIMITED",
    "subscription_sharing_usage_unavailable": "USAGE_LIMITED",
    "subscription_sharing_user_not_eligible": "PLAN_PERMISSION_MISSING",
    "chatpass_v2_scope_not_authorized": "PLAN_PERMISSION_MISSING",
    "chatpass_v2_invalid_authorization_context": "PLAN_PERMISSION_MISSING",
    "subscription_sharing_invalid_user": "AUTH_EXPIRED",
    "model_not_found": "MODEL_UNAVAILABLE",
}


def load_prompt() -> str:
    return files("gridlens").joinpath(f"prompts/{PROMPT_VERSION}.txt").read_text("utf-8")


@dataclass
class GenerationRecord:
    """Redacted facts about the last call, for QA records (never the token)."""

    registration_ref: str
    requested_model: str
    output_mode: OutputMode
    prompt_version: str = PROMPT_VERSION
    model: str | None = None
    request_id: str | None = None
    terminal_event: str | None = None
    usage: dict = field(default_factory=dict)
    latency_ms: int = 0


class ChatGPTAnswerProvider:
    def __init__(
        self,
        sessions: SessionManager,
        handle: SessionHandle,
        model_slug: str,
        *,
        output_mode: Literal["auto", "schema", "prompt_json_validated"] = "auto",
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 60,
        clock=time.monotonic,
    ):
        if not model_slug:
            raise AppError("MODEL_UNAVAILABLE", "Choose a model from your account first.")
        self.sessions = sessions
        self.handle = handle
        self.model_slug = model_slug
        self.output_mode = output_mode
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.clock = clock
        self.last: GenerationRecord | None = None

    def generate(
        self, question: str, context: RetrievalContext, repair: str | None = None
    ) -> AnswerDraft:
        if not self.sessions.plan_usage_enabled(self.handle):
            raise AppError("PLAN_PERMISSION_MISSING", "ChatGPT plan usage is not authorized.")
        token = self.sessions.access_token(self.handle)  # raises if account changed/expired
        mode: OutputMode = (
            "prompt_json_validated" if self.output_mode == "prompt_json_validated" else "schema"
        )
        try:
            return self._call(token, question, context, mode, repair)
        except _SchemaUnsupported:
            if self.output_mode != "auto":
                raise AppError(
                    "OUTPUT_MODE_UNSUPPORTED", "The model rejected structured output."
                ) from None
            # Rejected before any stream opened; retry once with prompt-JSON + strict checks.
            return self._call(token, question, context, "prompt_json_validated", repair)

    def build_request(
        self,
        question: str,
        context: RetrievalContext,
        mode: OutputMode,
        repair: str | None = None,
    ) -> dict:
        evidence = [
            {
                "chunk_id": chunk.chunk_id,
                "section": " > ".join(chunk.heading_path) or None,
                "text": chunk.text,
            }
            for chunk in context.chunks
        ]
        # Evidence travels as a JSON value inside the user message: data, not instructions.
        payload = json.dumps({"question": question, "evidence": evidence}, ensure_ascii=False)
        content = [{"type": "input_text", "text": payload}]
        if repair:
            # One repair attempt: say why the previous draft was rejected, nothing else.
            content.append(
                {
                    "type": "input_text",
                    "text": "Your previous output was rejected: "
                    + repair
                    + " Return a corrected AnswerDraft using only the evidence above.",
                }
            )
        body = {
            "model": self.model_slug,
            "instructions": load_prompt(),
            "input": [{"role": "user", "content": content}],
            "store": False,
            "stream": True,
        }
        if mode == "schema":
            body["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "answer_draft",
                    "schema": ANSWER_SCHEMA,
                    "strict": True,
                }
            }
        if not set(body) <= ALLOWED_FIELDS:
            raise RuntimeError("Request contains a field this route does not support")
        return body

    def _call(self, token, question, context, mode: OutputMode, repair=None) -> AnswerDraft:
        record = GenerationRecord(
            registration_ref=self.handle.registration_id[:12],
            requested_model=self.model_slug,
            output_mode=mode,
        )
        self.last = record
        started = self.clock()
        body = self.build_request(question, context, mode, repair)
        try:
            with httpx.Client(timeout=self.timeout_seconds, transport=self.transport) as client:
                with client.stream(
                    "POST",
                    RESPONSES_URL,
                    json=body,
                    headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
                ) as response:
                    record.request_id = response.headers.get("x-request-id")
                    if response.status_code != 200:
                        response.read()
                        raise _http_error(response, mode)
                    text = self._consume(response, record)
        except httpx.TimeoutException:
            raise AppError(
                "PROVIDER_TIMEOUT", "The answer took too long.", retryable=True
            ) from None
        except httpx.HTTPError:
            # A broken stream may already have used plan usage; it is never a success.
            raise AppError("STREAM_INCOMPLETE", "The answer stream was interrupted.") from None
        finally:
            record.latency_ms = int((self.clock() - started) * 1000)
        try:
            return AnswerDraft.model_validate(json.loads(text))
        except (ValueError, ValidationError):
            raise AppError(
                "OUTPUT_INVALID", "The answer did not match the required format."
            ) from None

    def _consume(self, response: httpx.Response, record: GenerationRecord) -> str:
        chunks: list[str] = []
        size = 0
        event_name, data_lines = None, []
        for line in response.iter_lines():
            size += len(line) + 1
            if size > MAX_STREAM_BYTES:
                raise AppError("GENERATION_TOO_LARGE", "The answer exceeded the size limit.")
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
            elif line == "" and data_lines:
                data = "\n".join(data_lines)
                data_lines = []
                if data == "[DONE]":
                    continue
                try:
                    event = json.loads(data)
                except ValueError:
                    raise AppError(
                        "STREAM_INCOMPLETE", "The answer stream was malformed."
                    ) from None
                kind = event.get("type") or event_name
                if kind == "response.output_text.delta":
                    chunks.append(str(event.get("delta", "")))
                elif kind == "response.completed":
                    record.terminal_event = kind
                    final = event.get("response") or {}
                    record.model = final.get("model")
                    record.usage = final.get("usage") or {}
                    return _final_text(final) or "".join(chunks)
                elif kind in {"response.failed", "error"}:
                    record.terminal_event = kind
                    error = (event.get("response") or {}).get("error") or event.get("error") or {}
                    code = error.get("code") if isinstance(error, dict) else None
                    raise AppError(
                        FAILURE_CODES.get(code, "GENERATION_FAILED"),
                        "ChatGPT could not complete the answer.",
                    )
                elif kind == "response.incomplete":
                    record.terminal_event = kind
                    raise AppError("STREAM_INCOMPLETE", "The answer was incomplete.")
                event_name = None
        raise AppError("STREAM_INCOMPLETE", "The answer stream ended before completion.")


class _SchemaUnsupported(Exception):
    pass


def _http_error(response: httpx.Response, mode: OutputMode) -> Exception:
    try:
        error = response.json().get("error") or {}
    except (ValueError, AttributeError):
        error = {}
    code = error.get("code") if isinstance(error, dict) else None
    param = str(error.get("param") or "") if isinstance(error, dict) else ""
    if response.status_code == 400 and mode == "schema" and param.startswith("text"):
        return _SchemaUnsupported()
    if code in FAILURE_CODES:
        return AppError(FAILURE_CODES[code], "ChatGPT could not answer with this account.")
    if response.status_code == 401:
        return AppError("AUTH_EXPIRED", "ChatGPT did not accept this session. Sign in again.")
    if response.status_code == 403:
        return AppError("PLAN_PERMISSION_MISSING", "This account cannot use ChatGPT plan here.")
    if response.status_code == 404:
        return AppError("MODEL_UNAVAILABLE", "The selected model is not available.")
    if response.status_code == 429:
        return AppError("USAGE_LIMITED", "The ChatGPT plan usage limit was reached.")
    if response.status_code >= 500:
        return AppError(
            "PROVIDER_UNAVAILABLE", "ChatGPT is temporarily unavailable.", retryable=True
        )
    return AppError("GENERATION_FAILED", "ChatGPT rejected the answer request.")


def _final_text(response: dict) -> str:
    parts = []
    for item in response.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and content.get("type") == "output_text":
                parts.append(str(content.get("text", "")))
    return "".join(parts)
