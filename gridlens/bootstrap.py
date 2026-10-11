"""Dependency assembly. No SDK calls, model downloads or sign-in on UI rerun."""

from dataclasses import dataclass

from gridlens.auth.credentials import FileCredentialStore
from gridlens.config import Settings
from gridlens.contracts import AnswerProvider, EmbeddingProvider, SearchProvider, VectorStore
from gridlens.db import Database
from gridlens.documents.fetch import DocumentFetcher
from gridlens.documents.snapshots import SnapshotService
from gridlens.providers.fakes import (
    FakeAnswerProvider,
    FakeDocumentFetcher,
    FakeEmbeddingProvider,
    FakeSearchProvider,
    FakeVectorStore,
)
from gridlens.providers.tavily import TavilySearchProvider
from gridlens.repositories.qa import QARepository
from gridlens.repositories.research import ResearchRepository
from gridlens.repositories.sources import SourceRepository
from gridlens.services.discovery import DiscoveryService
from gridlens.services.review import ReviewService


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
    snapshots: SnapshotService
    review: ReviewService


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
    # Constructing the fetcher opens no connection; capture runs only on a user action.
    fetcher = (
        FakeDocumentFetcher()
        if is_fixture
        else DocumentFetcher(
            max_bytes=settings.max_document_bytes,
            timeout_seconds=settings.fetch_timeout_seconds,
        )
    )
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
        snapshots=SnapshotService(
            db,
            source_repository,
            fetcher,
            settings.data_dir,
            max_pdf_pages=settings.max_pdf_pages,
            pdf_timeout_seconds=settings.fetch_timeout_seconds,
        ),
        review=ReviewService(db, source_repository, settings.data_dir),
    )
