/** Pick the cue whose half-open frame window contains the current output frame. */

import type { RoughCaptionCue } from "./types.js";

export function activeCaption(captions: readonly RoughCaptionCue[], frame: number): RoughCaptionCue | null {
  if (!Number.isInteger(frame) || frame < 0) {
    throw new Error("caption frame must be a non-negative integer");
  }
  const hits = captions.filter(
    (cue) => frame >= cue.output_start_frame && frame < cue.output_end_frame_exclusive,
  );
  if (hits.length > 1) {
    throw new Error("more than one provisional caption is active on this frame");
  }
  return hits[0] ?? null;
}
