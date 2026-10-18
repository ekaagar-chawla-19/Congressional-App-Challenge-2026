// Illustrative terrain for the drawn (web) map: an elevation surface shaped by the landmarks
// (valleys along the streams, rising to the peaks and ridges), turned into contour lines with
// marching squares. It is NOT surveyed elevation data, just enough relief to read the landscape.

export type Pt = [number, number]; // metres east, north
export type Seg = [number, number, number, number]; // x1, y1, x2, y2 in metres

const segDist = (p: Pt, a: Pt, b: Pt) => {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy || 1)));
  return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
};
const lineDist = (p: Pt, line: Pt[]) => {
  let d = Infinity;
  for (let i = 1; i < line.length; i++) d = Math.min(d, segDist(p, line[i - 1], line[i]));
  return d;
};

export function terrain(streams: Pt[][], peaks: { at: Pt; big: boolean }[], ridges: Pt[][],
  box: { x0: number; x1: number; y0: number; y1: number }, step = 20, n = 72) {
  const pad = 400;
  const x0 = box.x0 - pad, y0 = box.y0 - pad, w = box.x1 - box.x0 + 2 * pad, h = box.y1 - box.y0 + 2 * pad;
  const elev = (p: Pt) => {
    const d = streams.length ? Math.min(...streams.map((l) => lineDist(p, l))) : 400;
    let e = 650 + 0.04 * (p[0] - x0) + 150 * (1 - Math.exp(-d / 260)); // valley floor rising upstream (east)
    for (const k of peaks) e += (k.big ? 320 : 200) * Math.exp(-((p[0] - k.at[0]) ** 2 + (p[1] - k.at[1]) ** 2) / (2 * 480 ** 2));
    for (const r of ridges) e += 170 * Math.exp(-(lineDist(p, r) ** 2) / (2 * 380 ** 2));
    return e + 6 * Math.sin(p[0] / 97) * Math.cos(p[1] / 131);
  };
  const gx = (i: number) => x0 + (w * i) / n, gy = (j: number) => y0 + (h * j) / n;
  const z: number[][] = [];
  let lo = Infinity, hi = -Infinity;
  for (let j = 0; j <= n; j++) {
    z.push([]);
    for (let i = 0; i <= n; i++) {
      const v = elev([gx(i), gy(j)]);
      z[j].push(v);
      lo = Math.min(lo, v);
      hi = Math.max(hi, v);
    }
  }
  const minor: Seg[] = [], index: Seg[] = [];
  for (let level = Math.ceil(lo / step) * step; level <= hi; level += step) {
    const out = level % 100 === 0 ? index : minor;
    for (let j = 0; j < n; j++) {
      for (let i = 0; i < n; i++) {
        const c = [z[j][i], z[j][i + 1], z[j + 1][i + 1], z[j + 1][i]]; // corners counter-clockwise
        const p: Pt[] = [[gx(i), gy(j)], [gx(i + 1), gy(j)], [gx(i + 1), gy(j + 1)], [gx(i), gy(j + 1)]];
        const cross: Pt[] = [];
        for (let k = 0; k < 4; k++) {
          const a = c[k], b = c[(k + 1) % 4];
          if ((a < level) !== (b < level)) {
            const t = (level - a) / (b - a);
            const [pa, pb] = [p[k], p[(k + 1) % 4]];
            cross.push([pa[0] + t * (pb[0] - pa[0]), pa[1] + t * (pb[1] - pa[1])]);
          }
        }
        if (cross.length >= 2) out.push([cross[0][0], cross[0][1], cross[1][0], cross[1][1]]);
        if (cross.length === 4) out.push([cross[2][0], cross[2][1], cross[3][0], cross[3][1]]);
      }
    }
  }
  return { minor, index, low: lo, high: hi };
}
