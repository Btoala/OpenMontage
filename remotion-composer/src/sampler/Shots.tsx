import React from "react";
import { AbsoluteFill, Img, staticFile, useCurrentFrame } from "remotion";
import { Character, COLORS, FlatBucket, CharacterProps } from "./Characters";

const W = 1080;
const H = 1920;
const PUB = "hard-hat-history-sampler";

export type Actor = Partial<CharacterProps> & { who: "guard" | "thief" | "sheriff" | "shop" };
export type ShotDef = {
  plate: string; blur?: number; caption: string; overlay?: string; title?: string;
  actors?: Actor[]; flatBuckets?: { x: number; feetY: number; scale: number; boots?: boolean; silhouette?: boolean }[];
  /** representative frame (30fps) inside the shot */ frame: number;
};

export const cast = (a: Actor) => {
  const c = COLORS[a.who];
  const hat = a.hat ?? (a.who === "guard" ? "cap" : a.who === "sheriff" ? "sheriff" : a.who === "thief" ? "flatcap" : "none");
  return { body: c.body, trim: c.trim, hatColor: c.hat, hat, x: 540, feetY: 1600, ...a } as CharacterProps;
};

export const SHOTS: Record<string, ShotDef> = {
  sc1: { plate: "sc1", caption: "This bucket", title: "Mudlow: population nervous", frame: 30 },
  sc2: { plate: "sc2", caption: "Mudlow's only guard", frame: 30, actors: [{ who: "guard", x: 440, feetY: 1236, scale: 0.2, emotion: "neutral" }] },
  sc3: { plate: "sc3", caption: "was terrified", frame: 24, actors: [{ who: "guard", x: 330, feetY: 1610, scale: 1, emotion: "scared", arms: "up" }] },
  sc4: { plate: "sc4", caption: "So the thief", frame: 30, actors: [
    { who: "shop", x: 770, feetY: 1500, scale: 0.78, emotion: "deadpan", apron: "#e9e2cf" },
    { who: "thief", x: 320, feetY: 1800, scale: 0.95, emotion: "smug", arms: "point" }] },
  sc5: { plate: "sc5", caption: "bought forty.", frame: 30 },
  sc6: { plate: "sc6", caption: "had fled screaming.", frame: 30, actors: [{ who: "guard", x: 360, feetY: 1430, scale: 0.42, emotion: "scared", arms: "flail", flip: true }] },
  sc7: { plate: "sc7", caption: "By noon,", frame: 30, flatBuckets: [{ x: 540, feetY: 1460, scale: 1.1, silhouette: true, boots: true }] },
  sc8: { plate: "sc8", caption: "The sheriff counted", frame: 30, actors: [{ who: "sheriff", x: 700, feetY: 1560, scale: 0.6, emotion: "puzzled", arms: "point" }] },
  sc9: { plate: "sc9", blur: 7, caption: "forty-one buckets.", overlay: "41", frame: 30, actors: [{ who: "sheriff", x: 520, feetY: 1960, scale: 1.55, emotion: "puzzled", arms: "down" }] },
  sc10: { plate: "sc9", blur: 7, caption: "The last one", frame: 40, flatBuckets: [
    { x: 160, feetY: 1760, scale: 0.8 }, { x: 330, feetY: 1760, scale: 0.8 }, { x: 750, feetY: 1760, scale: 0.8 }, { x: 920, feetY: 1760, scale: 0.8 }],
    actors: [{ who: "thief", x: 540, feetY: 1800, scale: 0.95, emotion: "caught", arms: "wave", hat: "bucket", lift: 110 }] },
  sc11: { plate: "sc9", blur: 9, caption: "Bucket.", frame: 60, actors: [{ who: "thief", x: 540, feetY: 2050, scale: 1.75, emotion: "deadpan", arms: "down", hat: "none" }] },
};

export const Grain: React.FC = () => (
  <svg width={W} height={H} style={{ position: "absolute", inset: 0, mixBlendMode: "overlay", opacity: 0.1 }}>
    <filter id="g"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed={7} stitchTiles="stitch" /></filter>
    <rect width={W} height={H} filter="url(#g)" />
  </svg>
);

/** One shot. Layer order: plate > contact shadow > actors/props > foreground > grade > caption. */
export const Shot: React.FC<{ id: string; frameOverride?: number }> = ({ id, frameOverride }) => {
  const f = useCurrentFrame();
  const d = SHOTS[id];
  const t = frameOverride ?? (f || d.frame);
  return (
    <AbsoluteFill style={{ backgroundColor: "#000", overflow: "hidden" }}>
      <Img src={staticFile(`${PUB}/plate_${d.plate}.png`)} style={{ position: "absolute", width: W, height: H, objectFit: "cover", filter: d.blur ? `blur(${d.blur}px)` : undefined }} />
      <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
        {d.flatBuckets?.map((b, i) => (<g key={i}><ellipse cx={b.x} cy={b.feetY + 4} rx={70 * b.scale} ry={11 * b.scale} fill="rgba(0,0,0,0.32)" /><FlatBucket {...b} /></g>))}
        {d.actors?.map((a, i) => { const p = cast(a); return (<g key={i}><ellipse cx={p.x} cy={p.feetY + 6} rx={130 * (p.scale ?? 1)} ry={16 * (p.scale ?? 1)} fill="rgba(0,0,0,0.32)" /><Character {...p} t={t} /></g>); })}
      </svg>
      <div style={{ position: "absolute", left: 0, right: 0, top: 1700, bottom: 0, background: "linear-gradient(to bottom, rgba(40,22,10,0) 0%, rgba(40,22,10,0.5) 100%)", filter: "blur(4px)" }} />
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at center, rgba(0,0,0,0) 55%, rgba(0,0,0,0.38) 100%)" }} />
      <Grain />
      {d.title && <div style={{ position: "absolute", left: 0, right: 0, top: 360, textAlign: "center", fontFamily: "Georgia, serif", fontStyle: "italic", fontSize: 56, color: "#f6e7c4", textShadow: "0 3px 10px #000" }}>{d.title}</div>}
      {d.overlay && <div style={{ position: "absolute", right: 70, top: 300, fontFamily: "Inter, sans-serif", fontWeight: 900, fontSize: 260, color: "#f0c43a", WebkitTextStroke: "12px #000", paintOrder: "stroke fill" }}>{d.overlay}</div>}
      <div style={{ position: "absolute", left: 0, right: 0, top: 1772, textAlign: "center", fontFamily: "Inter, sans-serif", fontWeight: 900, fontSize: 84, color: "#fff", WebkitTextStroke: "11px #000", paintOrder: "stroke fill", letterSpacing: 1 }}>{d.caption}</div>
    </AbsoluteFill>
  );
};

/** All 11 shots tiled at 1/3 scale (6 x 2 grid, 2160 x 1280) for asset review. */
export const ContactSheet: React.FC = () => {
  const ids = Object.keys(SHOTS);
  return (
    <AbsoluteFill style={{ backgroundColor: "#141414" }}>
      {ids.map((id, i) => (
        <div key={id} style={{ position: "absolute", left: (i % 6) * 360, top: Math.floor(i / 6) * 640, width: 360, height: 640, overflow: "hidden" }}>
          <div style={{ width: W, height: H, transform: "scale(0.3333)", transformOrigin: "top left" }}>
            <Shot id={id} frameOverride={SHOTS[id].frame} />
          </div>
          <div style={{ position: "absolute", left: 8, top: 6, color: "#fff", fontFamily: "Inter", fontWeight: 800, fontSize: 22, textShadow: "0 1px 4px #000" }}>{id}</div>
        </div>
      ))}
    </AbsoluteFill>
  );
};

export const ShotPreview: React.FC<{ id: string }> = ({ id }) => <Shot id={id} />;
