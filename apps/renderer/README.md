# Renderer

This package is the Remotion app. `src/index.ts` stays a scaffold and does not register a composition. Rough previews live in `src/rough-preview/` and are rendered by `scripts/render-rough.mjs`, which Python starts. Locked versions: Remotion 4.0.532, `@remotion/renderer` 4.0.532, `@remotion/bundler` 4.0.532, React 19.3.0, TypeScript 5.9.3.

The rough composition is a 720×1280 review frame. `HeroDraft` is a separate 1080×1920 composition for an approved clip. Neither one publishes.

Contracts are the JSON Schema files in `../../schemas/generated`. `schemaIndexVersion()` reads `index.json` and fails if the file or the version string is missing.
