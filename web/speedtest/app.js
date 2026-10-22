import { MODELS, cosine, decode, download, embed, hasWebGPU, load, threads } from '../lib/engine.js';

const $ = (id) => document.getElementById(id);
const base = new URL('../', import.meta.url);
const CACHE = 'hemlockid-v1';
const report = { results: {}, mine: {}, notes: [] };
const bytes = {}; // model files held in memory after Step 1
let backend = 'auto';

// The service worker keeps everything for offline use. The first visit reloads once so the page is
// cross-origin isolated (multi-threaded WebAssembly) and fully served by the worker.
if ('serviceWorker' in navigator) {
  const first = !navigator.serviceWorker.controller;
  navigator.serviceWorker.register(new URL('sw.js', base), { scope: base.pathname }).catch((e) => report.notes.push(`service worker: ${e.message}`));
  if (first) {
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      let again = false;
      try { again = sessionStorage.getItem('hid-reloaded') === '1'; sessionStorage.setItem('hid-reloaded', '1'); } catch { /* private mode */ }
      if (!again) location.reload();
    });
  }
}

const fmtMs = (ms) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`);
const mb = (n) => `${(n / 1e6).toFixed(0)} MB`;
const row = (k, v) => `<div class="row"><span>${k}</span><span>${v}</span></div>`;
const pill = (ok, yes, no) => `<span class="pill ${ok ? 'good' : 'bad'}">${ok ? yes : no}</span>`;

async function cached(path) {
  try {
    return !!(await (await caches.open(CACHE)).match(new URL(path, base).href));
  } catch {
    return false;
  }
}

async function refreshOffline() {
  const sw = !!navigator.serviceWorker?.controller;
  const models = (await Promise.all(Object.values(MODELS).map((m) => cached(m.url)))).every(Boolean);
  const ok = sw && models;
  $('offline').innerHTML = ok ? '<span class="pill good">Yes</span>'
    : `<span class="pill warn">${!sw ? 'Reload once' : 'Save models first'}</span>`;
  report.offlineReady = ok;
  $('run').disabled = !(models || Object.keys(bytes).length === 2);
  $('pick').disabled = $('run').disabled;
  if (models) {
    $('download').textContent = 'Saved on this phone';
    $('download').disabled = true;
  }
  return ok;
}

async function getModel(m, onProgress) {
  if (!bytes[m.key]) bytes[m.key] = await download(new URL(m.url, base).href, onProgress);
  return bytes[m.key];
}

$('download').onclick = async () => {
  $('download').disabled = true;
  try { report.persisted = await navigator.storage?.persist?.(); } catch { /* not supported */ }
  const box = $('dl');
  box.innerHTML = Object.values(MODELS).map((m) => `<div style="display:grid;gap:6px"><div class="row small"><span>${m.name}</span><span id="p-${m.key}">0%</span></div><div class="bar"><i id="b-${m.key}"></i></div></div>`).join('');
  try {
    for (const m of Object.values(MODELS)) {
      const t = performance.now();
      await getModel(m, (got, total) => {
        const pct = total ? Math.round((100 * got) / total) : 0;
        $(`b-${m.key}`).style.width = `${pct}%`;
        $(`p-${m.key}`).textContent = total ? `${pct}% · ${mb(got)}` : mb(got);
      });
      report.results[m.key] = { ...(report.results[m.key] || {}), download: fmtMs(performance.now() - t) };
      $(`p-${m.key}`).textContent = `Saved · ${mb(bytes[m.key].length)}`;
    }
  } catch (e) {
    box.insertAdjacentHTML('beforeend', `<p class="pill bad">${e.message}</p>`);
    $('download').disabled = false;
  }
  await refreshOffline();
  showDevice();
};

document.querySelectorAll('[data-backend]').forEach((b) => {
  b.onclick = () => {
    backend = b.dataset.backend;
    document.querySelectorAll('[data-backend]').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
  };
});

async function sample() {
  const [img, ref] = await Promise.all([
    fetch(new URL('speedtest/sample.jpg', base)).then((r) => r.blob()),
    fetch(new URL('speedtest/reference.json', base)).then((r) => r.json()),
  ]);
  return { blob: img, ref };
}

$('run').onclick = async () => {
  $('run').disabled = true;
  const box = $('results');
  box.innerHTML = '';
  try {
    const { blob, ref } = await sample();
    const t0 = performance.now();
    const img = await decode(blob);
    const decodeMs = performance.now() - t0;
    for (const m of Object.values(MODELS)) {
      box.insertAdjacentHTML('beforeend', `<div id="r-${m.key}" style="display:grid;gap:6px"><h2>${m.name}</h2><p class="soft small">Loading…</p></div>`);
      const el = $(`r-${m.key}`);
      try {
        let t = performance.now();
        const file = await getModel(m);
        const readMs = performance.now() - t;
        t = performance.now();
        const loaded = await load(m, file, backend);
        const createMs = performance.now() - t;
        el.querySelector('p').textContent = `Running on ${loaded.backend}…`;
        await embed(loaded, img); // warm-up: the first run compiles the GPU programs
        const runs = [];
        let out;
        for (let i = 0; i < 3; i++) {
          t = performance.now();
          out = await embed(loaded, img);
          runs.push(performance.now() - t);
        }
        await loaded.session.release();
        const per = runs.reduce((a, b) => a + b, 0) / runs.length;
        const sim = cosine(out.embedding, ref[m.key].embedding);
        const same = sim >= 0.99;
        const r = {
          backend: loaded.backend, read: fmtMs(readMs), start: fmtMs(createMs), perPhoto: fmtMs(per),
          scan3: fmtMs(3 * (per + decodeMs)), similarity: sim.toFixed(4), sameAsServer: same,
          ...(out.hemlock != null ? { hemlock: out.hemlock.toFixed(3), serverHemlock: ref.delta.hemlock_probability.toFixed(3) } : {}),
        };
        report.results[m.key] = { ...(report.results[m.key] || {}), ...r };
        el.innerHTML = `<h2>${m.name}</h2>` + row('Runs on', loaded.backend) + row('Start-up', r.start)
          + row('Per photo', r.perPhoto) + row('3-photo scan', `about ${r.scan3}`)
          + row('Matches the server', pill(same, `Yes · ${(100 * sim).toFixed(1)}%`, `No · ${(100 * sim).toFixed(1)}%`))
          + (out.hemlock != null ? row('Hemlock check', `${Math.round(100 * out.hemlock)}% (server ${Math.round(100 * ref.delta.hemlock_probability)}%)`) : '');
      } catch (e) {
        report.results[m.key] = { ...(report.results[m.key] || {}), error: String(e?.message || e) };
        el.innerHTML = `<h2>${m.name}</h2><p class="pill bad">Failed: ${String(e?.message || e)}</p>`;
      }
      box.insertAdjacentHTML('beforeend', '<hr>');
    }
    box.lastElementChild?.remove();
  } finally {
    $('run').disabled = false;
    showDevice();
  }
};

$('pick').onclick = () => $('photo').click();
$('photo').onchange = async () => {
  const f = $('photo').files?.[0];
  if (!f) return;
  const box = $('mine');
  box.innerHTML = '<p class="soft small">Working…</p>';
  $('pick').disabled = true;
  try {
    let t = performance.now();
    const img = await decode(f);
    const decodeMs = performance.now() - t;
    let html = row('Photo', `${img.w}×${img.h} after decoding`) + row('Decoding', fmtMs(decodeMs));
    report.mine = { size: `${img.w}x${img.h}`, decode: fmtMs(decodeMs) };
    for (const m of Object.values(MODELS)) {
      const loaded = await load(m, await getModel(m), backend);
      await embed(loaded, img);
      t = performance.now();
      const out = await embed(loaded, img);
      const ms = performance.now() - t;
      await loaded.session.release();
      report.mine[m.key] = fmtMs(ms);
      html += row(m.name, fmtMs(ms));
      if (out.hemlock != null) {
        report.mine.hemlock = out.hemlock.toFixed(3);
        html += row('Hemlock check (Delta)', `${Math.round(100 * out.hemlock)}%`);
      }
    }
    box.innerHTML = html;
  } catch (e) {
    box.innerHTML = `<p class="pill bad">Failed: ${String(e?.message || e)}</p>`;
  } finally {
    $('pick').disabled = false;
    $('photo').value = '';
  }
};

async function showDevice() {
  let est = null;
  try { est = await navigator.storage?.estimate?.(); } catch { /* not supported */ }
  try { report.persisted ??= await navigator.storage?.persisted?.(); } catch { /* not supported */ }
  report.device = {
    browser: navigator.userAgent, webgpu: hasWebGPU(), threads: threads(), isolated: !!globalThis.crossOriginIsolated,
    standalone: matchMedia('(display-mode: standalone)').matches || navigator.standalone === true,
    online: navigator.onLine, storage: est ? `${mb(est.usage || 0)} used of ${mb(est.quota || 0)}` : 'unknown',
  };
  const d = report.device;
  $('device').innerHTML = row('GPU (WebGPU)', d.webgpu ? 'Available' : 'Not available') + row('CPU threads', d.threads)
    + row('From Home Screen', d.standalone ? 'Yes' : 'No') + row('Internet', d.online ? 'Online' : 'Offline')
    + row('Storage', d.storage) + row('Protected storage', report.persisted ? 'Yes' : 'No');
}

$('copy').onclick = async () => {
  const text = `HemlockID offline test\n${JSON.stringify(report, null, 1)}`;
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const t = document.createElement('textarea');
    t.value = text;
    document.body.append(t);
    t.select();
    document.execCommand('copy');
    t.remove();
  }
  $('copied').hidden = false;
};

refreshOffline();
showDevice();
