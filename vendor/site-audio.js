/**
 * Shared Web Audio helpers for the site (octopus page + board):
 * default-ON sound that unlocks on the first gesture anywhere, iOS silent-switch workaround,
 * a remembered explicit mute, a pulsing hint until the context runs, and a graceful fallback.
 */
let silentEl = null;
function silentWavURI() {
  const n = 800, b = new Uint8Array(44 + n), v = new DataView(b.buffer), w = (o, t) => { for (let i = 0; i < t.length; i++) b[o + i] = t.charCodeAt(i); };
  w(0, "RIFF"); v.setUint32(4, 36 + n, true); w(8, "WAVE"); w(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, 8000, true); v.setUint32(28, 8000, true); v.setUint16(32, 1, true); v.setUint16(34, 8, true); w(36, "data"); v.setUint32(40, n, true); b.fill(128, 44);
  let bin = ""; b.forEach((x) => (bin += String.fromCharCode(x))); return "data:audio/wav;base64," + btoa(bin);
}
export const isReducedMotion = () => (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) || document.documentElement.classList.contains("reduce-motion");

/** Master chain: input → compressor → limiter → gain → analyser → destination. */
export function makeMaster(ctx, volume = 0.9) {
  const input = ctx.createGain(), comp = ctx.createDynamicsCompressor(), lim = ctx.createDynamicsCompressor(), gain = ctx.createGain(), analyser = ctx.createAnalyser();
  comp.threshold.value = -20; comp.knee.value = 8; comp.ratio.value = 3.5; comp.attack.value = 0.006; comp.release.value = 0.18;
  lim.threshold.value = -3; lim.knee.value = 0; lim.ratio.value = 20; lim.attack.value = 0.001; lim.release.value = 0.08;
  gain.gain.value = volume; analyser.fftSize = 2048;
  input.connect(comp); comp.connect(lim); lim.connect(gain); gain.connect(analyser); analyser.connect(ctx.destination);
  const rms = () => { const d = new Float32Array(analyser.fftSize); analyser.getFloatTimeDomainData(d); let x = 0; for (let i = 0; i < d.length; i++) x += d[i] * d[i]; return Math.sqrt(x / d.length); };
  return { input, gain, analyser, rms };
}
export function noiseBuffer(ctx, secs = 2, seed = 77) {
  const b = ctx.createBuffer(1, Math.floor(ctx.sampleRate * secs), ctx.sampleRate), d = b.getChannelData(0); let s = seed;
  for (let i = 0; i < d.length; i++) { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; d[i] = ((s >>> 0) % 20001) / 10000 - 1; }
  return b;
}
export function impulse(ctx, secs = 2.4, decay = 3.2, seed = 11) {
  const b = ctx.createBuffer(2, Math.floor(ctx.sampleRate * secs), ctx.sampleRate);
  for (let c = 0; c < 2; c++) { const d = b.getChannelData(c); let s = seed + c * 7; for (let i = 0; i < d.length; i++) { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; d[i] = (((s >>> 0) % 20001) / 10000 - 1) * Math.pow(1 - i / d.length, decay); } }
  return b;
}

/**
 * createSoundSwitch({ storageKey, buttons, cta, root, createEngine(ctx), onOn(engine), onOff(engine), onRunning(engine) })
 * Sound is ON by default; only an explicit mute is remembered (localStorage[storageKey] = "0").
 */
export function createSoundSwitch(o) {
  const st = { on: false, fail: false, ctx: null, engine: null };
  const buttons = o.buttons || [], cta = o.cta || null, root = o.root || document.documentElement;
  const muted = () => { try { return localStorage.getItem(o.storageKey) === "0"; } catch (e) { return false; } };
  const live = () => !!(st.ctx && st.ctx.state === "running");
  function sync() {
    const l = st.on && live();
    buttons.forEach((b) => {
      b.setAttribute("aria-pressed", st.on ? "true" : "false"); b.classList.toggle("on", l); b.classList.toggle("fail", st.fail);
      const t = b.querySelector("b"); if (t) t.textContent = st.fail ? "不支持" : l ? "开" : st.on ? "待开启" : "关";
      b.title = st.fail ? "此浏览器不支持音效" : l ? "点击静音" : st.on ? "点一下页面任意位置即可出声" : "点击开启音效";
    });
    if (cta) { cta.classList.toggle("hidden", !st.fail && (l || !st.on)); cta.textContent = st.fail ? "此浏览器不支持音效" : "🔊 点击开启音效"; cta.disabled = st.fail; }
    root.classList.toggle("snd-on", l);
  }
  function fail(e) { console.warn("[audio] 此浏览器不支持音效：", e && e.message ? e.message : e); st.fail = true; st.on = false; sync(); return false; }
  /** Create/resume the context; call synchronously from a gesture handler when possible. */
  function unlock() {
    if (st.fail) return false;
    try {
      if (navigator.audioSession) { try { navigator.audioSession.type = "playback"; } catch (e) {} }
      if (!silentEl) { silentEl = new Audio(silentWavURI()); silentEl.loop = true; silentEl.preload = "auto"; silentEl.setAttribute("playsinline", ""); silentEl.volume = 0.01; }
      if (st.on) { const p = silentEl.play(); if (p && p.catch) p.catch(() => {}); }
      if (!st.ctx) {
        const AC = window.AudioContext || window.webkitAudioContext;
        if (!AC) throw new Error("Web Audio API unavailable");
        try { st.ctx = new AC({ latencyHint: "interactive" }); } catch (e) { st.ctx = new AC(); }
        st.ctx.addEventListener("statechange", () => { if (live() && st.on && o.onRunning) o.onRunning(st.engine); sync(); });
        st.engine = o.createEngine(st.ctx);
      }
      if (st.ctx.state !== "running") { const r = st.ctx.resume(); if (r && r.catch) r.catch(() => {}); }
      const bs = st.ctx.createBufferSource(); bs.buffer = st.ctx.createBuffer(1, 1, 22050); bs.connect(st.ctx.destination); bs.start(0);
      return true;
    } catch (e) { return fail(e); }
  }
  function enable(save = true) {
    st.on = true;
    if (!unlock()) return;
    if (o.onOn) o.onOn(st.engine);
    if (save) { try { localStorage.removeItem(o.storageKey); } catch (e) {} }
    sync();
  }
  function disable() {
    st.on = false;
    if (o.onOff && st.engine) o.onOff(st.engine);
    if (silentEl) silentEl.pause();
    try { localStorage.setItem(o.storageKey, "0"); } catch (e) {}
    sync();
  }
  const gesture = () => { if (st.on && !st.fail && !live()) unlock(); };
  ["pointerdown", "touchstart", "touchend", "mousedown", "keydown", "click", "wheel"].forEach((t) => document.addEventListener(t, gesture, { capture: true, passive: true }));
  document.addEventListener("visibilitychange", () => {
    if (!st.ctx) return;
    if (document.hidden) { if (st.ctx.state === "running") st.ctx.suspend().catch(() => {}); }
    else if (st.on) st.ctx.resume().catch(() => {});
  });
  buttons.forEach((b) => b.addEventListener("click", (ev) => { ev.preventDefault(); if (st.on && !live()) enable(); else if (st.on) disable(); else enable(); }));
  if (cta) cta.addEventListener("click", (ev) => { ev.preventDefault(); ev.stopPropagation(); enable(); });
  if (!muted()) enable(false); // default on: browsers that block autoplay keep it suspended until the first gesture
  sync();
  return {
    get on() { return st.on; }, get fail() { return st.fail; }, get ctx() { return st.ctx; }, get engine() { return st.engine; },
    live, enable, disable, unlock, sync,
    state: () => (st.ctx ? st.ctx.state : "none"),
  };
}
