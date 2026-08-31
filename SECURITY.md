# Security Policy

## Supported Version

MEMORIA is currently published as a public beta.

| Version | Supported |
| --- | --- |
| 0.2.x beta | Yes |
| Earlier development snapshots | No |

## Reporting a Vulnerability

Please do not disclose an unpatched security vulnerability in a public issue.

Use GitHub Private Vulnerability Reporting for security-sensitive reports.

For ordinary bugs, documentation issues, and non-sensitive feature requests, use GitHub Issues.

Do not include passwords, private keys, API keys, tokens, private memories, or other secrets in public reports.

## Security Principles

MEMORIA follows a local-first and user-sovereign model:

- no automatic durable-memory promotion
- explicit approval before durable memory
- no hidden private-data scanning
- no automatic upload of local memory
- fail-closed behavior on integrity uncertainty
- signed release verification

## Release Verification

Expected MEMORIA 0.2+ release signing fingerprint:

`2A43DDB1EB6CAE0E011D8C688F3BBFD776DF59A3`

Verify official release assets with:

`gpgv --keyring ./memoria-release-keyring.gpg SHA256SUMS.sig SHA256SUMS`
`sha256sum -c SHA256SUMS`

MEMORIA is currently a beta project and does not promise a fixed security response SLA.
