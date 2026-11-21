import React from "react";

/**
 * Original cast for the Mudlow sampler. Flat 2D actors: white egg head (wider than tall),
 * heavy black per-part outline, dot eyes, no nose, thin stick limbs, mitten hands.
 * Proportions fixed: head .33 / body .38 / legs .29 of height. Origin = feet line, y up is negative.
 * Height at scale 1 = ~620px. All motion is a pure function of `t` (frame).
 */
export type Emotion = "neutral" | "scared" | "smug" | "puzzled" | "deadpan" | "caught";
export type Arms = "down" | "up" | "point" | "wave" | "flail";
export type Hat = "none" | "cap" | "sheriff" | "flatcap" | "bucket";

export type CharacterProps = {
  body: string;
  trim: string;
  hat?: Hat;
  hatColor?: string;
  emotion?: Emotion;
  arms?: Arms;
  scale?: number;
  x: number;
  feetY: number;
  flip?: boolean;
  t?: number;
  apron?: string;
  /** vertical lift of a bucket hat (reveal beat) */
  lift?: number;
};

const OUT = "#0b0b0d";

export const COLORS = {
  guard: { body: "#2F5DA8", trim: "#1d3f78", hat: "#2F5DA8" },
  thief: { body: "#D9A21B", trim: "#a87a10", hat: "#5a4a2a" },
  sheriff: { body: "#A4452C", trim: "#7a2f1d", hat: "#C9A15A" },
  shop: { body: "#3f7d4a", trim: "#2c5a35", hat: "#3f7d4a" },
};

const Brows: React.FC<{ e: Emotion }> = ({ e }) => {
  const s = { stroke: OUT, strokeWidth: 8, strokeLinecap: "round" as const, fill: "none" };
  switch (e) {
    case "scared": return <><path d="M-66 -518 L-18 -508" {...s} /><path d="M66 -518 L18 -508" {...s} /></>;
    case "smug": return <><path d="M-62 -516 L-18 -512" {...s} /><path d="M62 -528 L18 -516" {...s} /></>;
    case "puzzled": return <><path d="M-62 -512 L-18 -520" {...s} /><path d="M62 -522 L18 -510" {...s} /></>;
    case "caught": return <><path d="M-62 -528 Q-40 -540 -18 -528" {...s} /><path d="M62 -528 Q40 -540 18 -528" {...s} /></>;
    case "deadpan": return <><path d="M-62 -514 L-18 -514" {...s} /><path d="M62 -514 L18 -514" {...s} /></>;
    default: return <><path d="M-62 -518 L-18 -514" {...s} /><path d="M62 -518 L18 -514" {...s} /></>;
  }
};

const Mouth: React.FC<{ e: Emotion; w: number }> = ({ e, w }) => {
  const s = { stroke: OUT, strokeWidth: 6, strokeLinecap: "round" as const, fill: "none" };
  switch (e) {
    case "scared": return <path d={`M-30 -440 q15 ${-14 + w * 0.4} 30 0 t30 0`} {...s} />;
    case "smug": return <path d="M-24 -446 Q10 -430 34 -452" {...s} />;
    case "puzzled": return <path d="M-22 -444 q10 -8 20 0 t20 -4" {...s} />;
    case "caught": return <ellipse cx={0} cy={-444} rx={13} ry={17} fill={OUT} />;
    case "deadpan": return <path d="M-26 -444 L26 -444" {...s} />;
    default: return <path d="M-22 -446 Q0 -434 22 -446" {...s} />;
  }
};

const Hat: React.FC<{ hat: Hat; color: string; lift: number; t: number }> = ({ hat, color, lift, t }) => {
  if (hat === "cap") return (<>
    <path d="M-104 -520 Q0 -640 104 -520 Z" fill={color} stroke={OUT} strokeWidth={6} />
    <path d="M-30 -526 L130 -534 Q150 -520 120 -508 L-30 -508 Z" fill="#1d3f78" stroke={OUT} strokeWidth={5} />
    <rect x={-12} y={-566} width={24} height={20} rx={4} fill="#e8d6a0" stroke={OUT} strokeWidth={3} />
  </>);
  if (hat === "sheriff") return (<>
    <ellipse cx={0} cy={-532} rx={160} ry={24} fill={color} stroke={OUT} strokeWidth={6} />
    <path d="M-86 -534 Q-70 -640 0 -640 Q70 -640 86 -534 Z" fill={color} stroke={OUT} strokeWidth={6} />
    <path d="M-86 -552 L86 -552" stroke="#7a5a2a" strokeWidth={10} />
  </>);
  if (hat === "flatcap") return (<>
    <path d="M-106 -524 Q-60 -606 30 -590 Q112 -580 108 -524 Z" fill={color} stroke={OUT} strokeWidth={6} />
    <path d="M60 -540 L140 -530 Q146 -516 110 -512 Z" fill="#3a2f1a" stroke={OUT} strokeWidth={5} />
  </>);
  if (hat === "bucket") {
    const y = -lift;
    return (<g transform={`translate(0 ${y})`}>
      <path d="M-124 -622 L124 -622 L98 -470 L-98 -470 Z" fill="#8a9298" stroke={OUT} strokeWidth={6} />
      <ellipse cx={0} cy={-622} rx={124} ry={20} fill="#aab2b8" stroke={OUT} strokeWidth={6} />
      <path d="M-124 -622 Q0 -740 124 -622" fill="none" stroke="#3a3a3a" strokeWidth={7} />
      <path d="M-80 -560 L-70 -500" stroke="rgba(255,255,255,0.35)" strokeWidth={9} strokeLinecap="round" />
    </g>);
  }
  return null;
};

export const Character: React.FC<CharacterProps> = ({
  body, trim, hat = "none", hatColor, emotion = "neutral", arms = "down", scale = 1, x, feetY, flip = false, t = 0, apron, lift = 0,
}) => {
  const wob = emotion === "scared" ? Math.sin(t * 1.9) * 4 + Math.sin(t * 0.7) * 2 : Math.sin(t * 0.12) * 1.2;
  const wave = Math.sin(t * 0.9) * 7;
  const S = 6.5;
  const armPath = (side: -1 | 1) => {
    const up = arms === "up" || arms === "flail";
    if (arms === "point" && side === 1) return { d: "M92 -330 Q190 -340 280 -380", hand: [280, -380] };
    if (arms === "wave" && side === 1) return { d: `M92 -330 Q150 ${-400 + wave} 150 ${-470 + wave}`, hand: [150, -470 + wave] };
    if (up) { const w = (side === -1 ? 1 : -1) * wave; return { d: `M${92 * side} -330 Q${150 * side} ${-380 + w} ${128 * side} ${-470 + w}`, hand: [128 * side, -470 + w] }; }
    return { d: `M${92 * side} -330 Q${120 * side} -250 ${108 * side} -170`, hand: [108 * side, -168] };
  };
  const L = armPath(-1), R = armPath(1);
  return (
    <g transform={`translate(${x + wob} ${feetY}) scale(${flip ? -scale : scale} ${scale})`}>
      <path d="M-34 -150 L-40 -8" stroke={OUT} strokeWidth={S * 1.6} strokeLinecap="round" />
      <path d="M34 -150 L42 -8" stroke={OUT} strokeWidth={S * 1.6} strokeLinecap="round" />
      <ellipse cx={-52} cy={-2} rx={32} ry={14} fill={OUT} />
      <ellipse cx={56} cy={-2} rx={32} ry={14} fill={OUT} />
      <path d={L.d} stroke={OUT} strokeWidth={S * 1.5} fill="none" strokeLinecap="round" />
      <path d={R.d} stroke={OUT} strokeWidth={S * 1.5} fill="none" strokeLinecap="round" />
      <circle cx={L.hand[0]} cy={L.hand[1]} r={18} fill={OUT} />
      <circle cx={R.hand[0]} cy={R.hand[1]} r={18} fill={OUT} />
      <rect x={-96} y={-390} width={192} height={240} rx={34} fill={body} stroke={OUT} strokeWidth={6} />
      <rect x={-96} y={-262} width={192} height={18} fill={trim} />
      {apron && <path d="M-70 -330 L70 -330 L80 -152 L-80 -152 Z" fill={apron} stroke={OUT} strokeWidth={5} />}
      <circle cx={0} cy={-330} r={11} fill="#e8d6a0" stroke={OUT} strokeWidth={3} />
      <ellipse cx={0} cy={-492} rx={108} ry={104} fill="#fff" stroke={OUT} strokeWidth={6} />
      <Hat hat={hat} color={hatColor || body} lift={lift} t={t} />
      <circle cx={-38} cy={-486} r={17} fill="#fff" stroke={OUT} strokeWidth={4} />
      <circle cx={38} cy={-486} r={17} fill="#fff" stroke={OUT} strokeWidth={4} />
      <circle cx={-34 + wob * 0.3} cy={-486} r={6} fill={OUT} />
      <circle cx={42 + wob * 0.3} cy={-486} r={6} fill={OUT} />
      <Brows e={emotion} />
      <Mouth e={emotion} w={wave} />
      {hat === "sheriff" && <path d="M-60 -330 l8 -18 l8 18 l-14 -11 l14 0 z" fill="#f0c43a" stroke={OUT} strokeWidth={3} transform="translate(104 0)" />}
    </g>
  );
};

/** Flat outlined bucket prop (2D layer) */
export const FlatBucket: React.FC<{ x: number; feetY: number; scale?: number; boots?: boolean; silhouette?: boolean }> = ({ x, feetY, scale = 1, boots = false, silhouette = false }) => (
  <g transform={`translate(${x} ${feetY}) scale(${scale})`}>
    {boots && <><path d="M-22 -30 L-24 0" stroke={OUT} strokeWidth={9} strokeLinecap="round" /><path d="M22 -30 L26 0" stroke={OUT} strokeWidth={9} strokeLinecap="round" /><ellipse cx={-34} cy={2} rx={22} ry={10} fill={OUT} /><ellipse cx={38} cy={2} rx={22} ry={10} fill={OUT} /></>}
    <path d="M-70 -200 L70 -200 L52 -30 L-52 -30 Z" transform={boots ? "" : "translate(0 30)"} fill={silhouette ? "#111" : "#8a9298"} stroke={OUT} strokeWidth={6} />
    <ellipse cx={0} cy={boots ? -200 : -170} rx={70} ry={12} fill={silhouette ? "#222" : "#aab2b8"} stroke={OUT} strokeWidth={5} />
    <path d={boots ? "M-70 -200 Q0 -280 70 -200" : "M-70 -170 Q0 -250 70 -170"} fill="none" stroke="#3a3a3a" strokeWidth={6} />
  </g>
);
