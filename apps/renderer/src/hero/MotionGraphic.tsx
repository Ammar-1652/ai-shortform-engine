import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { frameAtOrAfter } from "./program-frames.js";

export type MotionGraphic = {
  event_id?: string;
  template?: "credit_card" | "travel_postcard" | "business_identity" | "business_spotlight" | "quran_challenge";
  interval?: { output_start_us?: number; output_end_us?: number };
  purpose?: string;
  source_evidence_ids?: string[];
  display_text?: string;
  x?: number;
  y?: number;
  width?: number;
  height?: number;
};

type Props = {
  graphic: MotionGraphic;
  accent: string;
  fontFamily?: string;
  showLabel?: boolean;
};

const clamp = (value: number) => Math.max(0, Math.min(1, value));

/**
 * Native, deterministic illustrations. These components intentionally accept
 * only a typed template and source-copied text; operator-provided SVG/HTML or
 * effect code never reaches a production composition.
 */
export function MotionGraphicCard({ graphic, accent, fontFamily, showLabel = true }: Props) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (fps !== 30) throw new Error("native graphics require the canonical 30/1 program grid");
  const start = frameAtOrAfter(graphic.interval?.output_start_us);
  const end = Math.max(start + 1, frameAtOrAfter(graphic.interval?.output_end_us));
  const local = Math.max(0, frame - start);
  // A source-grounded illustration is a beat, not a persistent panel. The
  // Quran challenge card gets one compact reveal/confirmation beat and then
  // leaves the picture clear for the closing recitation. The event interval
  // remains the reviewed evidence window; this visual budget prevents a
  // long punch segment from turning into a full-time obstruction.
  const visualEnd = graphic.template === "quran_challenge"
    ? Math.min(end, start + 72)
    : end;
  const duration = Math.max(1, visualEnd - start);
  const enter = clamp(local / Math.min(12, Math.max(1, Math.floor(duration / 3))));
  const visualExit = clamp((visualEnd - frame) / Math.min(10, Math.max(1, Math.floor(duration / 3))));
  const visible = Math.min(enter, visualExit);
  const eased = 1 - Math.pow(1 - visible, 3);
  // A bounded settle is intentional: illustration movement communicates its
  // entrance once instead of becoming a generic looping distraction.
  const settle = 1 - Math.pow(1 - clamp(local / 20), 3);
  const bob = (1 - settle) * 8;
  const width = graphic.width ?? 420;
  const height = graphic.height ?? 300;
  const text = (graphic.display_text ?? "").trim();
  const base = {
    position: "absolute" as const,
    left: graphic.x ?? 72,
    top: graphic.y ?? 760,
    width,
    height,
    // Unlike legacy cards, a completed Quran beat must leave no ghost panel
    // behind while the spoken payoff continues.
    opacity: graphic.template === "quran_challenge" && visible <= 0 ? 0 : 0.1 + 0.9 * eased,
    transform: `translate3d(${(1 - eased) * 38}px, ${bob + (1 - eased) * 20}px, 0) scale(${0.9 + 0.1 * eased})`,
    transformOrigin: "center center",
    filter: "drop-shadow(0 18px 22px rgba(0,0,0,0.34))",
    pointerEvents: "none" as const,
  };
  if (graphic.template === "credit_card") {
    return <CreditCard graphic={graphic} accent={accent} fontFamily={fontFamily} text={text} style={base} local={local} showLabel={showLabel} />;
  }
  if (graphic.template === "travel_postcard") {
    return <TravelPostcard graphic={graphic} accent={accent} fontFamily={fontFamily} text={text} style={base} local={local} showLabel={showLabel} />;
  }
  if (graphic.template === "business_identity") {
    return <BusinessIdentity graphic={graphic} accent={accent} fontFamily={fontFamily} text={text} style={base} local={local} showLabel={showLabel} />;
  }
  if (graphic.template === "quran_challenge") {
    return <QuranChallenge graphic={graphic} accent={accent} fontFamily={fontFamily} text={text} style={base} local={local} showLabel={showLabel} />;
  }
  return <BusinessSpotlight graphic={graphic} accent={accent} fontFamily={fontFamily} text={text} style={base} local={local} showLabel={showLabel} />;
}

function Label({ text, accent, fontFamily, show = true }: { text: string; accent: string; fontFamily?: string; show?: boolean }) {
  if (!show) return null;
  return (
    <div
      style={{
        position: "absolute",
        left: 20,
        right: 20,
        bottom: 18,
        color: "#fff",
        fontFamily: fontFamily ?? "'DejaVu Sans', sans-serif",
        fontSize: 26,
        fontWeight: 800,
        lineHeight: 1.12,
        letterSpacing: -0.5,
        textShadow: "0 2px 8px rgba(0,0,0,.7)",
      }}
    >
      <span
        style={{
          display: "inline-block",
          width: 10,
          height: 10,
          marginRight: 10,
          borderRadius: 2,
          background: accent,
          verticalAlign: "middle",
        }}
      />
      {text}
    </div>
  );
}

function CreditCard({
  accent,
  fontFamily,
  text,
  style,
  local,
  showLabel,
}: {
  graphic: MotionGraphic;
  accent: string;
  fontFamily?: string;
  text: string;
  style: Record<string, string | number>;
  local: number;
  showLabel: boolean;
}) {
  const shine = interpolate(clamp(local / 24), [0, 1], [-440, 620]);
  return (
    <div style={{ ...style, borderRadius: 30, overflow: "hidden", background: "rgba(5,15,32,.92)", border: `2px solid ${accent}99` }}>
      <svg viewBox="0 0 720 440" width="100%" height="100%" aria-label="Animated credit card illustration">
        <defs>
          <linearGradient id="card-bg" x1="0" y1="0" x2="1" y2="1">
            <stop stopColor="#0d2753" />
            <stop offset="0.55" stopColor="#182d77" />
            <stop offset="1" stopColor="#111827" />
          </linearGradient>
          <linearGradient id="chip" x1="0" y1="0" x2="1" y2="1">
            <stop stopColor="#fff1ad" />
            <stop offset="1" stopColor="#c3902f" />
          </linearGradient>
        </defs>
        <rect x="42" y="44" width="636" height="280" rx="34" fill="url(#card-bg)" stroke={accent} strokeWidth="4" />
        <circle cx="596" cy="104" r="74" fill={accent} opacity="0.16" />
        <rect x="92" y="112" width="104" height="76" rx="14" fill="url(#chip)" />
        <path d="M108 150h72M144 120v62" stroke="#896119" strokeWidth="5" opacity=".7" />
        <path d="M92 230h390" stroke="#ffffff" strokeWidth="12" strokeLinecap="round" opacity=".65" />
        <path d="M92 266h214" stroke={accent} strokeWidth="8" strokeLinecap="round" opacity=".9" />
        <g transform={`translate(${shine} 0) rotate(-18 0 0)`} opacity=".28">
          <rect x="0" y="-80" width="105" height="500" fill="#ffffff" />
        </g>
        <circle cx="566" cy="244" r="36" fill="#ffcb5b" opacity=".92" />
        <circle cx="612" cy="244" r="36" fill="#ef5b75" opacity=".9" />
      </svg>
      <Label text={text} accent={accent} fontFamily={fontFamily} show={showLabel} />
    </div>
  );
}

function TravelPostcard({
  accent,
  fontFamily,
  text,
  style,
  local,
  showLabel,
}: {
  graphic: MotionGraphic;
  accent: string;
  fontFamily?: string;
  text: string;
  style: Record<string, string | number>;
  local: number;
  showLabel: boolean;
}) {
  const progress = clamp(local / 28);
  const planeX = 80 + progress * 540;
  const wave = Math.sin(Math.min(local, 36) / 5) * 11;
  return (
    <div style={{ ...style, borderRadius: 24, overflow: "hidden", background: "#092c45", border: `5px solid rgba(255,255,255,.92)`, boxShadow: "0 14px 30px rgba(0,0,0,.42)" }}>
      <svg viewBox="0 0 720 440" width="100%" height="100%" aria-label="Animated tropical travel illustration">
        <rect width="720" height="440" fill="#56c7f1" />
        <circle cx="584" cy="90" r="55" fill="#ffe07a" />
        <path d={`M0 246 C130 ${202 + wave} 230 ${290 - wave} 360 246 S600 ${202 + wave} 720 246 V440 H0Z`} fill="#147da4" />
        <path d={`M0 290 C130 ${246 - wave} 250 ${334 + wave} 390 286 S590 ${252 - wave} 720 298 V440 H0Z`} fill="#085a86" opacity=".92" />
        <path d="M88 282 C93 178 145 126 196 88" stroke="#51351d" strokeWidth="17" strokeLinecap="round" />
        <path d="M190 100c-50-48-104-38-118-3 51 14 85 33 118 3M191 100c12-58 54-81 83-63-9 38-33 68-83 63M188 113c-50 2-88 31-89 63 42-5 71-24 89-63" fill="#1d8048" />
        <path d={`M70 120 C${planeX - 80} 62 ${planeX - 28} 122 ${planeX} 88`} fill="none" stroke="#ffffff" strokeWidth="5" strokeDasharray="12 13" opacity=".9" />
        <g transform={`translate(${planeX} 88) rotate(-12)`}>
          <path d="M0 12 L42 0 L19 22 L11 41 L5 22 L-18 17 Z" fill={accent} stroke="#fff" strokeWidth="3" />
        </g>
      </svg>
      <div style={{ position: "absolute", inset: 0, background: "linear-gradient(transparent 38%, rgba(2,12,24,.74))" }} />
      <Label text={text} accent={accent} fontFamily={fontFamily} show={showLabel} />
    </div>
  );
}

function BusinessSpotlight({
  accent,
  fontFamily,
  text,
  style,
  local,
  showLabel,
}: {
  graphic: MotionGraphic;
  accent: string;
  fontFamily?: string;
  text: string;
  style: Record<string, string | number>;
  local: number;
  showLabel: boolean;
}) {
  const rise = 34 + clamp(local / 24) * 18;
  return (
    <div style={{ ...style, borderRadius: 28, overflow: "hidden", background: "linear-gradient(135deg,#10192f,#263a69)", border: `2px solid ${accent}aa` }}>
      <svg viewBox="0 0 720 440" width="100%" height="100%" aria-label="Animated business spotlight illustration">
        <path d="M0 78 L360 0 L720 78 V440 H0Z" fill="#17264a" />
        <path d="M76 340V218h104v122M216 340V148h130v192M384 340V188h112v152M534 340V96h108v244" fill="#0b1227" stroke="#6c8bd2" strokeWidth="5" />
        {[110, 250, 418, 570].map((x, index) => <rect key={x} x={x} y={150 + index * 15} width="32" height="50" rx="6" fill={accent} opacity={0.3 + (index + 1) * 0.12} />)}
        <path d={`M86 310 C190 260 270 302 350 226 S515 166 632 ${rise}`} fill="none" stroke={accent} strokeWidth="13" strokeLinecap="round" />
        <path d={`M604 ${rise + 6} L632 ${rise} L618 ${rise + 28}`} fill="none" stroke="#fff" strokeWidth="8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <div style={{ position: "absolute", inset: 0, background: "linear-gradient(transparent 42%, rgba(4,9,20,.8))" }} />
      <Label text={text} accent={accent} fontFamily={fontFamily} show={showLabel} />
    </div>
  );
}

function QuranChallenge({
  accent,
  style,
  local,
}: {
  graphic: MotionGraphic;
  accent: string;
  fontFamily?: string;
  text: string;
  style: Record<string, string | number>;
  local: number;
  showLabel: boolean;
}) {
  const { fps } = useVideoConfig();
  const enter = spring({
    fps,
    frame: local,
    config: { damping: 200, stiffness: 170, mass: 0.8 },
    durationInFrames: 18,
  });
  const page = interpolate(local, [5, 24], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const lineReveal = interpolate(local, [18, 42], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const completion = spring({
    fps,
    frame: Math.max(0, local - 38),
    config: { damping: 180, stiffness: 180, mass: 0.7 },
    durationInFrames: 16,
  });
  const pulse = interpolate(local, [38, 48, 62], [0, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const compactStyle = {
    ...style,
    width: Math.min(Number(style.width ?? 420), 430),
    height: Math.min(Number(style.height ?? 280), 280),
    opacity: Number(style.opacity ?? 1) * (0.92 + completion * 0.08),
    transform: `translate3d(${(1 - enter) * 34}px, ${(1 - enter) * 16}px, 0) scale(${0.94 + enter * 0.06})`,
    background: "rgba(8, 24, 19, 0.9)",
    border: `1.5px solid ${accent}b8`,
    borderRadius: 22,
    boxShadow: "0 12px 30px rgba(0,0,0,.32)",
  };
  return (
    <div style={{ ...compactStyle, overflow: "hidden" }}>
      <svg viewBox="0 0 430 280" width="100%" height="100%" aria-label="Animated Quran completion challenge">
        <defs>
          <linearGradient id="quran-challenge-panel" x1="0" y1="0" x2="1" y2="1">
            <stop stopColor="#173f31" />
            <stop offset="1" stopColor="#0d261f" />
          </linearGradient>
          <clipPath id="quran-challenge-clip"><rect x="0" y="0" width="430" height="280" rx="22" /></clipPath>
        </defs>
        <rect width="430" height="280" fill="url(#quran-challenge-panel)" />
        <g clipPath="url(#quran-challenge-clip)">
          <circle cx="370" cy="50" r="66" fill={accent} opacity=".12" />
          <path d="M28 228H402" stroke="#e5f3dd" strokeWidth="2" opacity=".16" />
          {[0, 1, 2].map((index) => (
            <circle key={index} cx={46 + index * 18} cy="244" r="4.5" fill={index < (completion > 0.8 ? 3 : 2) ? accent : "#7b9486"} opacity={0.35 + lineReveal * 0.65} />
          ))}
          <g transform={`translate(${(1 - page) * 18} ${12 - page * 12})`} opacity={0.35 + page * 0.65}>
            <path d="M64 66 Q124 46 202 78 V208 Q128 184 64 200Z" fill="#fbf3d1" stroke={accent} strokeWidth="3" />
            <path d="M366 66 Q306 46 228 78 V208 Q302 184 366 200Z" fill="#fbf3d1" stroke={accent} strokeWidth="3" />
            <path d="M215 76V210" stroke="#b88a43" strokeWidth="3" />
            {[104,130,156].map((y) => (
              <g key={y} opacity={lineReveal}>
                <path d={`M92 ${y} Q132 ${y - 9} 174 ${y} M256 ${y} Q298 ${y - 9} 338 ${y}`} stroke="#6e8a68" strokeWidth="4" strokeLinecap="round" />
              </g>
            ))}
          </g>
          <g transform={`translate(${300 + completion * 8} ${170 - completion * 8})`} opacity={completion}>
            <circle r="28" fill={accent} opacity={0.94 + pulse * 0.06} />
            <path d="M-12 0l9 10 19-23" stroke="#123329" strokeWidth="6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          </g>
          <path d="M40 42H152" stroke={accent} strokeWidth="3" strokeLinecap="round" strokeDasharray="10 8" opacity={0.4 + lineReveal * 0.6} />
          <circle cx="40" cy="42" r="7" fill={accent} opacity={0.5 + completion * 0.5} />
        </g>
      </svg>
    </div>
  );
}

function BusinessIdentity({
  accent,
  fontFamily,
  text,
  style,
  local,
  showLabel,
}: {
  graphic: MotionGraphic;
  accent: string;
  fontFamily?: string;
  text: string;
  style: Record<string, string | number>;
  local: number;
  showLabel: boolean;
}) {
  const reveal = clamp(local / 18);
  const easedReveal = 1 - Math.pow(1 - reveal, 3);
  return (
    <div style={{ ...style, borderRadius: 28, overflow: "hidden", background: "linear-gradient(135deg,#10192f,#263a69)", border: `2px solid ${accent}aa` }}>
      <svg viewBox="0 0 720 440" width="100%" height="100%" aria-label="Animated business identity illustration">
        <defs>
          <linearGradient id="identity-bg" x1="0" y1="0" x2="1" y2="1">
            <stop stopColor="#15244b" />
            <stop offset="1" stopColor="#0a1024" />
          </linearGradient>
        </defs>
        <rect width="720" height="440" fill="url(#identity-bg)" />
        <circle cx="126" cy="138" r="70" fill={accent} opacity=".18" />
        <circle cx="126" cy="138" r="47" fill={accent} opacity={0.3 + easedReveal * 0.5} />
        <path d="M101 166c9-22 41-22 50 0M113 126h26" stroke="#fff" strokeWidth="9" strokeLinecap="round" opacity={easedReveal} />
        <path d="M214 98H634M214 176H634" stroke="#fff" strokeWidth="3" opacity=".16" />
        <g transform={`translate(${(1 - easedReveal) * 46} 0)`} opacity={easedReveal}>
          <rect x="214" y="116" width="300" height="42" rx="21" fill={accent} opacity=".88" />
          <rect x="214" y="194" width="392" height="42" rx="21" fill="#fff" opacity=".16" />
          <text x="236" y="145" fill="#07101f" fontFamily="'DejaVu Sans', sans-serif" fontSize="22" fontWeight="800">PAC-10 ENTERPRISE</text>
          <text x="236" y="223" fill="#fff" fontFamily="'DejaVu Sans', sans-serif" fontSize="22" fontWeight="700">RAPID CREDIT BOOSTERS</text>
        </g>
        <path d="M84 310H636" stroke="#fff" strokeWidth="3" opacity=".16" />
        <path d={`M84 310H${84 + easedReveal * 432}`} stroke={accent} strokeWidth="8" strokeLinecap="round" />
      </svg>
      <div style={{ position: "absolute", inset: 0, background: "linear-gradient(transparent 42%, rgba(4,9,20,.8))" }} />
      <Label text={text} accent={accent} fontFamily={fontFamily} show={showLabel} />
    </div>
  );
}
