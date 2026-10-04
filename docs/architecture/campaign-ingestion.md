# Campaign ingestion

Clipforge keeps one editing core. A campaign adds policy, rights evidence, and an explicit acquisition plan.

## Antoine Sallis

The policy source is `Antoine Sallis Clipping - Full Guide.docx`. "No AI edits" and "No AI subtitles" block external black-box tools. Native Clipforge editing and reviewed native captions stay allowed. Aura, glow, skull, and emoji effects are blocked. Newest-footage priority is `needs_operator_clarification`.

Allowed platforms are TikTok, Instagram Reels, Facebook Reels, and YouTube Shorts. English is the default language. Outside footage is blocked. `@antoinesallis` and `#AntoineSallis` belong on reviewed captions.

## Catalogue

Round 18 may acquire only:

- Drive id `12RKu2wuIgCccBpcwjhlbzEUM7lEt8vwN`, 180882018 bytes
- Drive id `1IzZ6Klx6_y6stfhpa2q2Cf9qIK92eeim`, 163530208 bytes

These stay `not_selected_for_round_18` and are not downloaded:

- `Copy of YTDown.com_YouTube_OG-Cuicide-In-The-Building-with-Antoine-_Media_9UQaKdtK0bM_001_1080p.mp4`
- `Antoine - Sept 1.mp4`
- `Antoine Septemberr 3.mp4`

Drive folder membership is not rights evidence. The guide and an operator confirmation are. Set `CLIPFORGE_DRIVE_ACQUIRE=1` to download. Without it, ingest records `provider_unavailable`.

## Commands

```text
clipforge campaign doctor
clipforge campaign list
clipforge campaign show CAMPAIGN_ID
clipforge campaign inventory CAMPAIGN_ID
clipforge campaign policy CAMPAIGN_ID
clipforge campaign acquire-plan CAMPAIGN_ID
clipforge campaign ingest CAMPAIGN_ID
clipforge campaign verify CAMPAIGN_ID
```

`verify` re-hashes acquired files and does not download.

## Whop

`FakeCampaignDiscoveryProvider` and `DryRunCampaignDiscoveryProvider` return public campaign ids only. `WhopCampaignProvider` stays `not_configured` unless `CLIPFORGE_WHOP_LIVE=1`, and even then it refuses to run without an already-authorized browser session. It does not collect passwords, cookies, or tokens. CI does not set the flag.

## Publishing

External platform publishing remains deferred. Local delivery is unchanged.
