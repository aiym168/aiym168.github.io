/** 星际信号站 · 深空音景 — procedural Web Audio (no samples). Calm: bed ≈ -18 LUFS, below the octopus page. */
import { makeMaster, noiseBuffer, impulse } from "./site-audio.js";

export function createBoardAudio(ctx, opts = {}) {
  const M = makeMaster(ctx, opts.volume == null ? 0.8 : opts.volume);
  const nb = noiseBuffer(ctx, 3, 91);
  const verb = ctx.createConvolver(); verb.buffer = impulse(ctx, 6.5, 2.4, 23);
  const wet = ctx.createGain(); wet.gain.value = 0.9; verb.connect(wet); wet.connect(M.input);
  const sendTo = (node, dry = 1, rev = 0.6) => { const d = ctx.createGain(); d.gain.value = dry; node.connect(d); d.connect(M.input); const r = ctx.createGain(); r.gain.value = rev; node.connect(r); r.connect(verb); };
  let seed = opts.seed || 5; const R = () => { seed ^= seed << 13; seed ^= seed >>> 17; seed ^= seed << 5; return ((seed >>> 0) % 100000) / 100000; };
  const gn = (v = 0) => { const g = ctx.createGain(); g.gain.value = v; return g; };
  const flt = (type, f, q = 1) => { const b = ctx.createBiquadFilter(); b.type = type; b.frequency.value = f; b.Q.value = q; return b; };
  const pan = (v) => { if (!ctx.createStereoPanner) return gn(1); const p = ctx.createStereoPanner(); p.pan.value = v; return p; };
  function env(p, t, a, peak, d) { p.setValueAtTime(0.0001, t); p.exponentialRampToValueAtTime(Math.max(0.0002, peak), t + a); p.exponentialRampToValueAtTime(0.0001, t + a + d); }
  function tone(t, f, dur, lvl, type = "sine", pn = 0, rev = 1.2, f1 = 0) {
    const o = ctx.createOscillator(); o.type = type; o.frequency.setValueAtTime(f, t); if (f1) o.frequency.exponentialRampToValueAtTime(f1, t + dur);
    const g = gn(); const p = pan(pn); o.connect(g); g.connect(p); env(g.gain, t, Math.min(0.02, dur * 0.2), lvl, dur); sendTo(p, 1, rev); o.start(t); o.stop(t + dur + 0.1);
  }
  function noise(t, dur, f0, f1, q, lvl, rev = 0.6, pn = 0) {
    const s = ctx.createBufferSource(); s.buffer = nb; s.loop = true; const b = flt("bandpass", f0, q); b.frequency.setValueAtTime(f0, t); b.frequency.exponentialRampToValueAtTime(f1, t + dur);
    const g = gn(), p = pan(pn); s.connect(b); b.connect(g); g.connect(p); sendTo(p, 1, rev);
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(lvl, t + dur * 0.6); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    s.start(t, R() * 2); s.stop(t + dur + 0.1);
  }

  // ---------------- ambient bed
  let bed = null, timers = [];
  const PENTA = [1, 9 / 8, 5 / 4, 3 / 2, 5 / 3, 2];
  function startBed(t = ctx.currentTime, dur = 0) {
    if (bed) return;
    const out = gn(0.0001), lp = flt("lowpass", 1100, 0.5);
    const lpl = ctx.createOscillator(); lpl.frequency.value = 0.031; const lpg = gn(450); lpl.connect(lpg); lpg.connect(lp.frequency);
    lp.connect(out); sendTo(out, 0.55, 1.1);
    const nodes = [lpl];
    [[55, "sine"], [110, "triangle"], [164.81, "sine"], [220, "triangle"], [246.94, "sine"], [329.63, "sine"]].forEach(([f, ty], i) => {
      [-1, 1].forEach((d) => {
        const o = ctx.createOscillator(); o.type = ty; o.frequency.value = f * (1 + d * 0.0035 * (1 + i * 0.2));
        const g = gn(0), lf = ctx.createOscillator(); lf.frequency.value = 0.025 + i * 0.011 + (d > 0 ? 0.004 : 0); const lg = gn(0.5);
        const base = gn(i === 0 ? 0.22 : 0.12 / (1 + i * 0.25)); lf.connect(lg); lg.connect(g.gain); g.gain.value = 0.5;
        const p = pan(d * (0.2 + i * 0.1)); o.connect(base); base.connect(g); g.connect(p); p.connect(lp); nodes.push(o, lf);
      });
    });
    // cosmic wind
    const ws = ctx.createBufferSource(); ws.buffer = nb; ws.loop = true; const wb = flt("bandpass", 700, 0.8), wg = gn(0.09);
    const wl = ctx.createOscillator(); wl.frequency.value = 0.045; const wlg = gn(420); wl.connect(wlg); wlg.connect(wb.frequency);
    const wa = ctx.createOscillator(); wa.frequency.value = 0.07; const wag = gn(0.05); wa.connect(wag); wag.connect(wg.gain);
    ws.connect(wb); wb.connect(wg); wg.connect(out); nodes.push(ws, wl, wa);
    nodes.forEach((n) => { n.start(t); if (dur) n.stop(t + dur); });
    out.gain.setValueAtTime(0.0001, t); out.gain.exponentialRampToValueAtTime(0.6, t + 4);
    if (dur) { out.gain.setValueAtTime(0.6, t + dur - 2); out.gain.exponentialRampToValueAtTime(0.0001, t + dur - 0.05); }
    bed = { out, nodes };
    if (!dur) scheduleRandom(); else for (let tt = t + 3; tt < t + dur - 3; tt += 3 + R() * 5) (R() < 0.7 ? ping : whisper)(tt);
  }
  function ping(t) { const f = 660 * PENTA[Math.floor(R() * PENTA.length)] * (R() < 0.5 ? 2 : 1); tone(t, f, 2.6, 0.028, "sine", (R() - 0.5) * 1.4, 2.2); tone(t + 0.01, f * 2.01, 1.4, 0.008, "sine", (R() - 0.5) * 1.4, 2.2); }
  function whisper(t) { // radio-static whisper: AM-gated bandpassed noise
    const dur = 0.6 + R() * 0.9, s = ctx.createBufferSource(); s.buffer = nb; s.loop = true;
    const b = flt("bandpass", 1800 + R() * 1800, 3), g = gn(0), am = ctx.createOscillator(); am.type = "square"; am.frequency.value = 18 + R() * 22; const ag = gn(0.5);
    const e = gn(), p = pan((R() - 0.5) * 1.6); am.connect(ag); ag.connect(g.gain); g.gain.value = 0.5;
    s.connect(b); b.connect(g); g.connect(e); e.connect(p); sendTo(p, 0.6, 1.0); env(e.gain, t, dur * 0.4, 0.035, dur * 0.6);
    s.start(t, R()); s.stop(t + dur + 0.1); am.start(t); am.stop(t + dur + 0.1);
  }
  function scheduleRandom() {
    const loop = (fn, a, b) => { const id = setTimeout(() => { if (!bed) return; if (ctx.state === "running") fn(ctx.currentTime + 0.05); loop(fn, a, b); }, (a + R() * (b - a)) * 1000); timers.push(id); };
    loop(ping, 4, 9); loop(whisper, 10, 20);
  }
  function stopBed() { if (!bed) return; timers.forEach(clearTimeout); timers = []; const b = bed; bed = null; const t = ctx.currentTime; b.out.gain.cancelScheduledValues(t); b.out.gain.setTargetAtTime(0.0001, t, 0.6); setTimeout(() => b.nodes.forEach((n) => { try { n.stop(); } catch (e) {} }), 3500); }

  // ---------------- drag whoosh (continuous, follows speed)
  let dragN = null;
  function ensureDrag() {
    if (dragN) return dragN;
    const s = ctx.createBufferSource(); s.buffer = nb; s.loop = true; const b = flt("bandpass", 400, 1.1), g = gn(0.0001), p = pan(0);
    s.connect(b); b.connect(g); g.connect(p); sendTo(p, 1, 0.5); s.start();
    return (dragN = { b, g, p });
  }
  function drag(speed, dir = 0) { // speed ≈ px per ms, 0 when released
    const d = ensureDrag(), t = ctx.currentTime, k = Math.min(1, Math.abs(speed) / 2.5);
    d.g.gain.setTargetAtTime(k > 0.01 ? 0.02 + 0.16 * k : 0.0001, t, k > 0.01 ? 0.05 : 0.25);
    d.b.frequency.setTargetAtTime(260 + 2600 * k, t, 0.08);
    if (d.p.pan) d.p.pan.setTargetAtTime(Math.max(-0.7, Math.min(0.7, dir * 0.6)), t, 0.1);
  }

  // ---------------- UI sounds
  function sparkle(strong = false, t = ctx.currentTime + 0.01) {
    const n = strong ? 5 : 3, base = 1320 * PENTA[Math.floor(R() * 4)];
    for (let i = 0; i < n; i++) tone(t + i * (strong ? 0.045 : 0.035), base * PENTA[(i * 2) % PENTA.length] * (i > 2 ? 2 : 1), strong ? 0.9 : 0.5, strong ? 0.045 : 0.022, "sine", (i / n - 0.5) * 0.8, 1.6);
    if (strong) noise(t, 0.35, 5000, 9000, 1.5, 0.02, 1.2);
  }
  function charge(dur = 1.6, t = ctx.currentTime + 0.01) {
    const o = ctx.createOscillator(); o.type = "sawtooth"; o.frequency.setValueAtTime(110, t); o.frequency.exponentialRampToValueAtTime(880, t + dur);
    const lp = flt("lowpass", 300, 6); lp.frequency.setValueAtTime(300, t); lp.frequency.exponentialRampToValueAtTime(4200, t + dur);
    const g = gn(); o.connect(lp); lp.connect(g); sendTo(g, 1, 0.8);
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.07, t + dur); g.gain.exponentialRampToValueAtTime(0.0001, t + dur + 0.25);
    o.start(t); o.stop(t + dur + 0.3);
    tone(t, 220, dur, 0.04, "sine", 0, 0.8, 880);
    noise(t, dur, 400, 6000, 1.2, 0.05, 0.8);
  }
  function chime(t = ctx.currentTime + 0.01) { // bright "signal sent" bell + fading echo trail
    const dl = ctx.createDelay(1.5); dl.delayTime.value = 0.34; const fb = gn(0.48), lp = flt("lowpass", 3200, 0.7), eg = gn(0.6);
    dl.connect(lp); lp.connect(fb); fb.connect(dl); lp.connect(eg); sendTo(eg, 0.7, 1.0);
    [[1046.5, 0.08], [1568, 0.05], [2093, 0.035], [3136, 0.02], [4186, 0.012]].forEach(([f, l], i) => {
      const o = ctx.createOscillator(); o.type = "sine"; o.frequency.value = f; const g = gn(), p = pan((i % 2 ? 1 : -1) * 0.25);
      o.connect(g); g.connect(p); sendTo(p, 1, 1.4); g.connect(dl); env(g.gain, t, 0.004, l, 2.4 / (1 + i * 0.3)); o.start(t); o.stop(t + 3);
    });
    setTimeout(() => { try { fb.gain.setTargetAtTime(0, ctx.currentTime, 0.5); } catch (e) {} }, 4000);
  }
  function warpSweep(t = ctx.currentTime + 0.01) {
    noise(t, 1.8, 180, 7000, 1.4, 0.16, 0.9, -0.3);
    tone(t, 90, 1.6, 0.12, "sine", 0, 0.5, 38);
    tone(t + 0.05, 440, 1.5, 0.03, "triangle", 0.3, 1.2, 1760);
  }
  function launch(t = ctx.currentTime + 0.01) { warpSweep(t); chime(t + 0.25); }
  function error(t = ctx.currentTime + 0.01) { tone(t, 440, 0.32, 0.06, "triangle", 0, 0.6, 415); tone(t + 0.2, 330, 0.5, 0.06, "triangle", 0, 0.8, 311); }
  return { ctx, M, rms: M.rms, startBed, stopBed, drag, sparkle, charge, chime, warpSweep, launch, error };
}

/** Offline render of ~N s of the ambient bed (for loudness checks). */
export async function renderBed(secs = 30, sr = 48000) {
  const OAC = window.OfflineAudioContext || window.webkitOfflineAudioContext;
  const ctx = new OAC(2, Math.ceil(secs * sr), sr); const a = createBoardAudio(ctx); a.startBed(0, secs); return ctx.startRendering();
}
