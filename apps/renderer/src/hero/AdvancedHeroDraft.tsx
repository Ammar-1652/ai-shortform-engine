import { AbsoluteFill, Audio, OffthreadVideo, staticFile, useCurrentFrame } from "remotion";

type Interval = { output_start_us?: number; output_end_us?: number };

type TypeEvent = {
  text?: string;
  interval?: Interval;
  component_id?: string;
  purpose?: string;
};

type DiagramEvent = {
  component_id?: string;
  interval?: Interval;
  payload?: {
    left_label?: string;
    right_label?: string;
    left_value?: number;
    right_value?: number;
  };
};

type BrollEvent = { asset_id?: string; interval?: Interval };
type SfxEvent = { asset_id?: string; interval?: Interval; gain_db?: number };
type EmphasisEvent = { text?: string; output_start_us?: number; output_end_us?: number };

export type AdvancedHeroInput = {
  duration_in_frames: number;
  base_video_name?: string;
  speech_name?: string;
  typography?: TypeEvent[];
  diagrams?: DiagramEvent[];
  broll?: BrollEvent[];
  sfx?: SfxEvent[];
  emphasis?: EmphasisEvent[];
  asset_names?: Record<string, string>;
};

const FPS = 30;

function frameAt(microseconds: number | undefined): number {
  if (typeof microseconds !== "number") {
    return 0;
  }
  return Math.floor((microseconds * FPS) / 1_000_000);
}

function active(frame: number, interval: Interval | undefined): boolean {
  const start = frameAt(interval?.output_start_us);
  const end = frameAt(interval?.output_end_us);
  return frame >= start && frame < end;
}

/**
 * Advanced portrait draft. Text nodes are React children.
 * A face box is not a speaker. Music is not a layer.
 */
export function AdvancedHeroDraft(input: AdvancedHeroInput) {
  const frame = useCurrentFrame();
  const names = input.asset_names ?? {};
  const broll = (input.broll ?? []).find((item) => active(frame, item.interval));
  const brollName = broll?.asset_id ? names[broll.asset_id] : undefined;
  const typography = input.typography ?? [];
  const typeVisible = typography.some((item) => active(frame, item.interval));
  const typeText = typography.map((item) => item.text ?? "").join(" ");
  const diagram = (input.diagrams ?? []).find((item) => active(frame, item.interval));
  const emphasis = (input.emphasis ?? []).filter(
    (item) => frame >= frameAt(item.output_start_us) && frame < frameAt(item.output_end_us),
  );
  const speech = input.speech_name ?? "asr.flac";
  const picture = input.base_video_name ?? "analysis.mp4";
  return (
    <AbsoluteFill style={{ backgroundColor: "#003300" }}>
      <OffthreadVideo
        src={staticFile(picture)}
        durationInFrames={input.duration_in_frames}
        muted
        style={{ width: "100%", height: "100%", objectFit: "cover" }}
      />
      <Audio src={staticFile(speech)} durationInFrames={input.duration_in_frames} />
      {(input.sfx ?? []).map((item) => {
        const name = item.asset_id ? names[item.asset_id] : undefined;
        if (!name || !active(frame, item.interval)) {
          return null;
        }
        return <Audio key={name} src={staticFile(name)} volume={0.5} />;
      })}
      {brollName === undefined ? null : (
        <AbsoluteFill>
          <OffthreadVideo
            src={staticFile(brollName)}
            muted
            style={{ width: "100%", height: "100%", objectFit: "cover" }}
          />
        </AbsoluteFill>
      )}
      {diagram === undefined ? null : (
        <AbsoluteFill>
          <div style={{ position: "absolute", left: 140, top: 320, width: 280, height: 280, backgroundColor: "#ff00ff" }} />
          <div style={{ position: "absolute", left: 520, top: 320, width: 280, height: 280, backgroundColor: "#00ffff" }} />
          <div style={{ position: "absolute", left: 160, top: 340, color: "#000000", fontFamily: "sans-serif", fontSize: 36 }}>
            {diagram.payload?.left_label} {diagram.payload?.left_value}
          </div>
          <div style={{ position: "absolute", left: 540, top: 340, color: "#000000", fontFamily: "sans-serif", fontSize: 36 }}>
            {diagram.payload?.right_label} {diagram.payload?.right_value}
          </div>
        </AbsoluteFill>
      )}
      {typeVisible ? (
        <div
          style={{
            position: "absolute",
            left: 72,
            top: 1480,
            width: 936,
            height: 220,
            backgroundColor: "#ffff00",
            color: "#000000",
            fontFamily: "sans-serif",
            fontSize: 64,
            fontWeight: 700,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            textAlign: "center",
          }}
        >
          {typeText}
        </div>
      ) : null}
      {emphasis.length === 0 ? null : (
        <div style={{ position: "absolute", left: 72, top: 1720, color: "#ffffff", fontFamily: "sans-serif", fontSize: 28 }}>
          {emphasis.map((item) => item.text ?? "").join(" ")}
        </div>
      )}
    </AbsoluteFill>
  );
}
