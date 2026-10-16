/** Canonical 30/1 output-grid cue ownership. Never start a cue early. */
export function frameAtOrAfter(microseconds: number | undefined): number {
  if (microseconds === undefined) return 0;
  if (!Number.isSafeInteger(microseconds) || microseconds < 0) {
    throw new Error("cue time must be non-negative integer microseconds");
  }
  let frame = Math.floor((microseconds * 30) / 1_000_000);
  while (Math.floor((frame * 1_000_000) / 30) < microseconds) frame += 1;
  return frame;
}

export function cueWindow(startUs: number | undefined, endUs: number | undefined) {
  const from = frameAtOrAfter(startUs);
  const end = frameAtOrAfter(endUs);
  return { from, duration: Math.max(1, end - from) };
}
