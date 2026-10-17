# Tarteel editing-material preparation

The Tarteel campaign may use licensed fonts, one-shot SFX, and deterministic
transitions/motion while continuing to prohibit outside footage, unrelated
stock, and music. The original campaign intake evidence remains immutable. The
current work-root preparation manifest is:

`var/work/campaigns/Tarteel/editing-material/editing-material-search-plan.json`

## Prepared local material

- Amiri Quran and Amiri Regular are staged under the Tarteel work root with
  the Amiri OFL notice and hashes. Amiri Quran is reserved for canonical Quran
  text after selected-audio review and forced alignment; a font does not prove
  verse accuracy.
- Kenney Interface Sounds is staged as 100 CC0 OGG one-shots. The pack is
  suitable for restrained clicks, selects, confirmations, ticks, toggles, and
  interface accents. It is not a license to place an effect on every cut.
- YouTubeSFX and Lots of Sounds are recorded as optional external sources. The
  former advertised a commercial-license starter pack, but direct download was
  unavailable from this environment; the latter advertised CC0 downloads but
  requires an account. Neither is marked downloaded.

## Envato handoff and verified material

The official Envato MCP is live when both `CLIPFORGE_ENVATO_MCP_ENABLED=1` and
`CLIPFORGE_ENVATO_MCP_LIVE_SMOKE=1` are set. The MyToolsPlan login is stored in
the Linux Secret Service keyring; it is never written to this repository.
Requests are created from the live advertised schemas and retain their exact
item URLs. The bridge then downloads the licensed archive and certificate and
registers only verified local files.

The current verified Tarteel preparation set is kept under the ignored work
root `var/work/campaigns/envato-assets/`:

- Arabic Kufi display font ([Envato item](https://elements.envato.com/arabikufi-display-a-latin-kufi-arabic-style-NCRUP24)), request
  `fc279503-bf0f-47dd-aed2-58f6631f3888`, asset
  `env-6d79115aa30782029f30-portal-84e258b6d27e-tag-38ee46d2`, 230072 bytes,
  SHA-256 `6d79115aa30782029f301484a826526282edd17bdb9cc5449f8816bb7c63c9a6`.
- Soft UI click ([Envato item](https://elements.envato.com/soft-click-LV55DY5)), request
  `b23dd4f0-ad2f-483d-ade0-71e587ca910a`, asset
  `env-d30e52d3437c505fec60-portal-53abf0a961d4-tag-ec00f12a`, 168044 bytes,
  SHA-256 `d30e52d3437c505fec60128e535c2c75fb343a9bd34c2472abdfa3859329ae27`.
- Soft transition whoosh ([Envato item](https://elements.envato.com/transition-whoosh-7PDAVP7)), request
  `60d79aaf-e79f-4590-aae9-88a5cfa88342`, asset
  `env-3bf2ae930d4a2731d75a-portal-969bedd20a47-tag-a6bf34c0`, 264678 bytes,
  SHA-256 `3bf2ae930d4a2731d75acc372977f0e735c843a3529b010c437be5081a309e47`.
- Short digital riser ([Envato item](https://elements.envato.com/quick-digital-riser-APARWG6)), request
  `d41fda7e-0e09-4744-b5d0-1ec255c5831d`, asset
  `env-be18bc58a6c1b74323f0-portal-b439395f9cb4-tag-5592e652`, 217734 bytes,
  SHA-256 `be18bc58a6c1b74323f0d1ba69d640f7f96838f6d80b8983842d4d8fafa06a7e`.

Each registration has `download_status=portal_download_verified`,
`rights_status=allowed`, a certificate under its `license.txt`, and a verified
probe. The MCP item URLs and portal/license IDs are in each request and
manifest sidecar; the signed download URLs are intentionally not persisted.

## Production gate

Each selected SFX must have a source-grounded purpose and exact output interval:
whoosh for a reviewed movement/transition, click for a UI interaction, impact
for a meaningful reveal, and riser only before a reviewed reveal. Audio remains
under the speech envelope and is measured after encoding. No SFX is inserted
automatically or used to hide a bad cut.

Because the original campaign intake says no added sound, the operator's
allowance for licensed SFX is recorded in the campaign addendum before a final
campaign package is approved. This preparation round does not silently rewrite
the original evidence or grant approval. SFX remain optional, purpose-bound,
and subject to the speech-envelope and final human review gates.
