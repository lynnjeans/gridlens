"""Dependency assembly. No SDK calls, model downloads or sign-in on UI rerun."""

from dataclasses import dataclass

from gridlens.auth.credentials import FileCredentialStore
from gridlens.config import Settings
from gridlens.contracts import AnswerProvider, EmbeddingProvider, SearchProvider, VectorStore
from gridlens.db import Database
from gridlens.providers.fakes import (
    FakeAnswerProvider,
    FakeEmbeddingProvider,
    FakeSearchProvider,
    FakeVectorStore,
)
from gridlens.providers.tavily import TavilySearchProvider
from gridlens.repositories.qa import QARepository
from gridlens.repositories.research import ResearchRepository
from gridlens.repositories.sources import SourceRepository
from gridlens.services.discovery import DiscoveryService


@dataclass
class Container:
    settings: Settings
    db: Database
    sources: SourceRepository
    research: ResearchRepository
    qa: QARepository
    credentials: FileCredentialStore
    search: SearchProvider | None
    embeddings: EmbeddingProvider | None
    answers: AnswerProvider | None
    vectors: VectorStore | None
    discovery: DiscoveryService


def build_container(settings: Settings) -> Container:
    db = Database(settings.data_dir / "research.sqlite3")
    db.initialize()
    is_fixture = settings.mode == "fixture"
    source_repository = SourceRepository(db)
    search: SearchProvider | None
    if is_fixture:
        search = FakeSearchProvider()
    elif settings.tavily_api_key.get_secret_value():
        search = TavilySearchProvider(
            settings.tavily_api_key, timeout_seconds=settings.fetch_timeout_seconds
        )
    else:
        search = None
    return Container(
        settings=settings,
        db=db,
        sources=source_repository,
        research=ResearchRepository(db),
        qa=QARepository(db),
        credentials=FileCredentialStore(settings.auth_dir),
        search=search,
        embeddings=FakeEmbeddingProvider() if is_fixture else None,
        answers=FakeAnswerProvider() if is_fixture else None,
        vectors=FakeVectorStore() if is_fixture else None,
        discovery=DiscoveryService(
            db=db,
            sources=source_repository,
            provider=search,
            mode=settings.mode,
            max_calls=settings.max_search_calls,
            max_results=settings.max_search_results,
        ),
    )
