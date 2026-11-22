import React from "react";
import { AbsoluteFill, Img, Sequence, staticFile, useCurrentFrame, interpolate, Easing } from "remotion";
import { Character, FlatBucket, CharacterProps } from "./Characters";
import { SHOTS, cast, Grain } from "./Shots";
import { CAPTION_CUES } from "./captionCues";

/** Mudlow sampler: 25s, 30fps, 1080x1920. Hard cuts only; every value is a pure function of the frame. */
const W = 1080, H = 1920, FPS = 30, PUB = "hard-hat-history-sampler";
const T: [string, number, number][] = [
  ["sc1", 0, 3.0], ["sc2", 3.0, 5.2], ["sc3", 5.2, 7.6], ["sc4", 7.6, 9.4], ["sc5", 9.4, 11.0], ["sc6", 11.0, 12.8],
  ["sc7", 12.8, 15.0], ["sc8", 15.0, 17.4], ["sc9", 17.4, 19.6], ["sc10", 19.6, 22.6], ["sc11", 22.6, 25.0],
];
/** Caption timing from measured speech boundaries of the voiceover lines (see captionCues.ts). */
export const CAPTIONS: [string, number, number][] = CAPTION_CUES;

type Cam = { k: "none" | "push" | "pan" | "tilt"; a?: number; b?: number; dx?: number; dy?: number };
const CAM: Record<string, Cam> = {
  sc1: { k: "push", a: 1.0, b: 1.12 }, sc2: { k: "push", a: 1.0, b: 1.08 }, sc3: { k: "none" }, sc4: { k: "pan", dx: -60 },
  sc5: { k: "tilt", dy: 150 }, sc6: { k: "pan", dx: 90 }, sc7: { k: "push", a: 1.0, b: 1.1 }, sc8: { k: "pan", dx: -120 },
  sc9: { k: "push", a: 1.0, b: 1.1 }, sc10: { k: "none" }, sc11: { k: "none" },
};

const ease = (p: number) => Easing.inOut(Easing.cubic)(Math.max(0, Math.min(1, p)));

/** Per-shot actor motion (pure function of local frame). */
const animate = (id: string, i: number, lf: number, dur: number, base: Partial<CharacterProps>): Partial<CharacterProps> => {
  const p = lf / Math.max(1, dur - 1);
  switch (id) {
    case "sc2": return { x: (base.x as number) - lf * 0.9 };
    case "sc3": return { x: (base.x as number) - Math.min(lf, 60) * 0.7 };
    case "sc4": return i === 1 ? { feetY: (base.feetY as number) - Math.abs(Math.sin(lf * 0.25)) * 4, emotion: lf % 40 < 20 ? "smug" : "smug" } : {};
    case "sc6": return { x: (base.x as number) - lf * 9, feetY: (base.feetY as number) - Math.abs(Math.sin(lf * 0.8)) * 14 };
    case "sc8": return { x: (base.x as number) - lf * 3.5, arms: Math.floor(lf / 12) % 2 ? "point" : "down" };
    case "sc9": return { scale: 1.55 + (p > 0.55 ? ease((p - 0.55) / 0.2) * 0.1 : 0), emotion: p > 0.55 ? "caught" : "puzzled" };
    case "sc10": { const l = interpolate(lf, [26, 56], [0, 150], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }); return { lift: l, emotion: l > 20 ? "caught" : "neutral", arms: l > 100 ? "wave" : "down" }; }
    default: return {};
  }
};

const ShotView: React.FC<{ id: string; dur: number }> = ({ id, dur }) => {
  const lf = useCurrentFrame();
  const d = SHOTS[id];
  const cam = CAM[id] || { k: "none" };
  const p = ease(lf / Math.max(1, dur - 1));
  let plateT = "", actorT = "";
  if (cam.k === "push") { plateT = `scale(${(cam.a! + (cam.b! - cam.a!) * p).toFixed(4)})`; actorT = `scale(${(1 + (cam.b! - cam.a!) * 0.5 * p).toFixed(4)})`; }
  if (cam.k === "pan") { plateT = `scale(1.12) translateX(${(cam.dx! * 0.55 * (p - 0.5)).toFixed(2)}px)`; actorT = `translateX(${(cam.dx! * (p - 0.5)).toFixed(2)}px)`; }
  if (cam.k === "tilt") { plateT = `scale(1.2) translateY(${(cam.dy! * (0.5 - p)).toFixed(2)}px)`; actorT = ""; }
  const titleOp = id === "sc1" ? interpolate(lf, [9, 24, 66, 84], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) : 0;
  const popP = id === "sc9" ? Math.max(0, (lf - 20) / 7) : 0;
  const pop = popP > 0 ? (popP < 1 ? 1.4 - 0.4 * Math.min(1, popP) + (1 - popP) * 0.3 : 1) : 0;
  return (
    <AbsoluteFill style={{ backgroundColor: "#000", overflow: "hidden" }}>
      <Img src={staticFile(`${PUB}/plate_${d.plate}.png`)} style={{ position: "absolute", width: W, height: H, objectFit: "cover", transform: plateT, transformOrigin: "50% 62%", filter: d.blur ? `blur(${d.blur}px)` : undefined }} />
      <svg width={W} height={H} style={{ position: "absolute", inset: 0, transform: actorT, transformOrigin: "50% 80%" }}>
        {d.flatBuckets?.map((b, i) => {
          const bx = id === "sc7" ? 760 - p * 380 : b.x;
          const by = id === "sc7" ? b.feetY - Math.abs(Math.sin(lf * 0.5)) * 8 : b.feetY;
          return (<g key={i}><ellipse cx={bx} cy={by + 4} rx={70 * b.scale} ry={11 * b.scale} fill="rgba(0,0,0,0.32)" /><FlatBucket {...b} x={bx} feetY={by} /></g>);
        })}
        {d.actors?.map((a, i) => { const base = cast(a); const o = animate(id, i, lf, dur, base); const c = { ...base, ...o } as CharacterProps; return (<g key={i}><ellipse cx={c.x} cy={c.feetY + 6} rx={130 * (c.scale ?? 1)} ry={16 * (c.scale ?? 1)} fill="rgba(0,0,0,0.32)" /><Character {...c} t={lf} /></g>); })}
      </svg>
      <div style={{ position: "absolute", left: 0, right: 0, top: 1700, bottom: 0, background: "linear-gradient(to bottom, rgba(40,22,10,0) 0%, rgba(40,22,10,0.5) 100%)", filter: "blur(4px)" }} />
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at center, rgba(0,0,0,0) 55%, rgba(0,0,0,0.38) 100%)" }} />
      <Grain />
      {d.title && <div style={{ position: "absolute", left: 0, right: 0, top: 360, textAlign: "center", opacity: titleOp, fontFamily: "Georgia, serif", fontStyle: "italic", fontSize: 56, color: "#f6e7c4", textShadow: "0 3px 10px #000" }}>{d.title}</div>}
      {d.overlay && pop > 0 && <div style={{ position: "absolute", right: 70, top: 300, transform: `scale(${pop})`, transformOrigin: "right top", fontFamily: "Inter, sans-serif", fontWeight: 900, fontSize: 260, color: "#f0c43a", WebkitTextStroke: "12px #000", paintOrder: "stroke fill" }}>{d.overlay}</div>}
    </AbsoluteFill>
  );
};

/** Captions: one fixed layer above everything, hard swap, never animated. */
const Captions: React.FC = () => {
  const f = useCurrentFrame();
  const t = f / FPS;
  const c = CAPTIONS.find(([, a, b]) => t >= a && t < b);
  if (!c) return null;
  return (
    <div style={{ position: "absolute", left: 0, right: 0, top: 1772, textAlign: "center", fontFamily: "Inter, sans-serif", fontWeight: 900, fontSize: 84, color: "#fff", WebkitTextStroke: "11px #000", paintOrder: "stroke fill", letterSpacing: 1 }}>{c[0]}</div>
  );
};

export const Sampler: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: "#000" }}>
    {T.map(([id, a, b]) => (
      <Sequence key={id} from={Math.round(a * FPS)} durationInFrames={Math.round((b - a) * FPS)}>
        <ShotView id={id} dur={Math.round((b - a) * FPS)} />
      </Sequence>
    ))}
    <Captions />
  </AbsoluteFill>
);
