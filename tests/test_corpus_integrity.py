from __future__ import annotations

import json
import shutil
from copy import deepcopy
from pathlib import Path

import pytest

from aica.assistant.retrieval import (
    CorpusIntegrityError,
    PolicyIndex,
    load_verified_policy_corpus,
    verify_policy_corpus,
)

ROOT = Path(__file__).parents[1]
CORPUS = ROOT / "data" / "policy-corpus"


def _snapshot() -> tuple[bytes, dict[str, bytes]]:
    manifest = (CORPUS / "manifest.json").read_bytes()
    raw = json.loads(manifest)
    documents = {
        str(item["path"]): (CORPUS / str(item["path"])).read_bytes() for item in raw["documents"]
    }
    return manifest, documents


def test_checked_in_corpus_is_complete_and_integrity_bound() -> None:
    manifest, documents = _snapshot()
    sections, provenance = verify_policy_corpus(manifest, documents)
    index = PolicyIndex(sections, provenance=provenance)

    assert provenance.corpus_id == "northstar-synthetic-policy-corpus"
    assert provenance.document_count == 18
    assert len(provenance.manifest_sha256) == 64
    assert index.search("privileged access approval")[0]


def test_corpus_rejects_mutated_and_unmanifested_documents() -> None:
    manifest, documents = _snapshot()
    first = next(iter(documents))
    documents[first] += b"mutation"
    with pytest.raises(CorpusIntegrityError, match="size does not match"):
        verify_policy_corpus(manifest, documents)

    manifest, documents = _snapshot()
    documents["unreviewed.md"] = b"# unreviewed"
    with pytest.raises(CorpusIntegrityError, match="unmanifested"):
        verify_policy_corpus(manifest, documents)


def test_corpus_rejects_traversal_and_non_synthetic_classification() -> None:
    manifest, documents = _snapshot()
    raw = json.loads(manifest)
    traversal = deepcopy(raw)
    traversal["documents"][0]["path"] = "../outside.md"
    with pytest.raises(CorpusIntegrityError, match="unsafe corpus document path"):
        verify_policy_corpus(json.dumps(traversal).encode(), documents)

    non_synthetic = deepcopy(raw)
    non_synthetic["classification"] = "INTERNAL"
    with pytest.raises(CorpusIntegrityError, match="synthetic-only"):
        verify_policy_corpus(json.dumps(non_synthetic).encode(), documents)


def test_local_corpus_loader_rejects_byte_drift_and_exact_membership(tmp_path: Path) -> None:
    corpus = tmp_path / "policy-corpus"
    shutil.copytree(CORPUS, corpus)
    first = corpus / "POL-001-acceptable-use.md"
    first.write_bytes(first.read_bytes() + b"\nmutation")
    with pytest.raises(CorpusIntegrityError, match="size does not match"):
        load_verified_policy_corpus(corpus)

    shutil.rmtree(corpus)
    shutil.copytree(CORPUS, corpus)
    (corpus / "nested").mkdir()
    (corpus / "nested" / "unreviewed.md").write_text("# Unreviewed", encoding="utf-8")
    with pytest.raises(CorpusIntegrityError, match="unmanifested"):
        load_verified_policy_corpus(corpus)
