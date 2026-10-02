# ADR 0016: Storage safety

- Status: Accepted
- Date: 2026-10-02

## Context

Derived media has to be estimated before ffmpeg starts. On a full disk, ffmpeg fails halfway and leaves a partial file. The root filesystem measured during this round had about 24.6 GiB free. That is enough for small proxies and not enough to treat temporary space as unlimited.

`/tmp` on the same machine is a tmpfs of about 7.6 GiB. Tests that measure the pytest temporary directory see that tmpfs, not the root filesystem.

## Decision

`CLIPFORGE_WORK_ROOT` overrides `WORK_ROOT`. If neither is set, the work root stays `var/work`.

`CLIPFORGE_DISK_RESERVE_GB` defaults to 10. There is no flag that disables the check.

Usable space is `free - reserve`. Preparation is refused when `free - estimate <= reserve`, so the projected free space stays strictly above the reserve. The refusal happens before a job is marked running and before ffmpeg is started.

The estimate is conservative, not exact:

```text
seconds = duration_us / 1_000_000
proxy = seconds * 1_500_000 + 1_000_000
flac = seconds * 32_000 + 100_000    # only when the source has audio
overhead = 8 MiB
estimate = (proxy + proxy + flac + flac + overhead) * 3 / 2
```

The proxy term is repeated because the partial and the final can both exist for a moment. The FLAC term uses the uncompressed 16 kHz 16-bit mono rate as an upper bound and is repeated for the same reason. The `3/2` factor covers filter scratch and the moov rewrite. `clipforge storage status` prints the work root, device id, total, used, free, reserve, and usable bytes.

Cleanup may delete only `*.partial.*` files under that source's work directory. Paths outside the work root are refused. The original source is never deleted.

## Alternatives considered

- A 2 GiB default. Rejected. Ten GiB leaves a larger cushion on a laptop that is already near full. The measured free space still cleared a 10 GiB reserve.
- `--ignore-disk-safety`. Rejected. An override would be the first thing a tight disk invites, which is when the check matters.
- Exact bitrate prediction. Rejected. A high estimate that stops early is safer than a precise estimate that is sometimes low.

## Consequences

A machine with less free space than 10 GiB plus the estimate cannot prepare media until space is freed or `CLIPFORGE_DISK_RESERVE_GB` is set lower on purpose. Tests set that variable to `1` because their files are tiny and their temporary directory may be a tmpfs. That setting is not available as a CLI bypass.
