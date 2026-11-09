/** Worker diagnostics only. Never imported into a composition or used as a frame clock. */
import { readFileSync } from "node:fs";

function memoryFacts() {
  let availableKb = null;
  try {
    const match = /^MemAvailable:\s+(\d+)\s+kB$/m.exec(readFileSync("/proc/meminfo", "utf8"));
    if (match) availableKb = Number(match[1]);
  } catch {
    // /proc is Linux-specific. An absent counter is not a claim of free RAM.
  }
  return { workerRssBytes: process.memoryUsage().rss, availableKb };
}

export async function withRenderStage(stage, operation) {
  if (!["imports", "bundle", "select", "render"].includes(stage)) {
    throw new Error("unsupported render diagnostic stage");
  }
  const started = process.hrtime.bigint();
  const emit = (state) => process.stderr.write(`${JSON.stringify({
    event: "render-stage",
    stage,
    state,
    elapsedMs: Number((process.hrtime.bigint() - started) / 1_000_000n),
    ...memoryFacts(),
  })}\n`);
  emit("started");
  const heartbeat = setInterval(() => emit("running"), 15_000);
  heartbeat.unref();
  try {
    const result = await operation();
    emit("finished");
    return result;
  } catch (error) {
    emit("failed");
    throw error;
  } finally {
    clearInterval(heartbeat);
  }
}
