# Round 17 validation

Branch `round-17-real-source-platform-boundary` starts from `dcbd18ac10826cfc684c893b8b9a14e9baed1200`. SQLite stays at schema version 6.

## Remotion isolation

A full local suite in Round 16 failed once in `test_real_hero_render_is_portrait_and_captioned` with Remotion `Page crashed`. The same test passed alone, and the CI hero job passed. A second full run failed a different smoke, `test_real_remotion_preview_is_vertical_and_contained`, with `No frame found` for a file under `/tmp/remotion-v4.0.532-assets...`.

Remotion creates the Chrome user-data directory and the composition asset directory with `os.tmpdir()`. Every render on the machine shared that directory. Node was started in its own session, but after it exited Clipforge did not signal the process group, so a Chrome child could remain. The next render could then crash or read an asset the previous process had removed. Renderer logs were appended on a path that could be a symlink.

Putting that directory under the render run isolated the files and then failed every browser smoke. Chrome writes its singleton socket at `{TMPDIR}/puppeteer_dev_chrome_profile-XXXXXX/com.google.Chrome.XXXXXX/SingletonSocket`. `sockaddr_un.sun_path` is 108 bytes. A pytest path such as `/tmp/pytest-of-pakka/.../advanced-hero/runs/<id>/browser-tmp/.../SingletonSocket` is longer than that, so Chrome aborts with `Socket path too long` and Remotion reports `Failed to launch the browser process`. The first full local suite after that change failed only these three tests, all with that socket error:

- `test_chrome_advanced_render_shows_broll_type_and_diagram`
- `test_real_hero_render_is_portrait_and_captioned`
- `test_real_remotion_preview_is_vertical_and_contained`

The fix keeps a private `TMPDIR`, `TMP`, and `TEMP` for the Node process, set before Remotion is imported, but the directory is `/tmp/cfb<random>`. Clipforge refuses the directory when the socket path would still be too long, and deletes it after the render. A file lock serializes browser renders. After Node exits, and before `wait()`, Clipforge signals the process group so the pid is still the zombie leader and cannot have been reused. Log paths that are symlinks are refused. A Node failure includes the text `renderer log` and the captured browser error. No retry was added.

## What was not claimed

- No authorized real source was supplied. `real_source_verified` stays `unavailable` with reason `no authorized source supplied`.
- VoiceStudio was not running. Live smoke was not run.
- `CLIPFORGE_PLATFORM_LIVE_SMOKE` was unset. External upload is `not_configured`. Fake and dry-run publishers do not open sockets.
- A synthetic benchmark is `synthetic_only`. It is not a real-source result.

## Local commands

Both full pytest runs used `uv run pytest -q --tb=line -p no:cacheprovider`.

| Run | Result |
| --- | --- |
| First | 406 passed, 1 skipped, 0 failed, 331.63s |
| Second | 406 passed, 1 skipped, 0 failed, 350.85s |

The repeated runs include the three Remotion smokes. Neither run failed.

`uv run ruff check .`, `uv run ruff format --check .`, and `uv run mypy` passed. mypy checked 202 source files. `uv run clipforge schema check` matched `schemas/generated`. `uv run clipforge doctor` reported 10 pass, 0 warn, 0 fail. Schema version stayed 6.

`pnpm --dir apps/renderer lint`, `typecheck`, and `test` passed. Vitest ran 23 tests.

`CLIPFORGE_PLATFORM_LIVE_SMOKE`, `CLIPFORGE_VOICESTUDIO_URL`, and `CLIPFORGE_VOICESTUDIO_LIVE_SMOKE` were unset. No live upload was attempted. No VoiceStudio process was contacted.
