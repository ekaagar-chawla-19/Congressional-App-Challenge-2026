import { useEffect, useMemo, useRef, useState } from 'react';
import { PanResponder, Pressable, StyleSheet, View, type LayoutChangeEvent } from 'react-native';
import Svg, { Circle, G, Path, Polyline, Rect, Text as SvgText } from 'react-native-svg';
import { Minus, Plus, Scan as Fit } from './icons';
import { hotspotColor, LANDMARK_STYLE, pinColor, type MapProps } from './mapTypes';
import { color, font, radius } from './theme';
import { Icon, T } from './ui';

export type { MapProps } from './mapTypes';

// Browser map (react-native-maps is native only): a drawn terrain map in metres around the forest,
// with streams, ridges, trails, peaks with contour lines, a canopy of background trees, sections,
// disease hotspots and the hemlocks. Drag to pan, buttons (or mouse wheel) to zoom.
const M = 111_320;

export default function MapCanvas({ trees, landmarks, sections, showSections, hotspots, layer, selected, onSelect, onView }: MapProps) {
  const [size, setSize] = useState({ w: 390, h: 700 });
  const pts = useMemo(() => {
    const all: [number, number][] = trees.map((t) => [t.lng!, t.lat!]);
    for (const l of landmarks) {
      if (l.geometry.type === 'Point') all.push(l.geometry.coordinates);
      else all.push(...l.geometry.coordinates);
    }
    return all;
  }, [trees, landmarks]);
  const lat0 = pts.reduce((a, p) => a + p[1], 0) / pts.length;
  const lon0 = pts.reduce((a, p) => a + p[0], 0) / pts.length;
  const kx = M * Math.cos((lat0 * Math.PI) / 180);
  const X = (lon: number) => (lon - lon0) * kx;
  const Y = (lat: number) => (lat - lat0) * M;
  const xs = pts.map((p) => X(p[0]));
  const ys = pts.map((p) => Y(p[1]));
  const ext = { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) };
  // (a hidden tab measures 0 x 0: keep the scale positive)
  const fit = Math.max(1e-3, Math.min(size.w / Math.max(ext.x1 - ext.x0, 100), Math.max(size.h - 220, 100) / Math.max(ext.y1 - ext.y0, 100)) * 0.92);
  const home = { cx: (ext.x0 + ext.x1) / 2, cy: (ext.y0 + ext.y1) / 2 - 40 / fit };
  // Pan offset (metres from home) and zoom; home moves when data arrives, the offset stays.
  const [off, setView] = useState({ dx: 0, dy: 0, z: 1 });
  const view = { cx: home.cx + off.dx, cy: home.cy + off.dy, z: off.z };

  const s = fit * view.z; // px per metre
  const sx = (x: number) => size.w / 2 + (x - view.cx) * s;
  const sy = (y: number) => size.h / 2 - (y - view.cy) * s;

  // visible area in lon/lat, for "Analyze this view"
  useEffect(() => {
    const hw = size.w / 2 / s, hh = size.h / 2 / s;
    onView([lon0 + (view.cx - hw) / kx, lat0 + (view.cy - hh) / M, lon0 + (view.cx + hw) / kx, lat0 + (view.cy + hh) / M]);
  }, [view.cx, view.cy, size, s, lon0, lat0, kx, onView]);

  const offRef = useRef(off);
  useEffect(() => void (offRef.current = off), [off]);
  const drag = useRef({ dx: 0, dy: 0 });
  // The refs are only read inside the gesture callbacks, never while rendering.
  // eslint-disable-next-line react-hooks/refs
  const pan = useMemo(() => PanResponder.create({
    onMoveShouldSetPanResponder: (_, g) => Math.abs(g.dx) + Math.abs(g.dy) > 4,
    onPanResponderGrant: () => void (drag.current = { dx: offRef.current.dx, dy: offRef.current.dy }),
    onPanResponderMove: (_, g) =>
      setView((v) => ({ ...v, dx: drag.current.dx - g.dx / (fit * v.z), dy: drag.current.dy + g.dy / (fit * v.z) })),
  }), [fit]);
  const zoom = (f: number) => setView((v) => ({ ...v, z: Math.min(12, Math.max(0.6, v.z * f)) }));

  // Background canopy: deterministic scatter of non-hemlock trees (hardwoods and pines).
  const canopy = useMemo(() => {
    const u = lcg(11, 900 * 4);
    const pad = 300;
    return Array.from({ length: 900 }, (_, i) => ({
      x: ext.x0 - pad + u[4 * i] * (ext.x1 - ext.x0 + 2 * pad), y: ext.y0 - pad + u[4 * i + 1] * (ext.y1 - ext.y0 + 2 * pad),
      r: 5 + u[4 * i + 2] * 9, c: ['#B9CBA9', '#AFC39E', '#C4D3B4', '#A6BC95'][Math.floor(u[4 * i + 3] * 4)],
    }));
  }, [ext.x0, ext.x1, ext.y0, ext.y1]);

  const line = (c: [number, number][]) => c.map(([lo, la]) => `${sx(X(lo))},${sy(Y(la))}`).join(' ');
  const box = ([w, so, e, n]: number[]) => ({ x: sx(X(w)), y: sy(Y(n)), width: (X(e) - X(w)) * s, height: (Y(n) - Y(so)) * s });
  const bar = [50, 100, 200, 500, 1000, 2000].find((m) => m * s > 70) ?? 2000;
  const peaks = landmarks.filter((l) => l.properties.kind === 'peak');

  return (
    <View style={st.field} onLayout={(e: LayoutChangeEvent) => setSize({ w: e.nativeEvent.layout.width, h: e.nativeEvent.layout.height })}
      {...pan.panHandlers}
      // @ts-expect-error onWheel exists on web only
      onWheel={(e: { deltaY: number }) => zoom(e.deltaY < 0 ? 1.15 : 1 / 1.15)}>
      <Svg width={size.w} height={size.h}>
        <Rect x={0} y={0} width={size.w} height={size.h} fill="#CFDDC2" />
        <G>
          {canopy.map((c, i) => <Circle key={i} cx={sx(c.x)} cy={sy(c.y)} r={Math.max(1.5, c.r * s)} fill={c.c} />)}
        </G>
        {peaks.map((p) => {
          const [lo, la] = p.geometry.coordinates as [number, number];
          return (
            <G key={p.properties.name}>
              {[520, 400, 290, 190, 100].map((rad, i) => (
                <Path key={rad} fill={i === 4 ? '#D9C9A8' : 'none'} stroke="#9C8460" strokeOpacity={0.45} strokeWidth={1}
                  d={blob(sx(X(lo)), sy(Y(la)), rad * s, rad * 0.75 * s, i)} />
              ))}
            </G>
          );
        })}
        {landmarks.filter((l) => l.geometry.type === 'LineString').map((l) => {
          const k = l.properties.kind as keyof typeof LANDMARK_STYLE;
          const style = LANDMARK_STYLE[k] ?? LANDMARK_STYLE.trail;
          const main = l.properties.name === 'Cooper Creek';
          return (
            <Polyline key={l.properties.name} points={line(l.geometry.coordinates as [number, number][])} fill="none"
              stroke={style.color} strokeWidth={(main ? 1.6 : 1) * style.width * Math.min(2, Math.max(1, view.z / 1.5))}
              strokeDasharray={k === 'trail' ? '6 4' : k === 'ridge' ? '2 3' : undefined} strokeLinecap="round" strokeLinejoin="round" />
          );
        })}
        {showSections && sections.map((sec) => {
          const b = box(sec.bbox);
          return (
            <G key={sec.section_id}>
              <Rect {...b} fill="rgba(30,59,50,0.05)" stroke={color.spruce} strokeWidth={1.5} strokeDasharray="5 4" />
              <SvgText x={b.x + 6} y={b.y + 14} fill={color.spruce} fontSize={11} fontWeight="600">{sec.name}</SvgText>
            </G>
          );
        })}
        {hotspots.map((h, i) => {
          const b = box(h.bbox);
          return (
            <G key={h.zone_id}>
              <Rect {...b} fill={hotspotColor(layer) + '30'} stroke={hotspotColor(layer)} strokeWidth={2} rx={4} />
              <SvgText x={b.x + b.width - 4} y={b.y + 13} textAnchor="end" fill={hotspotColor(layer)} fontSize={11} fontWeight="700">{`#${i + 1}`}</SvgText>
            </G>
          );
        })}
        {landmarks.map((l) => {
          const [lo, la] = l.geometry.type === 'Point' ? l.geometry.coordinates
            : l.geometry.coordinates[Math.floor(l.geometry.coordinates.length * (l.properties.kind === 'stream' ? 0.35 : 0.5))];
          const peak = l.properties.kind === 'peak';
          const props = {
            x: sx(X(lo)), y: sy(Y(la)) + (peak ? -8 : -6), textAnchor: 'middle' as const, fontSize: peak ? 12 : 10,
            fontWeight: peak ? '700' : '500', fontStyle: l.properties.kind === 'stream' ? ('italic' as const) : ('normal' as const),
          };
          const text = `${peak ? '▲ ' : ''}${l.properties.name}`;
          return (
            <G key={`t${l.properties.name}`}>
              <SvgText {...props} fill="#F3F1E8" stroke="#F3F1E8" strokeWidth={3}>{text}</SvgText>
              <SvgText {...props} fill={l.properties.kind === 'stream' ? '#2F5F8A' : '#5B4630'}>{text}</SvgText>
            </G>
          );
        })}
      </Svg>
      {/* Pins are plain views: SVG press handlers are not supported on web. */}
      {trees.map((t) => {
        const on = t.id === selected;
        const r = on ? 12 : 9;
        return (
          <Pressable key={t.id} onPress={() => onSelect(t.id)} accessibilityLabel={`Tree ${t.id}`}
            style={[st.pin, { left: sx(X(t.lng!)) - r, top: sy(Y(t.lat!)) - r, width: 2 * r, height: 2 * r, borderColor: on ? color.ink : '#7E8B80', borderWidth: on ? 2 : 1, zIndex: on ? 3 : 2 }]}>
            <View style={{ width: on ? 14 : 10, height: on ? 14 : 10, borderRadius: 7, backgroundColor: pinColor(t, layer) }} />
          </Pressable>
        );
      })}

      <View style={st.controls}>
        <Pressable style={st.btn} onPress={() => zoom(1.5)} accessibilityLabel="Zoom in"><Icon as={Plus} /></Pressable>
        <Pressable style={st.btn} onPress={() => zoom(1 / 1.5)} accessibilityLabel="Zoom out"><Icon as={Minus} /></Pressable>
        <Pressable style={st.btn} onPress={() => setView({ dx: 0, dy: 0, z: 1 })} accessibilityLabel="Show all trees"><Icon as={Fit} /></Pressable>
      </View>
      <View style={st.scale} pointerEvents="none">
        <View style={{ width: bar * s, height: 4, backgroundColor: color.ink, borderRadius: 2 }} />
        <T v="caption" c={color.ink} style={{ fontSize: 11, fontFamily: font.semibold }}>{bar >= 1000 ? `${bar / 1000} km` : `${bar} m`}</T>
        <T v="caption" c={color.inkSoft} style={{ fontSize: 10 }}>Landmarks approximate</T>
      </View>
    </View>
  );
}

// n deterministic pseudo-random numbers in [0, 1).
function lcg(seed: number, n: number) {
  const out = new Array<number>(n);
  let r = seed;
  for (let i = 0; i < n; i++) {
    r = (r * 16807) % 2147483647;
    out[i] = (r - 1) / 2147483646;
  }
  return out;
}

// Slightly irregular closed contour around a peak.
function blob(cx: number, cy: number, rx: number, ry: number, seed: number) {
  const n = 18;
  const p = Array.from({ length: n }, (_, i) => {
    const a = (i / n) * Math.PI * 2;
    const k = 1 + 0.08 * Math.sin(a * 3 + seed) + 0.05 * Math.cos(a * 5 + seed * 2);
    return [cx + Math.cos(a) * rx * k, cy + Math.sin(a) * ry * k];
  });
  return `M${p.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' L')} Z`;
}

const st = StyleSheet.create({
  field: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, overflow: 'hidden', backgroundColor: '#CFDDC2', cursor: 'grab' } as object,
  pin: { position: 'absolute', borderRadius: 999, backgroundColor: '#FFFFFF', alignItems: 'center', justifyContent: 'center' },
  controls: { position: 'absolute', right: 16, top: 120, gap: 8 },
  btn: { width: 44, height: 44, borderRadius: radius.sm, backgroundColor: color.card, borderWidth: 1, borderColor: color.line, alignItems: 'center', justifyContent: 'center' },
  scale: { position: 'absolute', left: 16, bottom: 200, gap: 3 },
});
