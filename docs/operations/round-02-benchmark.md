# Round 2 benchmark

Measured on 2026-10-02 with the local ffmpeg build. The source is a synthetic 10 second 1920x1080 H.264 file with a sine audio track, generated in a temporary directory and deleted after the run. It is not committed.

The work directory was on the root filesystem (`var/round02-bench`, removed). `CLIPFORGE_DISK_RESERVE_GB` was left at the default of 10.

| Measurement | Result |
| --- | --- |
| Source duration | 10.000 s (`10000000` µs) |
| Source size | 791,942 bytes |
| Hash time | 0.001 s |
| Probe time | 0.205 s |
| ASR audio encode | 0.103 s |
| Proxy encode | 1.006 s |
| First prepare, wall clock | 1.466 s |
| Cache-hit prepare, wall clock | 0.338 s |
| Proxy size | 222,949 bytes |
| ASR audio size | 147,099 bytes |
| Storage estimate | 61,842,912 bytes |
| Free space at measurement | 26,418,618,368 bytes |
| Reserve | 10,737,418,240 bytes (10 GiB) |
| Second-run transcodes | 0 |

ffmpeg and ffprobe were `n9.0.1`. The proxy recipe is `analysis-proxy` version `1` (libx264, `veryfast`, CRF 28). The audio recipe is `asr-audio` version `1`.

The source is small because the fixture uses `ultrafast` and a generated pattern, so the hash time is not a multi-gigabyte measurement. Hashing still reads the file in 1 MiB chunks. The cache-hit run called ffprobe to revalidate and did not call libx264 or the FLAC encoder.

Peak memory was not sampled. No extra profiler was added.
