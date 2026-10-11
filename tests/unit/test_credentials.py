import json
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from gridlens.auth.credentials import FileCredentialStore
from gridlens.auth.host import get_or_create_host_id
from gridlens.contracts import CredentialRecord
from gridlens.errors import AppError


def record(client="issued-synthetic-1"):
    return CredentialRecord(
        subject="synthetic-subject",
        client_id=client,
        ext_agent_host_id="urn:uuid:fixture",
        label=f"Synthetic account {client}",
        email="same@synthetic.example",
        access_token="synthetic-access-secret",
        refresh_token="synthetic-refresh-secret",
        id_token="synthetic-id-secret",
        scopes=["chatgpt.tokens.use.direct"],
        expires_at=9999999999,
        saved_at="test",
    )


def test_stable_host_concurrent_creation(tmp_path):
    directory = tmp_path / "credentials"
    with ThreadPoolExecutor(max_workers=4) as pool:
        identifiers = list(pool.map(lambda _: get_or_create_host_id(directory), range(8)))
    assert len(set(identifiers)) == 1
    assert get_or_create_host_id(directory) == identifiers[0]
    assert directory.stat().st_mode & 0o777 == 0o700
    assert (directory / "host.json").stat().st_mode & 0o777 == 0o600


def test_account_isolation_and_safe_repr(tmp_path):
    store = FileCredentialStore(tmp_path / "credentials")
    assert not store.directory.exists()
    a = store.save(record())
    b = store.save(record("issued-synthetic-2"))
    assert a != b
    assert len(store.summaries()) == 2
    assert store.load(a).access_token.get_secret_value() == "synthetic-access-secret"
    assert "synthetic-access-secret" not in repr(store.load(a))
    assert "synthetic-access-secret" not in json.dumps([r.model_dump() for r in store.summaries()])
    store.clear_tokens(a)
    assert store.load(a).access_token is None
    assert store.load(a).client_id == "issued-synthetic-1"
    assert store.load(b).access_token is not None
    assert (store.directory / f"{a}.json").stat().st_mode & 0o777 == 0o600


def test_atomic_write_failure_keeps_old_record(tmp_path, monkeypatch):
    store = FileCredentialStore(tmp_path / "credentials")
    a = store.save(record())

    def fail(*args):
        raise OSError("Synthetic replacement failure")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        store.save(record().model_copy(update={"label": "new label"}))
    assert store.load(a).label == record().label
    assert not list(store.directory.glob(".write-*"))


def test_reader_never_sees_partial_record(tmp_path):
    store = FileCredentialStore(tmp_path / "credentials")
    a = store.save(record())

    def writer():
        for i in range(30):
            store.save(record().model_copy(update={"label": f"Label {i}"}))

    with ThreadPoolExecutor(max_workers=2) as pool:
        writing = pool.submit(writer)
        for _ in range(30):
            assert store.load(a).subject == "synthetic-subject"
        writing.result()


def test_path_permissions_and_mismatched_identity(tmp_path):
    store = FileCredentialStore(tmp_path / "credentials")
    with pytest.raises(AppError):
        store.load("../../outside")
    a = store.save(record())
    path = store.directory / f"{a}.json"
    path.chmod(0o644)
    with pytest.raises(AppError) as e:
        store.load(a)
    assert e.value.code == "CREDENTIAL_STORAGE_UNSAFE"
    path.chmod(0o600)
    value = json.loads(path.read_text())
    value["subject"] = "wrong-subject"
    path.write_text(json.dumps(value))
    with pytest.raises(AppError) as e:
        store.load(a)
    assert e.value.code == "CREDENTIAL_STORAGE_INVALID"
