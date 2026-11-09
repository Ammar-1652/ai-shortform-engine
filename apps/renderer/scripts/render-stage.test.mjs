import { afterEach, describe, expect, it, vi } from "vitest";
import { withRenderStage } from "./render-stage.mjs";

afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

describe("bounded worker diagnostics", () => {
  it("records stages and clears heartbeat timers after completion", async () => {
    vi.useFakeTimers();
    const write = vi.spyOn(process.stderr, "write").mockReturnValue(true);
    const result = await withRenderStage("bundle", async () => "bundled");
    expect(result).toBe("bundled");
    const records = write.mock.calls.map(([line]) => JSON.parse(line));
    expect(records.map((record) => record.state)).toEqual(["started", "finished"]);
    expect(records.every((record) => record.stage === "bundle")).toBe(true);
    expect(records[0].workerRssBytes).toBeGreaterThan(0);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("reports a waiting stage and propagates failure without leaking a timer", async () => {
    vi.useFakeTimers();
    const write = vi.spyOn(process.stderr, "write").mockReturnValue(true);
    let reject;
    const work = new Promise((_, rejectPromise) => { reject = rejectPromise; });
    const result = withRenderStage("select", () => work);
    const failure = expect(result).rejects.toThrow("browser closed");
    await vi.advanceTimersByTimeAsync(15_000);
    reject(new Error("browser closed"));
    await failure;
    expect(write.mock.calls.map(([line]) => JSON.parse(line).state)).toEqual(["started", "running", "failed"]);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("refuses arbitrary text in diagnostic stage names", async () => {
    await expect(withRenderStage("private input", async () => {})).rejects.toThrow("unsupported");
  });
});
