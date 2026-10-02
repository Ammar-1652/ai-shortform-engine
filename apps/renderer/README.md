# Renderer scaffold

This package is the future Remotion app. Round 1 checks that TypeScript strict mode, ESLint, and Vitest run, and that the `remotion` package installs. Locked versions: Remotion 4.0.532, React 19.3.0, TypeScript 5.9.3. TypeScript 7 was not used because `typescript-eslint` 8.71 does not support it.

There is no composition, no `Root.tsx`, and no render script. Do not add a command that pretends a reel was written.

Contracts for a later round are the JSON Schema files in `../../schemas/generated`. `schemaIndexVersion()` reads `index.json` and fails if the file or the version string is missing.
