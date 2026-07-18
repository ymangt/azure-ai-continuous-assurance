"""Deterministic SQLite FTS5 retrieval over a synthetic policy corpus."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any, cast

from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.storage.blob import ContainerClient

from aica.assistant.contracts import Citation
from aica.domain.models import Classification

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{1,63}")
INJECTION_PATTERN = re.compile(
    r"(?i)(ignore\s+(?:all\s+)?(?:previous|prior)|system\s+prompt|developer\s+message|"
    r"override\s+(?:the\s+)?instructions|exfiltrat|reveal\s+(?:the\s+)?secret)"
)
DOCUMENT_METADATA_PATTERN = re.compile(r"^[-*]\s+([^:]+):\s*(.+)$")
MAX_CORPUS_DOCUMENTS = 25
MIN_CORPUS_DOCUMENTS = 15
MAX_DOCUMENT_BYTES = 128 * 1024
MAX_CORPUS_BYTES = 1024 * 1024


class CorpusIntegrityError(RuntimeError):
    """The policy corpus cannot be trusted or safely indexed."""


def _classification(value: str) -> Classification:
    normalized = value.split("(", 1)[0].strip().upper().replace(" ", "_")
    if normalized == "SYNTHETIC":
        normalized = "PUBLIC"
    return Classification(normalized)


@dataclass(frozen=True)
class PolicySection:
    document_id: str
    section_id: str
    title: str
    owner: str
    classification: Classification
    approval_requirement: str
    content: str


@dataclass(frozen=True)
class CorpusProvenance:
    corpus_id: str
    version: str
    manifest_sha256: str
    document_count: int


def _parse_markdown_text(text: str, fallback_id: str) -> list[PolicySection]:
    metadata: dict[str, str] = {}
    if text.startswith("---\n"):
        _, raw_metadata, text = text.split("---\n", 2)
        for line in raw_metadata.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip().strip('"')
    else:
        for line in text.splitlines()[:12]:
            match = DOCUMENT_METADATA_PATTERN.match(line.strip())
            if match:
                metadata[match.group(1).strip().casefold().replace(" ", "_")] = match.group(
                    2
                ).strip()
    document_id = metadata.get("id", metadata.get("policy_id", fallback_id))
    owner = metadata.get("owner", "Policy Governance")
    classification = _classification(metadata.get("classification", "INTERNAL"))
    approval = metadata.get("approval_requirement", "Policy owner approval required")
    sections: list[PolicySection] = []
    current_title = "Overview"
    body: list[str] = []
    section_number = 1
    for line in text.splitlines():
        if line.startswith("## "):
            if body:
                sections.append(
                    PolicySection(
                        document_id,
                        f"{document_id}-s{section_number:02d}",
                        current_title,
                        owner,
                        classification,
                        approval,
                        "\n".join(body).strip(),
                    )
                )
                section_number += 1
                body = []
            current_title = line[3:].strip()
        elif line.strip():
            body.append(line.strip())
    if body:
        sections.append(
            PolicySection(
                document_id,
                f"{document_id}-s{section_number:02d}",
                current_title,
                owner,
                classification,
                approval,
                "\n".join(body).strip(),
            )
        )
    return sections


def _parse_markdown(path: Path) -> list[PolicySection]:
    return _parse_markdown_text(path.read_text(encoding="utf-8"), path.stem)


def _parse_json_value(raw: dict[str, Any], fallback_id: str) -> list[PolicySection]:
    if "sections" not in raw and "content" not in raw:
        return []
    document_id = str(raw.get("id", fallback_id))
    title = str(raw.get("title", fallback_id.replace("-", " ").title()))
    owner = str(raw.get("owner", "Policy Governance"))
    classification = _classification(str(raw.get("classification", "INTERNAL")))
    approval = str(raw.get("approval_requirement", "Policy owner approval required"))
    raw_sections = raw.get("sections")
    if not raw_sections:
        raw_sections = [
            {"id": f"{document_id}-s01", "title": "Overview", "content": raw["content"]}
        ]
    return [
        PolicySection(
            document_id=document_id,
            section_id=str(section.get("id", f"{document_id}-s{index:02d}")),
            title=str(section.get("title", title)),
            owner=str(section.get("owner", owner)),
            classification=classification,
            approval_requirement=str(section.get("approval_requirement", approval)),
            content=str(section["content"]),
        )
        for index, section in enumerate(raw_sections, start=1)
    ]


def _parse_json(path: Path) -> list[PolicySection]:
    raw = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    return _parse_json_value(raw, path.stem)


def _safe_manifest_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.suffix.casefold() not in {".md", ".json"}
    ):
        raise CorpusIntegrityError(f"unsafe corpus document path: {value!r}")
    return path


def verify_policy_corpus(
    manifest_bytes: bytes,
    document_bytes: Mapping[str, bytes],
) -> tuple[list[PolicySection], CorpusProvenance]:
    """Verify a complete synthetic corpus snapshot before parsing any document."""

    if len(manifest_bytes) > MAX_DOCUMENT_BYTES:
        raise CorpusIntegrityError("corpus manifest exceeds the size limit")
    try:
        manifest = cast(dict[str, Any], json.loads(manifest_bytes.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise CorpusIntegrityError("corpus manifest is not valid UTF-8 JSON") from exc
    if str(manifest.get("classification", "")).casefold() != "synthetic":
        raise CorpusIntegrityError("corpus manifest is not synthetic-only")
    documents = manifest.get("documents")
    if not isinstance(documents, list):
        raise CorpusIntegrityError("corpus manifest documents must be a list")
    if not MIN_CORPUS_DOCUMENTS <= len(documents) <= MAX_CORPUS_DOCUMENTS:
        raise CorpusIntegrityError(
            f"corpus must contain {MIN_CORPUS_DOCUMENTS}-{MAX_CORPUS_DOCUMENTS} documents"
        )
    if manifest.get("active_document_count") != len(documents):
        raise CorpusIntegrityError("active document count does not match the manifest")

    expected_paths: set[str] = set()
    expected_ids: set[str] = set()
    sections: list[PolicySection] = []
    total_bytes = 0
    for raw_entry in documents:
        if not isinstance(raw_entry, dict):
            raise CorpusIntegrityError("corpus manifest document entry is not an object")
        entry = cast(dict[str, Any], raw_entry)
        document_id = str(entry.get("id", ""))
        path_value = str(entry.get("path", ""))
        path = _safe_manifest_path(path_value)
        if not document_id or document_id in expected_ids:
            raise CorpusIntegrityError(f"duplicate or empty corpus document ID: {document_id!r}")
        if path_value in expected_paths:
            raise CorpusIntegrityError(f"duplicate corpus path: {path_value}")
        expected_ids.add(document_id)
        expected_paths.add(path_value)

        classification_text = str(entry.get("classification", ""))
        if "synthetic" not in classification_text.casefold():
            raise CorpusIntegrityError(f"{document_id}: classification is not synthetic")
        try:
            expected_classification = _classification(classification_text)
        except ValueError as exc:
            raise CorpusIntegrityError(f"{document_id}: unsupported policy classification") from exc
        if expected_classification not in {Classification.PUBLIC, Classification.INTERNAL}:
            raise CorpusIntegrityError(f"{document_id}: classification is outside corpus policy")

        content = document_bytes.get(path_value)
        if content is None:
            raise CorpusIntegrityError(f"manifested corpus document is missing: {path_value}")
        expected_size = entry.get("size_bytes")
        if not isinstance(expected_size, int) or expected_size != len(content):
            raise CorpusIntegrityError(f"{path_value}: size does not match the manifest")
        if len(content) > MAX_DOCUMENT_BYTES:
            raise CorpusIntegrityError(f"{path_value}: document exceeds the size limit")
        total_bytes += len(content)
        if total_bytes > MAX_CORPUS_BYTES:
            raise CorpusIntegrityError("corpus exceeds the aggregate size limit")
        digest = str(entry.get("sha256", ""))
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or sha256(content).hexdigest() != digest:
            raise CorpusIntegrityError(f"{path_value}: digest does not match the manifest")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CorpusIntegrityError(f"{path_value}: document is not UTF-8") from exc
        if path.suffix.casefold() == ".md":
            parsed = _parse_markdown_text(text, path.stem)
        else:
            try:
                value = cast(dict[str, Any], json.loads(text))
            except (json.JSONDecodeError, TypeError) as exc:
                raise CorpusIntegrityError(f"{path_value}: invalid policy JSON") from exc
            parsed = _parse_json_value(value, path.stem)
        if not parsed or {item.document_id for item in parsed} != {document_id}:
            raise CorpusIntegrityError(
                f"{path_value}: parsed policy ID does not match the manifest"
            )
        if any(item.owner != str(entry.get("owner", "")) for item in parsed):
            raise CorpusIntegrityError(f"{path_value}: owner does not match the manifest")
        if any(item.classification != expected_classification for item in parsed):
            raise CorpusIntegrityError(f"{path_value}: classification does not match the manifest")
        sections.extend(parsed)

    extras = set(document_bytes) - expected_paths
    if extras:
        raise CorpusIntegrityError(f"unmanifested corpus blobs are forbidden: {sorted(extras)!r}")
    section_ids = [item.section_id for item in sections]
    if len(section_ids) != len(set(section_ids)):
        raise CorpusIntegrityError("corpus section IDs are not unique")
    provenance = CorpusProvenance(
        corpus_id=str(manifest.get("corpus_id", "")),
        version=str(manifest.get("version", "")),
        manifest_sha256=sha256(manifest_bytes).hexdigest(),
        document_count=len(documents),
    )
    if not provenance.corpus_id or not provenance.version:
        raise CorpusIntegrityError("corpus ID and version are required")
    return sections, provenance


def load_verified_policy_corpus(
    directory: Path,
) -> tuple[list[PolicySection], CorpusProvenance]:
    """Load one exact local corpus snapshot and verify every byte before parsing it."""

    if not directory.is_dir():
        raise CorpusIntegrityError(f"policy corpus directory is unavailable: {directory}")
    try:
        entries = sorted(
            (path for path in directory.rglob("*") if path.is_file() or path.is_symlink()),
            key=lambda path: path.relative_to(directory).as_posix(),
        )
    except OSError as exc:
        raise CorpusIntegrityError("cannot enumerate the local policy corpus") from exc
    if any(path.is_symlink() for path in entries):
        raise CorpusIntegrityError("symbolic links are forbidden in the local policy corpus")
    if len(entries) > MAX_CORPUS_DOCUMENTS + 1:
        raise CorpusIntegrityError("local corpus snapshot contains too many files")

    payloads: dict[str, bytes] = {}
    for path in entries:
        relative = path.relative_to(directory).as_posix()
        try:
            if path.stat().st_size > MAX_DOCUMENT_BYTES:
                raise CorpusIntegrityError(f"{relative}: file exceeds the size limit")
            payloads[relative] = path.read_bytes()
        except OSError as exc:
            raise CorpusIntegrityError(f"cannot read local corpus file: {relative}") from exc
    try:
        manifest = payloads.pop("manifest.json")
    except KeyError as exc:
        raise CorpusIntegrityError("local corpus manifest is missing") from exc
    return verify_policy_corpus(manifest, payloads)


class AzureBlobPolicyCorpusLoader:
    """Download one complete, integrity-bound corpus snapshot with managed identity."""

    def __init__(
        self,
        container_url: str,
        *,
        prefix: str = "",
        managed_identity_client_id: str | None,
    ):
        if not container_url.startswith("https://"):
            raise ValueError("production corpus container URL must use HTTPS")
        self.prefix = prefix.strip("/")
        self.credential = (
            ManagedIdentityCredential(client_id=managed_identity_client_id)
            if managed_identity_client_id
            else DefaultAzureCredential(exclude_interactive_browser_credential=True)
        )
        self.client = ContainerClient.from_container_url(
            container_url.rstrip("/"), credential=self.credential
        )

    def load(self) -> tuple[list[PolicySection], CorpusProvenance]:
        blob_prefix = f"{self.prefix}/" if self.prefix else ""
        try:
            names = sorted(
                str(item.name) for item in self.client.list_blobs(name_starts_with=blob_prefix)
            )
            if len(names) > MAX_CORPUS_DOCUMENTS + 1:
                raise CorpusIntegrityError("corpus container snapshot contains too many blobs")
            relative_names = [name.removeprefix(blob_prefix) for name in names]
            if "manifest.json" not in relative_names:
                raise CorpusIntegrityError("corpus manifest blob is missing")
            payloads: dict[str, bytes] = {}
            for name, relative in zip(names, relative_names, strict=True):
                if not relative or relative.startswith("/"):
                    raise CorpusIntegrityError(f"unsafe corpus blob name: {name!r}")
                content = bytes(self.client.download_blob(name).readall())
                if len(content) > MAX_DOCUMENT_BYTES:
                    raise CorpusIntegrityError(f"{relative}: blob exceeds the size limit")
                payloads[relative] = content
            manifest = payloads.pop("manifest.json")
            return verify_policy_corpus(manifest, payloads)
        finally:
            self.client.close()
            self.credential.close()


def load_corpus(directory: Path) -> list[PolicySection]:
    sections: list[PolicySection] = []
    if not directory.exists():
        return sections
    for path in sorted(directory.rglob("*")):
        if path.suffix.lower() == ".md":
            sections.extend(_parse_markdown(path))
        elif path.suffix.lower() == ".json":
            sections.extend(_parse_json(path))
    return sections


class PolicyIndex:
    def __init__(
        self,
        sections: list[PolicySection],
        *,
        provenance: CorpusProvenance | None = None,
    ):
        self.provenance = provenance
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """
            CREATE VIRTUAL TABLE policy_fts USING fts5(
              document_id UNINDEXED,
              section_id UNINDEXED,
              title,
              owner,
              classification UNINDEXED,
              approval_requirement,
              content,
              tokenize='unicode61 remove_diacritics 2'
            )
            """
        )
        self.connection.executemany(
            "INSERT INTO policy_fts VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    item.document_id,
                    item.section_id,
                    item.title,
                    item.owner,
                    item.classification.value,
                    item.approval_requirement,
                    item.content,
                )
                for item in sections
            ],
        )
        self.connection.commit()

    @classmethod
    def from_directory(cls, directory: Path) -> PolicyIndex:
        return cls(load_corpus(directory))

    @classmethod
    def from_verified_directory(cls, directory: Path) -> PolicyIndex:
        sections, provenance = load_verified_policy_corpus(directory)
        return cls(sections, provenance=provenance)

    @classmethod
    def from_blob(
        cls,
        container_url: str,
        *,
        prefix: str = "",
        managed_identity_client_id: str | None,
    ) -> PolicyIndex:
        sections, provenance = AzureBlobPolicyCorpusLoader(
            container_url,
            prefix=prefix,
            managed_identity_client_id=managed_identity_client_id,
        ).load()
        return cls(sections, provenance=provenance)

    def search(self, query: str, *, limit: int = 4) -> tuple[list[Citation], list[str]]:
        raw_terms = TOKEN_PATTERN.findall(query)[:12]
        terms: list[str] = []
        for term in raw_terms:
            candidates = [term]
            if len(term) > 3:
                candidates.extend([f"{term}s", f"{term}es"])
                if term.casefold().endswith("s"):
                    candidates.append(term[:-1])
            for candidate in candidates:
                if candidate not in terms:
                    terms.append(candidate)
        if not terms:
            return [], ["NO_SEARCHABLE_TERMS"]
        match_expression = " OR ".join(f'"{term}"' for term in terms)
        rows = self.connection.execute(
            """
            SELECT document_id, section_id, title, classification, content, bm25(policy_fts) AS rank
            FROM policy_fts
            WHERE policy_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (match_expression, limit * 2),
        ).fetchall()
        outcomes: list[str] = []
        citations: list[Citation] = []
        for row in rows:
            content = str(row["content"])
            if INJECTION_PATTERN.search(content):
                outcomes.append(f"INDIRECT_PROMPT_INJECTION_BLOCKED:{row['document_id']}")
                continue
            excerpt = content[:480] + ("…" if len(content) > 480 else "")
            citations.append(
                Citation(
                    document_id=row["document_id"],
                    section_id=row["section_id"],
                    title=row["title"],
                    excerpt=excerpt,
                    classification=Classification(row["classification"]),
                    score=round(abs(float(row["rank"])), 6),
                )
            )
            if len(citations) >= limit:
                break
        if not citations:
            outcomes.append("NO_TRUSTED_GROUNDING_FOUND")
        return citations, outcomes

    def lookup(self, document_id: str, section_id: str | None = None) -> dict[str, str] | None:
        query = "SELECT * FROM policy_fts WHERE document_id = ?"
        params: tuple[str, ...] = (document_id,)
        if section_id:
            query += " AND section_id = ?"
            params = (document_id, section_id)
        query += " LIMIT 1"
        row = self.connection.execute(query, params).fetchone()
        if row is None:
            return None
        return {
            "document_id": row["document_id"],
            "section_id": row["section_id"],
            "owner": row["owner"],
            "approval_requirement": row["approval_requirement"],
            "classification": row["classification"],
        }
