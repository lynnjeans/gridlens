"""Validated configuration and strictly separated fixture/live data roots."""

import os
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from gridlens.errors import AppError

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_root: Path = PROJECT_ROOT
    mode: Literal["fixture", "live"] = "fixture"
    data_dir: Path | None = None
    auth_dir: Path | None = None
    local_model_dir: Path | None = None
    tavily_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    chatgpt_model_slug: str = ""
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_revision: str = ""
    embedding_dimensions: int = Field(default=384, gt=0)
    embedding_device: Literal["cpu"] = "cpu"
    normalize_embeddings: Literal[True] = True
    chunk_tokens: int = Field(default=350, gt=0, le=510)
    chunk_overlap: int = Field(default=50, ge=0)
    max_search_calls: int = Field(default=3, ge=1, le=3)
    max_search_results: int = Field(default=10, ge=1, le=10)
    max_document_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    max_pdf_pages: int = Field(default=200, gt=0)
    retrieval_top_k: int = Field(default=10, gt=0)
    context_top_k: int = Field(default=5, gt=0, le=5)
    max_context_tokens: int = Field(default=4000, gt=0)
    max_generation_attempts: int = Field(default=2, ge=1, le=2)
    fetch_timeout_seconds: int = Field(default=20, gt=0)
    model_timeout_seconds: int = Field(default=60, gt=0)

    @model_validator(mode="after")
    def boundaries(self):
        if self.chunk_overlap >= self.chunk_tokens:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_TOKENS")
        if self.context_top_k > self.retrieval_top_k:
            raise ValueError("CONTEXT_TOP_K must not exceed RETRIEVAL_TOP_K")
        root = self.project_root.resolve()
        mode_root = (root / "data" / self.mode).resolve()
        data = self.data_dir.resolve() if self.data_dir else mode_root
        if not data.is_relative_to(mode_root):
            raise ValueError("DATA_DIR must remain inside data/{APP_MODE}")
        auth = self.auth_dir or (
            root / "data" / "fixture" / "auth"
            if self.mode == "fixture"
            else Path.home() / ".config" / "gridlens"
        )
        if self.mode == "live" and auth.resolve().is_relative_to(root):
            raise ValueError("Live AUTH_DIR must be outside the application repository")
        if self.mode == "fixture" and not auth.resolve().is_relative_to(mode_root):
            raise ValueError("Fixture AUTH_DIR must remain inside data/fixture")
        object.__setattr__(self, "project_root", root)
        object.__setattr__(self, "data_dir", data)
        object.__setattr__(self, "auth_dir", auth.resolve())
        model_dir = self.local_model_dir or root / "models"
        object.__setattr__(self, "local_model_dir", model_dir.resolve())
        return self

    @classmethod
    def from_env(cls, project_root: Path = PROJECT_ROOT, environ: dict | None = None):
        # .env values never override explicit process configuration.
        env = {
            **dotenv_values(project_root / ".env"),
            **(os.environ if environ is None else environ),
        }
        values: dict = {"project_root": project_root}
        for name in cls.model_fields:
            if name in {"project_root", "mode"}:
                continue
            value = env.get(name.upper())
            if value is not None and str(value).strip():
                values[name] = (
                    value if name != "normalize_embeddings" else str(value).lower() == "true"
                )
        values["mode"] = env.get("APP_MODE", "fixture")
        for name in ("data_dir", "auth_dir", "local_model_dir"):
            if name in values:
                path = Path(values[name]).expanduser()
                values[name] = path if path.is_absolute() else project_root / path
        return cls(**values)

    def require_search(self) -> None:
        if self.mode == "live" and not self.tavily_api_key.get_secret_value():
            raise AppError("CONFIG_MISSING", "Add your search key to the local .env file.")
