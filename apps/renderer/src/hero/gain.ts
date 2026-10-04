/** Convert an SFX gain in dB to a linear Remotion volume. Music is not an input. */

const MIN_GAIN_DB = -24;
const MAX_GAIN_DB = 6;

export function linearVolume(gainDb: number): number {
  if (!Number.isFinite(gainDb) || gainDb < MIN_GAIN_DB || gainDb > MAX_GAIN_DB) {
    throw new Error("SFX gain_db must be between -24 and 6");
  }
  return 10 ** (gainDb / 20);
}
