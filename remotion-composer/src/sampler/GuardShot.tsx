import React from "react";
import { AbsoluteFill, Img, staticFile, useCurrentFrame } from "remotion";

/**
 * Hard-Hat History sampler — scene 3 test shot.
 * Layer order (bottom -> top): plate -> contact shadow -> 2D outlined actor
 * -> foreground plane -> grade (vignette + grain) -> caption.
 * Every value is a pure function of the frame number (deterministic).
 */
export type GuardShotProps = {
  /** "layers" = built-in 2.5D SVG plate; "image" = pre-rendered plate (Three.js / threejs_world) */
  plate: "layers" | "image";
  plateSrc?: string;
  caption: string;
};

const W = 1080;
const H = 1920;
const FEET_Y = 1610; // on the boardwalk front edge
const ACTOR_X = 330;
const OUTLINE = "#0b0b0d";

// ---------------------------------------------------------------- 2.5D plate
const Plate25D: React.FC = () => {
  const stripes: React.ReactNode[] = [];
  for (let i = 0; i < 20; i++) {
    const x = i * 56;
    const tone = 30 + ((i * 37) % 9);
    stripes.push(
      <rect key={i} x={x} y={190} width={56} height={1320} fill={`hsl(20,55%,${tone}%)`} />,
      <rect key={`l${i}`} x={x} y={190} width={3} height={1320} fill="rgba(0,0,0,0.45)" />,
    );
  }
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
      <defs>
        <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#6f8fb8" />
          <stop offset="1" stopColor="#f0b27c" />
        </linearGradient>
        <linearGradient id="ground" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#b98a55" />
          <stop offset="1" stopColor="#8a5f33" />
        </linearGradient>
        <linearGradient id="sunwash" x1="0" y1="0" x2="1" y2="0.3">
          <stop offset="0" stopColor="rgba(255,194,122,0.35)" />
          <stop offset="1" stopColor="rgba(20,10,30,0.35)" />
        </linearGradient>
        <filter id="soft"><feGaussianBlur stdDeviation="10" /></filter>
      </defs>
      <rect width={W} height={H} fill="url(#sky)" />
      {stripes}
      <rect x={0} y={190} width={W} height={1320} fill="url(#sunwash)" />
      <rect x={0} y={190} width={W} height={240} fill="#5a2c14" />
      <rect x={146} y={224} width={788} height={158} fill="#d6b06a" />
      <text x={540} y={338} textAnchor="middle" fontFamily="Georgia, serif" fontWeight={700} fontSize={92} fill="#3a2412">MUDLOW BANK</text>
      <rect x={66} y={964} width={330} height={540} fill="#1d0c06" />
      <rect x={612} y={946} width={328} height={328} fill="#e09f40" />
      {[680, 770, 860].map((x) => <rect key={x} x={x} y={946} width={18} height={328} fill="#1d0c06" />)}
      <rect x={0} y={1506} width={W} height={124} fill="#6b3a1b" />
      <rect x={0} y={1630} width={W} height={290} fill="url(#ground)" />
      <ellipse cx={330} cy={1700} rx={330} ry={34} fill="rgba(0,0,0,0.30)" filter="url(#soft)" />
      <path d="M672 1500 L950 1500 L930 1750 L690 1750 Z" fill="#7a3f1a" />
      <ellipse cx={811} cy={1500} rx={139} ry={26} fill="#8a4a22" />
      {[1560, 1700].map((y) => <rect key={y} x={668} y={y} width={286} height={14} fill="#1a1a1a" />)}
      <path d="M722 1360 L896 1360 L876 1468 L742 1468 Z" fill="#505860" />
      <path d="M722 1360 Q809 1300 896 1360" fill="none" stroke="#2c2c2c" strokeWidth={8} />
    </svg>
  );
};

// ------------------------------------------------------------------- actor
const Guard: React.FC<{ frame: number }> = ({ frame }) => {
  const shake = Math.sin(frame * 1.9) * 4 + Math.sin(frame * 0.7) * 2;
  const back = Math.min(frame, 60) * 0.7; // slow back-step
  const armWave = Math.sin(frame * 0.9) * 7;
  const S = 6.5; // stroke thickness for limbs
  return (
    <g transform={`translate(${ACTOR_X - back + shake} ${FEET_Y})`}>
      {/* legs (29% of height) */}
      <path d="M-34 -150 L-40 -8" stroke={OUTLINE} strokeWidth={S * 1.6} strokeLinecap="round" />
      <path d="M34 -150 L42 -8" stroke={OUTLINE} strokeWidth={S * 1.6} strokeLinecap="round" />
      <ellipse cx={-52} cy={-2} rx={32} ry={14} fill={OUTLINE} />
      <ellipse cx={56} cy={-2} rx={32} ry={14} fill={OUTLINE} />
      {/* arms raised in fear */}
      <path d={`M-92 -330 Q-150 ${-380 + armWave} -128 ${-470 + armWave}`} stroke={OUTLINE} strokeWidth={S * 1.5} fill="none" strokeLinecap="round" />
      <path d={`M92 -330 Q150 ${-380 - armWave} 128 ${-470 - armWave}`} stroke={OUTLINE} strokeWidth={S * 1.5} fill="none" strokeLinecap="round" />
      <circle cx={-128} cy={-470 + armWave} r={18} fill={OUTLINE} />
      <circle cx={128} cy={-470 - armWave} r={18} fill={OUTLINE} />
      {/* torso (38%): guard blue */}
      <rect x={-96} y={-390} width={192} height={240} rx={34} fill="#2F5DA8" stroke={OUTLINE} strokeWidth={6} />
      <rect x={-96} y={-262} width={192} height={18} fill="#1d3f78" />
      <circle cx={0} cy={-330} r={11} fill="#e8d6a0" stroke={OUTLINE} strokeWidth={3} />
      {/* head (33%), no neck, wider than tall */}
      <ellipse cx={0} cy={-492} rx={108} ry={104} fill="#ffffff" stroke={OUTLINE} strokeWidth={6} />
      {/* cap */}
      <path d="M-104 -520 Q0 -640 104 -520 Z" fill="#2F5DA8" stroke={OUTLINE} strokeWidth={6} />
      <path d="M-30 -526 L130 -534 Q150 -520 120 -508 L-30 -508 Z" fill="#1d3f78" stroke={OUTLINE} strokeWidth={5} />
      <rect x={-12} y={-566} width={24} height={20} rx={4} fill="#e8d6a0" stroke={OUTLINE} strokeWidth={3} />
      {/* face: dot eyes, worried brows, wobbly mouth */}
      <circle cx={-38} cy={-486} r={17} fill="#fff" stroke={OUTLINE} strokeWidth={4} />
      <circle cx={38} cy={-486} r={17} fill="#fff" stroke={OUTLINE} strokeWidth={4} />
      <circle cx={-34 + shake * 0.3} cy={-486} r={6} fill={OUTLINE} />
      <circle cx={42 + shake * 0.3} cy={-486} r={6} fill={OUTLINE} />
      <path d="M-66 -518 L-18 -508" stroke={OUTLINE} strokeWidth={8} strokeLinecap="round" />
      <path d="M66 -518 L18 -508" stroke={OUTLINE} strokeWidth={8} strokeLinecap="round" />
      <path d={`M-30 -440 q15 ${-14 + armWave * 0.4} 30 0 t30 0`} stroke={OUTLINE} strokeWidth={6} fill="none" strokeLinecap="round" />
    </g>
  );
};

// ------------------------------------------------------------ grade + caption
const Grain: React.FC = () => (
  <svg width={W} height={H} style={{ position: "absolute", inset: 0, mixBlendMode: "overlay", opacity: 0.1 }}>
    <filter id="g"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed={7} stitchTiles="stitch" /></filter>
    <rect width={W} height={H} filter="url(#g)" />
  </svg>
);

export const GuardShot: React.FC<GuardShotProps> = ({ plate, plateSrc, caption }) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {/* 1. plate */}
      {plate === "image" && plateSrc ? (
        <Img src={staticFile(plateSrc)} style={{ position: "absolute", width: W, height: H, objectFit: "cover" }} />
      ) : (
        <Plate25D />
      )}
      {/* 2-3. contact shadow + actor */}
      <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
        <ellipse cx={ACTOR_X - Math.min(frame, 60) * 0.7} cy={FEET_Y + 6} rx={130} ry={16} fill="rgba(0,0,0,0.32)" />
        <Guard frame={frame} />
      </svg>
      {/* 4. foreground plane: dark, blurred strip overlapping the ankles */}
      <div style={{ position: "absolute", left: 0, right: 0, top: FEET_Y - 8, bottom: 0, background: "linear-gradient(to bottom, rgba(40,22,10,0) 0%, rgba(40,22,10,0.55) 100%)", filter: "blur(4px)" }} />
      {/* 5. grade */}
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at center, rgba(0,0,0,0) 55%, rgba(0,0,0,0.38) 100%)" }} />
      <Grain />
      {/* 6. caption: fixed lower third, always on top */}
      <div style={{ position: "absolute", left: 0, right: 0, top: 1772, textAlign: "center", fontFamily: "Inter, sans-serif", fontWeight: 900, fontSize: 84, color: "#fff", WebkitTextStroke: "11px #000", paintOrder: "stroke fill", letterSpacing: 1 }}>
        {caption}
      </div>
    </AbsoluteFill>
  );
};
