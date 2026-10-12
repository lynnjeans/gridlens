"""Dependency assembly. No SDK calls, model downloads or sign-in on UI rerun."""

from dataclasses import dataclass

from gridlens.auth.catalog import ModelCatalog
from gridlens.auth.credentials import FileCredentialStore
from gridlens.auth.oauth import OAuthLogin
from gridlens.auth.sessions import SessionManager
from gridlens.config import Settings
from gridlens.contracts import AnswerProvider, EmbeddingProvider, SearchProvider, VectorStore
from gridlens.db import Database
from gridlens.documents.chunking import index_fingerprint
from gridlens.documents.fetch import DocumentFetcher
from gridlens.documents.snapshots import SnapshotService
from gridlens.errors import AppError
from gridlens.oplog import OperationLog
from gridlens.providers.chroma_store import ChromaVectorStore
from gridlens.providers.fakes import (
    FakeAnswerProvider,
    FakeDocumentFetcher,
    FakeEmbeddingProvider,
    FakeSearchProvider,
    FakeTokenizer,
)
from gridlens.providers.local_embeddings import LocalEmbeddingProvider, read_manifest
from gridlens.providers.serpapi import SerpApiSearchProvider
from gridlens.providers.tavily import TavilySearchProvider
from gridlens.repositories.qa import QARepository
from gridlens.repositories.research import ResearchRepository
from gridlens.repositories.sources import SourceRepository
from gridlens.runlocks import RunLocks
from gridlens.services.answers import AnswerService
from gridlens.services.discovery import DiscoveryService
from gridlens.services.export import ExportService
from gridlens.services.gaps import GapService
from gridlens.services.ingestion import IngestionService
from gridlens.services.recovery import RecoveryService
from gridlens.services.retrieval import RetrievalService
from gridlens.services.review import ReviewService


@dataclass
class Container:
    settings: Settings
    db: Database
    sources: SourceRepository
    research: ResearchRepository
    qa: QARepository
    credentials: FileCredentialStore
    oauth: OAuthLogin
    sessions: SessionManager
    catalog: ModelCatalog
    search: SearchProvider | None
    embeddings: EmbeddingProvider | None
    answers: AnswerProvider | None
    vectors: VectorStore | None
    discovery: DiscoveryService
    snapshots: SnapshotService
    review: ReviewService
    ingestion: IngestionService | None
    retrieval: RetrievalService | None
    answer_service: AnswerService | None
    gaps: GapService
    export: ExportService
    recovery: RecoveryService


def build_container(settings: Settings) -> Container:
    db = Database(settings.data_dir / "research.sqlite3")
    db.initialize()
    is_fixture = settings.mode == "fixture"
    source_repository = SourceRepository(db)
    search: SearchProvider | None
    if is_fixture:
        search = FakeSearchProvider()
    elif settings.search_api_key.get_secret_value():
        provider_class = (
            SerpApiSearchProvider if settings.search_provider == "serpapi" else TavilySearchProvider
        )
        search = provider_class(
            settings.search_api_key, timeout_seconds=settings.fetch_timeout_seconds
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
    review = ReviewService(db, source_repository, settings.data_dir)
    # Lock files and operation logs live in the per-mode data directory, never in Git.
    locks = RunLocks(settings.data_dir / "locks")
    oplog = OperationLog(settings.data_dir / "logs" / "operations.jsonl")
    embeddings, vectors, ingestion = _indexing(settings, db, review, locks, oplog)
    research = ResearchRepository(db)
    gaps = GapService(db)
    retrieval = (
        RetrievalService(
            research,
            embeddings=embeddings,
            vectors=vectors,
            index_fingerprint=ingestion.fingerprint,
            top_k=settings.retrieval_top_k,
            context_k=settings.context_top_k,
            max_context_tokens=settings.max_context_tokens,
        )
        if ingestion
        else None
    )
    credentials = FileCredentialStore(settings.auth_dir)
    sessions = SessionManager(credentials)
    return Container(
        settings=settings,
        db=db,
        sources=source_repository,
        research=research,
        qa=QARepository(db),
        credentials=credentials,
        # Constructed only; nothing contacts ChatGPT until the user acts in live mode.
        oauth=OAuthLogin(credentials),
        sessions=sessions,
        catalog=ModelCatalog(sessions),
        search=search,
        embeddings=embeddings,
        answers=FakeAnswerProvider() if is_fixture else None,
        vectors=vectors,
        discovery=DiscoveryService(
            db=db,
            sources=source_repository,
            provider=search,
            provider_name=settings.search_provider,
            mode=settings.mode,
            max_calls=settings.max_search_calls,
            max_results=settings.max_search_results,
            locks=locks,
            oplog=oplog,
        ),
        snapshots=SnapshotService(
            db,
            source_repository,
            fetcher,
            settings.data_dir,
            max_pdf_pages=settings.max_pdf_pages,
            pdf_timeout_seconds=settings.fetch_timeout_seconds,
        ),
        review=review,
        ingestion=ingestion,
        retrieval=retrieval,
        gaps=gaps,
        recovery=RecoveryService(db, locks),
        export=ExportService(
            db, mode=settings.mode, index_fingerprint=ingestion.fingerprint if ingestion else None
        ),
        answer_service=(
            AnswerService(
                db,
                research,
                retrieval,
                mode=settings.mode,
                max_attempts=settings.max_generation_attempts,
                gap_writer=gaps.write,
                oplog=oplog,
            )
            if retrieval
            else None
        ),
    )


def _indexing(
    settings: Settings,
    db: Database,
    review: ReviewService,
    locks: RunLocks,
    oplog: OperationLog,
):
    """Builds lazy indexing parts; nothing loads a model or opens Chroma here."""
    if settings.mode == "fixture":
        embeddings = FakeEmbeddingProvider()
        tokenizer = FakeTokenizer()
        identity, dimensions, max_input = embeddings.identity(), 16, 512
    else:
        try:
            manifest = read_manifest(settings)
        except AppError:
            # Live indexing stays unavailable until `gridlens prepare-model` has run.
            return None, None, None
        embeddings = tokenizer = LocalEmbeddingProvider(settings)
        identity = embeddings.identity()
        dimensions, max_input = settings.embedding_dimensions, manifest.max_seq_length
    fingerprint = index_fingerprint(identity, settings.chunk_tokens, settings.chunk_overlap)
    # Persistent per-mode index, so fixture and live vectors never share a collection.
    vectors = ChromaVectorStore(settings.data_dir / "chroma", fingerprint, dimensions)
    ingestion = IngestionService(
        db,
        review,
        embeddings=embeddings,
        tokenizer=tokenizer,
        vectors=vectors,
        embedding_identity=identity,
        dimensions=dimensions,
        chunk_tokens=settings.chunk_tokens,
        chunk_overlap=settings.chunk_overlap,
        max_input_tokens=max_input,
        locks=locks,
        oplog=oplog,
    )
    return embeddings, vectors, ingestion
