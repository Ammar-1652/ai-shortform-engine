# ADR 0085: Audited Envato portal download bridge

## Status

Accepted for explicitly allowed campaigns. External publishing and the
Antoine campaign's outside-media prohibition remain unchanged.

## Context

The official Envato MCP is a catalog search service. It returns item metadata
and public item pages, not downloadable bytes or license evidence. The
operator's MyToolsPlan subscription bridge exposes a short-lived authenticated
session for the same account. Treating an item-page slug as a download URL, or
storing a signed URL, would make provenance and retry behavior unsafe.

## Decision

`clipforge assets envato fetch` performs one audited, local operation:

1. Load the portal login only from the Linux Secret Service credential created
   by `assets envato auth setup`.
2. Authenticate to the portal, obtain its short-lived bridge domain/session,
   and keep the token and cookie in memory only.
3. Resolve the MCP item page through the portal to obtain its canonical item
   UUID and type. An optional `--portal-item-uuid` is only an assertion and
   fails if it disagrees; a URL slug is never guessed or converted locally.
4. Create a named Envato project license, download the signed item archive and
   certificate through the portal data routes, and reject non-HTTPS,
   non-allowlisted hosts, oversized responses, pending certificates, and
   malformed PDFs.
5. Extract one deterministic preferred media member (for example WAV before
   MP3) with path, symlink, size, and ambiguity checks. The media and certificate are passed to the existing
   hash, ffprobe, rights, provenance, policy, database-job, and promotion
   gates. A verified registration records
   `download_status: portal_download_verified`.

Signed download URLs, bridge tokens, cookies, credentials, and raw portal
responses are never persisted or printed. The downloaded archive stays under
the gitignored work root for retry/audit; generated media, licenses, and
databases are never committed.

The bridge supports the existing request media kinds with explicit mappings:
audio → `music`, video → `video`, image → `photo`, and graphic → `graphics`.
Unsupported kinds fail closed. Rights are not inferred from the MCP result; the
returned certificate is required before registration. Campaign policy is
checked before login and again by registration, so Antoine outside media stays
blocked.

## Consequences

- A clean operator can search with the MCP and fetch/register a selected item
  without manually copying a URL or license file.
- Catalog item identity remains an explicit human-confirmed binding when the
  provider omits a stable UUID.
- A stale portal session is recoverable by rerunning `fetch`; no browser
  profile or session cookie is stored in the work root.
- This does not authorize external publishing or turn a catalog result into a
  usable asset without a certificate and local verification.
