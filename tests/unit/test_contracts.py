import pytest
from pydantic import ValidationError

from gridlens.config import Settings
from gridlens.contracts import AnswerDraft, EmbeddingBatch, Locator, ReviewStatus


def insufficient():
    return {
        "evidence_status": "insufficient",
        "claims": [],
        "limitations": [],
        "missing_evidence": [
            {
                "reason_type": "no_evidence",
                "subquestion": "Test question",
                "needed_evidence": "Approved sources",
                "suggested_queries": ["test question"],
            }
        ],
    }


@pytest.mark.parametrize(
    "change",
    [
        {"chunk_overlap": 350},
        {"max_search_calls": -1},
        {"context_top_k": 11},
        {"mode": "invalid"},
        {"normalize_embeddings": False},
    ],
)
def test_invalid_settings_rejected(tmp_path, change):
    with pytest.raises(ValidationError):
        Settings(project_root=tmp_path, **change)


def test_storage_cannot_cross_modes(tmp_path):
    with pytest.raises(ValidationError):
        Settings(project_root=tmp_path, mode="fixture", data_dir=tmp_path / "data/live")
    with pytest.raises(ValidationError):
        Settings(project_root=tmp_path, mode="live", auth_dir=tmp_path / "auth")
    with pytest.raises(ValidationError):
        Settings(project_root=tmp_path, mode="fixture", auth_dir=tmp_path / "auth")
    fixture = Settings(project_root=tmp_path)
    live = Settings(project_root=tmp_path, mode="live")
    assert fixture.data_dir != live.data_dir
    assert not live.auth_dir.is_relative_to(tmp_path)


def test_dotenv_process_precedence_and_secret_repr(tmp_path):
    (tmp_path / ".env").write_text("APP_MODE=live\nTAVILY_API_KEY=synthetic-secret\n")
    settings = Settings.from_env(tmp_path, {"APP_MODE": "fixture"})
    assert settings.mode == "fixture"
    assert "synthetic-secret" not in repr(settings)
    assert "synthetic-secret" not in settings.model_dump_json()


def test_draft_cannot_bypass_claim_structure():
    draft = insufficient()
    assert AnswerDraft.model_validate(draft).evidence_status == "insufficient"
    for update in [
        {"evidence_status": "answered"},
        {"missing_evidence": []},
        {"url": "https://synthetic.example"},
    ]:
        with pytest.raises(ValidationError):
            AnswerDraft.model_validate({**draft, **update})


def test_claim_requires_nonempty_evidence():
    draft = insufficient()
    draft.update(
        evidence_status="partial",
        claims=[
            {
                "claim_id": "c1",
                "kind": "fact",
                "text": "Test claim",
                "evidence": [],
            }
        ],
    )
    with pytest.raises(ValidationError):
        AnswerDraft.model_validate(draft)


def test_locator_and_review_status_boundaries():
    with pytest.raises(ValidationError):
        Locator(kind="pdf")
    with pytest.raises(ValidationError):
        Locator(kind="html", paragraph_index=0)
    with pytest.raises(ValueError):
        ReviewStatus("automatic_approval")


@pytest.mark.parametrize("vectors", [[[1, 2, 3]], [[float("nan"), 1]], [[float("inf"), 1]], []])
def test_invalid_vectors(vectors):
    with pytest.raises(ValidationError):
        EmbeddingBatch(
            vectors=vectors,
            dimensions=2,
            model_id="fixture",
            revision="1",
            role="document",
            local_token_count=1,
            latency_ms=0,
        )
