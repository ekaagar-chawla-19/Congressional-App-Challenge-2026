// base64 <-> bytes / float32 fingerprints without atob, btoa or Buffer (same on Hermes, browsers and Node).
const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
export function bytesFromBase64(b64: string): Uint8Array {
  const clean = b64.replace(/[^A-Za-z0-9+/]/g, '');
  const out = new Uint8Array(Math.floor((clean.length * 3) / 4));
  let bits = 0, n = 0, o = 0;
  for (let i = 0; i < clean.length; i++) {
    bits = (bits << 6) | B64.indexOf(clean[i]); n += 6;
    if (n >= 8) { n -= 8; out[o++] = (bits >> n) & 0xff; }
  }
  return out.subarray(0, o);
}

/** float32 little-endian -> base64: the gallery's fingerprint format (same as the server's GET /gallery). */
export function encodeEmbedding(e: Float32Array): string {
  const u8 = new Uint8Array(e.buffer, e.byteOffset, e.byteLength);
  let s = '';
  for (let i = 0; i < u8.length; i += 3) {
    const n = (u8[i] << 16) | ((u8[i + 1] ?? 0) << 8) | (u8[i + 2] ?? 0);
    s += B64[(n >> 18) & 63] + B64[(n >> 12) & 63] + (i + 1 < u8.length ? B64[(n >> 6) & 63] : '=') + (i + 2 < u8.length ? B64[n & 63] : '=');
  }
  return s;
}
