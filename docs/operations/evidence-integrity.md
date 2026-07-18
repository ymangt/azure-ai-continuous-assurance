# Evidence integrity and verification

Each run retains raw private, normalized private, sanitized derived, OSCAL, and human-readable layers. Each artifact receives SHA-256 and a media type. The canonical run manifest lists paths, sizes, and digests plus model, compute, storage, telemetry, and total estimated CAD cost. The manifest model rejects a total inconsistent with those four components. A P-256 key signs the manifest digest with ES256 and records the exact key version and public JWK thumbprint.

Offline verification must:

1. parse and schema-validate the manifest;
2. canonicalize the unsigned manifest using the project contract;
3. recompute its SHA-256;
4. verify the raw `r||s` ES256 signature against the recorded public JWK;
5. recompute each artifact digest and reject missing, extra, or mutated files;
6. report key ID, thumbprint, and verification status without claiming WORM immutability.

The package also contains the strict system record loaded from `config/system-record.json`. Contract validation proves that the checked-in source and generated `schemas/system-record.schema.json` remain in parity with the Pydantic runtime model; the signed package digest binds the selected record to the assessment.

Checked-in sample signatures, if present, use a clearly labeled local CI key (`local://...`). Only a deployed run may identify a Key Vault key, and only after Azure MCP verification of the key version and signature operation.

Live Azure diagnostic evidence records an applicability outcome for every queried Resource Graph item. `APPLICABLE` requires a successful diagnostic-settings response and is evaluated for an enabled workspace destination; `NOT_APPLICABLE` is accepted only for Azure's explicit `ResourceTypeNotSupported` error; every other 404, authorization failure, malformed response, or transport failure remains `UNKNOWN`/collection error and cannot pass.

Live application-authorization evidence performs two GET requests to the same configured read-only API route: no bearer token must return 401, and the collector managed identity's token for the API audience must authenticate but fail the Easy Auth application allowlist with 403. Response bodies and bearer tokens are discarded before evidence normalization.
