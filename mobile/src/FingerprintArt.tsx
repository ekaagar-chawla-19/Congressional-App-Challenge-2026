import { View } from 'react-native';
import Svg, { Circle, G, Line, Path, Rect } from 'react-native-svg';
import { color } from './theme';

// Illustrations for "How HemlockID thinks": drawn, not real data. Bark is a few dozen wavy vertical ridges
// from a seeded random generator, so the "same tree" panels share ridges and features exactly.

const rand = (seed: number) => () => ((seed = (seed * 16807) % 2147483647) - 1) / 2147483646;

function ridges(seed: number, w: number, h: number) {
  const r = rand(seed);
  const out: { d: string; width: number; tone: string }[] = [];
  const tones = ['#5B4636', '#6E5643', '#3F3127', '#7D6450'];
  for (let x = -6; x < w + 6; x += 6 + r() * 7) {
    let d = `M ${x.toFixed(1)} -4`;
    let cx = x;
    for (let y = 0; y <= h + 8; y += 14) {
      cx += (r() - 0.5) * 7;
      d += ` L ${cx.toFixed(1)} ${y}`;
    }
    out.push({ d, width: 1.5 + r() * 3.5, tone: tones[Math.floor(r() * tones.length)] });
  }
  return out;
}

// distinctive spots (lenticels, cracks) at fixed places of one tree's bark
function features(seed: number, w: number, h: number, n = 7) {
  const r = rand(seed * 7 + 3);
  return Array.from({ length: n }, () => ({ x: 12 + r() * (w - 24), y: 14 + r() * (h - 28), rad: 2.5 + r() * 2.5 }));
}

export function Bark({ seed, w, h, shift = 0, grid, marks }: { seed: number; w: number; h: number; shift?: number; grid?: boolean; marks?: boolean }) {
  return (
    <Svg width={w} height={h} viewBox={`${shift} 0 ${w} ${h}`}>
      <Rect x={shift - 10} y={0} width={w + 20} height={h} fill="#8A735E" />
      {ridges(seed, w + 40, h).map((p, i) => <Path key={i} d={p.d} stroke={p.tone} strokeWidth={p.width} fill="none" strokeLinecap="round" />)}
      {marks && features(seed, w + 40, h).map((f, i) => <Circle key={i} cx={f.x} cy={f.y} r={f.rad} fill="#2C221B" stroke="#E8D9C4" strokeWidth={1} />)}
      {grid && (
        <G opacity={0.55}>
          {[1, 2, 3].map((k) => <Line key={`v${k}`} x1={shift + (w * k) / 4} y1={0} x2={shift + (w * k) / 4} y2={h} stroke={color.paper} strokeWidth={1} />)}
          {[1, 2, 3].map((k) => <Line key={`h${k}`} x1={shift} y1={(h * k) / 4} x2={shift + w} y2={(h * k) / 4} stroke={color.paper} strokeWidth={1} />)}
        </G>
      )}
    </Svg>
  );
}

// The fingerprint: a strip of numbers drawn as bars (the real one has 256 or 384 values).
export function Fingerprint({ seed, w, h, tint = color.live }: { seed: number; w: number; h: number; tint?: string }) {
  const r = rand(seed + 11);
  const n = 32;
  const bw = w / n;
  return (
    <Svg width={w} height={h}>
      {Array.from({ length: n }, (_, i) => {
        const v = 0.15 + r() * 0.85;
        return <Rect key={i} x={i * bw + 1} y={h - v * h} width={bw - 2} height={v * h} rx={1.5} fill={tint} />;
      })}
    </Svg>
  );
}

// Two photos of the same tree (the second taken from slightly to the side) with matching features joined.
export function MatchPair({ w, h, seed = 17 }: { w: number; h: number; seed?: number }) {
  const gap = 18;
  const pw = (w - gap) / 2;
  const shift = 14; // the second photo sees the bark a little further right
  const f = features(seed, pw + 40, h).filter((p) => p.x > shift + 6 && p.x < pw - 6);
  const lines = ['#8FB08A', '#E0B15A', '#9EC5E8', '#F2A68C', '#C9A8E8', '#F4E28C', '#A8E0D0'];
  return (
    <View style={{ width: w, height: h }}>
      <View style={{ flexDirection: 'row', gap }}>
        <View style={{ borderRadius: 14, overflow: 'hidden' }}><Bark seed={seed} w={pw} h={h} marks /></View>
        <View style={{ borderRadius: 14, overflow: 'hidden' }}><Bark seed={seed} w={pw} h={h} shift={shift} marks /></View>
      </View>
      <Svg width={w} height={h} style={{ position: 'absolute', left: 0, top: 0 }}>
        {f.map((p, i) => (
          <G key={i}>
            <Line x1={p.x} y1={p.y} x2={pw + gap + p.x - shift} y2={p.y} stroke={lines[i % lines.length]} strokeWidth={2} strokeDasharray="5 3" />
            <Circle cx={p.x} cy={p.y} r={5} fill="none" stroke={lines[i % lines.length]} strokeWidth={2} />
            <Circle cx={pw + gap + p.x - shift} cy={p.y} r={5} fill="none" stroke={lines[i % lines.length]} strokeWidth={2} />
          </G>
        ))}
      </Svg>
    </View>
  );
}
