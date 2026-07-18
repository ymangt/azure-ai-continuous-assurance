# Official NIST OSCAL v1.2.2 JSON schema

`oscal_complete_schema.json` is the unmodified complete JSON schema published
by NIST as part of the OSCAL `v1.2.2` release.

- Release: <https://github.com/usnistgov/OSCAL/releases/tag/v1.2.2>
- Asset: <https://github.com/usnistgov/OSCAL/releases/download/v1.2.2/oscal_complete_schema.json>
- SHA-256: `484d09fb794155d25c3d017a461a47a8f07d8a4cc53e7bce2f5b3c025820a945`

The validator verifies this digest before using the bundled schema. NIST's
schema contains ECMA-262 Unicode property patterns such as `\p{L}`. The
repository validator therefore uses Python's `regex` package for the Draft 7
`pattern` keyword while retaining `jsonschema` for every other keyword.
