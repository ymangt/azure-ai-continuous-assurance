"""Tamper-evident run manifests and ES256 signing adapters."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol

from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.keyvault.keys import KeyClient
from azure.keyvault.keys.crypto import CryptographyClient, SignatureAlgorithm
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    Prehashed,
    decode_dss_signature,
    encode_dss_signature,
)
from pydantic import Field, model_validator

from aica.domain.models import Sha256, StrictRecord
from aica.util.canonical import canonical_json_bytes, sha256_bytes, sha256_file


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class ManifestArtifact(StrictRecord):
    path: str
    media_type: str
    sha256: Sha256
    size_bytes: int = Field(ge=0)
    classification: str


class CadCostBreakdown(StrictRecord):
    """Per-run cost estimate in CAD, split across the four required envelopes."""

    currency: Literal["CAD"] = "CAD"
    model_estimate_cad: float = Field(ge=0, allow_inf_nan=False)
    compute_estimate_cad: float = Field(ge=0, allow_inf_nan=False)
    storage_estimate_cad: float = Field(ge=0, allow_inf_nan=False)
    telemetry_estimate_cad: float = Field(ge=0, allow_inf_nan=False)
    total_estimate_cad: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def total_matches_components(self) -> CadCostBreakdown:
        components = sum(
            (
                Decimal(str(self.model_estimate_cad)),
                Decimal(str(self.compute_estimate_cad)),
                Decimal(str(self.storage_estimate_cad)),
                Decimal(str(self.telemetry_estimate_cad)),
            ),
            start=Decimal(),
        )
        if components != Decimal(str(self.total_estimate_cad)):
            raise ValueError("cost total must equal model + compute + storage + telemetry")
        return self


class UnsignedManifest(StrictRecord):
    schema_version: Literal["1.1.0"] = "1.1.0"
    run_id: str
    generated_at: datetime
    git_commit: str
    collector_version: str
    evaluator_version: str
    artifacts: tuple[ManifestArtifact, ...]
    cost_estimate_cad: float = Field(ge=0)
    cost_breakdown: CadCostBreakdown

    @model_validator(mode="after")
    def cost_total_matches_breakdown(self) -> UnsignedManifest:
        if Decimal(str(self.cost_estimate_cad)) != Decimal(
            str(self.cost_breakdown.total_estimate_cad)
        ):
            raise ValueError("manifest cost estimate must equal cost breakdown total")
        return self


class SignedManifest(StrictRecord):
    manifest: UnsignedManifest
    manifest_sha256: Sha256
    algorithm: str = "ES256"
    signature: str
    public_jwk: dict[str, str]
    key_id: str
    key_fingerprint: Sha256


class Es256Signer(Protocol):
    @property
    def key_id(self) -> str: ...

    def public_jwk(self) -> dict[str, str]: ...

    def sign_digest(self, digest: bytes) -> bytes: ...


class LocalEs256Signer:
    """CI/local signer. Production uses a non-exportable Key Vault key."""

    def __init__(self, key_path: Path):
        self.path = key_path
        if key_path.exists():
            loaded = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
            if not isinstance(loaded, ec.EllipticCurvePrivateKey):
                raise TypeError("signing key must be an EC private key")
            self._key = loaded
        else:
            key_path.parent.mkdir(parents=True, exist_ok=True)
            self._key = ec.generate_private_key(ec.SECP256R1())
            pem = self._key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
            key_path.write_bytes(pem)
            key_path.chmod(0o600)

    @property
    def key_id(self) -> str:
        return f"local://{self.path.name}"

    def public_jwk(self) -> dict[str, str]:
        numbers = self._key.public_key().public_numbers()
        return {
            "kty": "EC",
            "crv": "P-256",
            "x": _b64url(numbers.x.to_bytes(32, "big")),
            "y": _b64url(numbers.y.to_bytes(32, "big")),
            "use": "sig",
            "alg": "ES256",
        }

    def sign_digest(self, digest: bytes) -> bytes:
        der = self._key.sign(digest, ec.ECDSA(Prehashed(hashes.SHA256())))
        r, s = decode_dss_signature(der)
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")


class KeyVaultEs256Signer:
    """Signs digests using an existing non-exportable Key Vault P-256 key."""

    def __init__(self, vault_url: str, key_name: str, *, managed_identity_client_id: str | None):
        credential = (
            ManagedIdentityCredential(client_id=managed_identity_client_id)
            if managed_identity_client_id
            else DefaultAzureCredential()
        )
        key = KeyClient(vault_url=vault_url, credential=credential).get_key(key_name)
        self._key = key
        self._crypto = CryptographyClient(key, credential)

    @property
    def key_id(self) -> str:
        if not self._key.id:
            raise RuntimeError("Key Vault key has no versioned identifier")
        return self._key.id

    def public_jwk(self) -> dict[str, str]:
        material = self._key.key
        x = getattr(material, "x", None)
        y = getattr(material, "y", None)
        if not x or not y:
            raise RuntimeError("Key Vault key has no P-256 public coordinates")
        return {
            "kty": "EC",
            "crv": "P-256",
            "x": _b64url(bytes(x)),
            "y": _b64url(bytes(y)),
            "use": "sig",
            "alg": "ES256",
        }

    def sign_digest(self, digest: bytes) -> bytes:
        result = self._crypto.sign(SignatureAlgorithm.es256, digest)
        return bytes(result.signature)


def key_fingerprint(jwk: dict[str, str]) -> str:
    thumbprint = {key: jwk[key] for key in ("crv", "kty", "x", "y")}
    return sha256_bytes(canonical_json_bytes(thumbprint))


def build_manifest(
    *,
    run_id: str,
    root: Path,
    paths: list[Path],
    git_commit: str,
    collector_version: str,
    evaluator_version: str,
    cost_estimate_cad: float,
    cost_breakdown: CadCostBreakdown,
    public: bool,
) -> UnsignedManifest:
    artifacts = []
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        artifacts.append(
            ManifestArtifact(
                path=relative,
                media_type="application/json" if path.suffix == ".json" else "text/html",
                sha256=sha256_file(path),
                size_bytes=path.stat().st_size,
                classification="PUBLIC" if public else "INTERNAL",
            )
        )
    return UnsignedManifest(
        run_id=run_id,
        generated_at=datetime.now(UTC),
        git_commit=git_commit,
        collector_version=collector_version,
        evaluator_version=evaluator_version,
        artifacts=tuple(artifacts),
        cost_estimate_cad=cost_estimate_cad,
        cost_breakdown=cost_breakdown,
    )


def sign_manifest(manifest: UnsignedManifest, signer: Es256Signer) -> SignedManifest:
    content = canonical_json_bytes(manifest)
    digest = bytes.fromhex(sha256_bytes(content))
    jwk = signer.public_jwk()
    return SignedManifest(
        manifest=manifest,
        manifest_sha256=digest.hex(),
        signature=_b64url(signer.sign_digest(digest)),
        public_jwk=jwk,
        key_id=signer.key_id,
        key_fingerprint=key_fingerprint(jwk),
    )


def verify_manifest_signature(signed: SignedManifest) -> list[str]:
    """Verify canonical manifest content and its embedded ES256 public signature."""

    errors: list[str] = []
    content = canonical_json_bytes(signed.manifest)
    digest = bytes.fromhex(sha256_bytes(content))
    if digest.hex() != signed.manifest_sha256:
        errors.append("manifest digest mismatch")

    jwk = signed.public_jwk
    if signed.algorithm != "ES256" or jwk.get("alg") != "ES256":
        errors.append("manifest signature algorithm is not ES256")
    if jwk.get("kty") != "EC" or jwk.get("crv") != "P-256":
        errors.append("manifest public key is not EC P-256")
    try:
        if key_fingerprint(jwk) != signed.key_fingerprint:
            errors.append("manifest key fingerprint does not match the embedded public key")
    except KeyError:
        errors.append("manifest public key is missing fingerprint material")
    try:
        public_numbers = ec.EllipticCurvePublicNumbers(
            int.from_bytes(_b64url_decode(jwk["x"]), "big"),
            int.from_bytes(_b64url_decode(jwk["y"]), "big"),
            ec.SECP256R1(),
        )
        public_key = public_numbers.public_key()
        raw_signature = _b64url_decode(signed.signature)
        if len(raw_signature) != 64:
            errors.append("ES256 signature is not 64-byte r||s format")
        else:
            der_signature = encode_dss_signature(
                int.from_bytes(raw_signature[:32], "big"),
                int.from_bytes(raw_signature[32:], "big"),
            )
            public_key.verify(der_signature, digest, ec.ECDSA(Prehashed(hashes.SHA256())))
    except (InvalidSignature, KeyError, ValueError) as exc:
        errors.append(f"manifest signature invalid: {exc}")

    return errors


def verify_manifest(signed: SignedManifest, root: Path) -> list[str]:
    """Verify manifest content, signature, and every artifact; return errors."""

    errors = verify_manifest_signature(signed)

    for artifact in signed.manifest.artifacts:
        path = (root / artifact.path).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError:
            errors.append(f"artifact escapes package root: {artifact.path}")
            continue
        if not path.is_file():
            errors.append(f"artifact missing: {artifact.path}")
        elif sha256_file(path) != artifact.sha256:
            errors.append(f"artifact digest mismatch: {artifact.path}")
    declared = {artifact.path for artifact in signed.manifest.artifacts}
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "run-manifest.json"
    }
    for extra in sorted(actual - declared):
        errors.append(f"unmanifested artifact present: {extra}")
    return errors


def load_signed_manifest(path: Path) -> SignedManifest:
    return SignedManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
