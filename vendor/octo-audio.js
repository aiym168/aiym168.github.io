/**
 * HYALOS GX-8 · 机械变形音效 — procedural Web Audio synthesis (no samples).
 * The same code drives the live page (AudioContext) and the film's soundtrack (OfflineAudioContext).
 */
function rng(seed) { let s = seed >>> 0 || 1; return () => { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; return ((s >>> 0) % 100000) / 100000; }; }

export function createSfx(ctx, opts = {}) {
  const sr = ctx.sampleRate;
  const R = rng(opts.seed || 8);
  // ---- master: bus → compressor → limiter → gain → destination
  const master = ctx.createGain(); master.gain.value = opts.volume == null ? 0.9 : opts.volume;
  const comp = ctx.createDynamicsCompressor();
  comp.threshold.value = -20; comp.knee.value = 8; comp.ratio.value = 3.5; comp.attack.value = 0.006; comp.release.value = 0.18;
  const lim = ctx.createDynamicsCompressor();
  lim.threshold.value = -3; lim.knee.value = 0; lim.ratio.value = 20; lim.attack.value = 0.001; lim.release.value = 0.08;
  const input = ctx.createGain();
  const analyser = ctx.createAnalyser(); analyser.fftSize = 2048;
  input.connect(comp); comp.connect(lim); lim.connect(master); master.connect(analyser); analyser.connect(ctx.destination);
  // ---- shared noise + reverb
  const nb = ctx.createBuffer(1, sr * 2, sr); { const d = nb.getChannelData(0); const r = rng(77); for (let i = 0; i < d.length; i++) d[i] = r() * 2 - 1; }
  const ir = ctx.createBuffer(2, Math.floor(sr * 2.4), sr);
  for (let c = 0; c < 2; c++) { const d = ir.getChannelData(c); const r = rng(11 + c); for (let i = 0; i < d.length; i++) d[i] = (r() * 2 - 1) * Math.pow(1 - i / d.length, 3.2); }
  const verb = ctx.createConvolver(); verb.buffer = ir;
  const verbIn = ctx.createGain(); verbIn.gain.value = 0.3; verbIn.connect(verb); verb.connect(input);

  let bus = null;
  function newBus() { const g = ctx.createGain(); g.connect(input); const s = ctx.createGain(); s.gain.value = 1; g.connect(s); s.connect(verbIn); bus = { dry: g, nodes: new Set() }; return bus; }
  newBus();
  const track = (n, end) => { bus.nodes.add(n); n.onended = () => bus && bus.nodes.delete(n); return n; };

  // ---- primitives
  function env(param, t, a, peak, d, floor = 0.0001) {
    param.setValueAtTime(floor, t);
    param.exponentialRampToValueAtTime(Math.max(floor, peak), t + Math.max(0.001, a));
    param.exponentialRampToValueAtTime(floor, t + a + Math.max(0.01, d));
  }
  function out(node, pan = 0, wet = 1) {
    let n = node;
    if (ctx.createStereoPanner && pan) { const p = ctx.createStereoPanner(); p.pan.value = Math.max(-1, Math.min(1, pan)); n.connect(p); n = p; }
    n.connect(bus.dry);
    if (wet !== 1) { const w = ctx.createGain(); w.gain.value = wet - 1; n.connect(w); w.connect(verbIn); }
    return n;
  }
  function noiseSrc(t, dur) {
    const s = ctx.createBufferSource(); s.buffer = nb; s.loop = true;
    s.start(t, R() * 1.5); s.stop(t + dur + 0.05); track(s); return s;
  }
  function filt(type, f, q = 1) { const b = ctx.createBiquadFilter(); b.type = type; b.frequency.value = f; b.Q.value = q; return b; }
  function osc(type, t, dur, f0, f1) {
    const o = ctx.createOscillator(); o.type = type; o.frequency.setValueAtTime(f0, t);
    if (f1 && f1 !== f0) o.frequency.exponentialRampToValueAtTime(f1, t + dur);
    o.start(t); o.stop(t + dur + 0.05); track(o); return o;
  }
  const g = (v = 0) => { const n = ctx.createGain(); n.gain.value = v; return n; };

  // ---- building blocks
  function hiss(t, dur = 0.6, lvl = 0.22, pan = 0) {
    const n = noiseSrc(t, dur), hp = filt("highpass", 2600, 0.7), bp = filt("bandpass", 6500, 0.8), a = g();
    bp.frequency.setValueAtTime(7500, t); bp.frequency.exponentialRampToValueAtTime(3800, t + dur);
    n.connect(hp); hp.connect(bp); bp.connect(a); env(a.gain, t, 0.025, lvl, dur); out(a, pan, 1.2);
  }
  function servo(t, dur, f0, f1, lvl = 0.12, pan = 0) {
    const o = osc("sawtooth", t, dur, f0, f1), o2 = osc("square", t, dur, f0 * 1.5, f1 * 1.5);
    const vib = osc("sine", t, dur, 31, 31), vg = g(f0 * 0.012); vib.connect(vg); vg.connect(o.frequency);
    const bp = filt("bandpass", f0 * 2.2, 2.5); bp.frequency.setValueAtTime(f0 * 2.2, t); bp.frequency.exponentialRampToValueAtTime(f1 * 2.2, t + dur);
    const lp = filt("lowpass", 4200, 0.6), a = g(), a2 = g(0.35);
    o.connect(bp); o2.connect(a2); a2.connect(bp); bp.connect(lp); lp.connect(a);
    a.gain.setValueAtTime(0.0001, t); a.gain.exponentialRampToValueAtTime(lvl, t + 0.05);
    a.gain.setValueAtTime(lvl, t + dur - 0.08); a.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    out(a, pan);
  }
  function click(t, lvl = 0.25, f = 3200, pan = 0) {
    const n = noiseSrc(t, 0.03), bp = filt("bandpass", f, 9), a = g();
    n.connect(bp); bp.connect(a); env(a.gain, t, 0.0015, lvl, 0.03); out(a, pan, 0.8);
    const o = osc("square", t, 0.012, f * 0.55, f * 0.5), oa = g(); o.connect(oa); env(oa.gain, t, 0.001, lvl * 0.18, 0.01); out(oa, pan);
  }
  function ratchet(t, dur, n, lvl = 0.2, accel = 1, pan = 0) {
    for (let i = 0; i < n; i++) {
      const u = i / Math.max(1, n - 1);
      const tt = t + dur * (accel === 1 ? u : Math.pow(u, accel));
      click(tt, lvl * (0.7 + R() * 0.5), 2400 + R() * 2400, pan + (R() - 0.5) * 0.4);
    }
  }
  function ping(t, f, dur, lvl, pan = 0) {
    const o = osc("sine", t, dur, f, f * 0.995), a = g(); o.connect(a); env(a.gain, t, 0.002, lvl, dur); out(a, pan, 1.4);
  }
  function sub(t, f0, f1, dur, lvl) {
    const o = osc("sine", t, dur, f0, f1), a = g(); o.connect(a); env(a.gain, t, 0.004, lvl, dur); out(a);
  }
  function clunk(t, size = 1, pan = 0) {
    const n = noiseSrc(t, 0.12), lp = filt("lowpass", 1400, 0.8), a = g();
    n.connect(lp); lp.connect(a); env(a.gain, t, 0.002, 0.55 * size, 0.09 * size); out(a, pan);
    const n2 = noiseSrc(t, 0.6), bp = filt("bandpass", 420 / Math.sqrt(size), 14), a2 = g();
    n2.connect(bp); bp.connect(a2); env(a2.gain, t, 0.002, 1.1 * size, 0.38 * size); out(a2, pan, 1.3);
    [1, 2.71, 4.43, 6.9].forEach((m, i) => ping(t, (310 / Math.sqrt(size)) * m, 0.5 * size / (1 + i * 0.6), 0.07 * size / (1 + i), pan));
    sub(t, 95, 38, 0.28 * size, 0.7 * size);
  }
  function whoosh(t, dur, f0, f1, lvl = 0.3, pan0 = 0, pan1 = 0) {
    const n = noiseSrc(t, dur), bp = filt("bandpass", f0, 1.3), a = g();
    bp.frequency.setValueAtTime(f0, t); bp.frequency.exponentialRampToValueAtTime(f1, t + dur);
    n.connect(bp); bp.connect(a);
    a.gain.setValueAtTime(0.0001, t); a.gain.exponentialRampToValueAtTime(lvl, t + dur * 0.55); a.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    let node = a;
    if (ctx.createStereoPanner) { const p = ctx.createStereoPanner(); p.pan.setValueAtTime(pan0, t); p.pan.linearRampToValueAtTime(pan1, t + dur); a.connect(p); node = p; }
    node.connect(bus.dry); const w = g(0.4); node.connect(w); w.connect(verbIn);
  }
  function rumble(t, dur, f0, f1, lvl = 0.35) {
    const o = osc("sawtooth", t, dur, f0, f1), lp = filt("lowpass", 140, 0.9), a = g();
    const n = noiseSrc(t, dur), nl = filt("lowpass", 160, 0.7), na = g(0.8);
    o.connect(lp); n.connect(nl); nl.connect(na); na.connect(lp); lp.connect(a);
    a.gain.setValueAtTime(0.0001, t); a.gain.exponentialRampToValueAtTime(lvl, t + dur * 0.35); a.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    out(a);
  }
  function shimmer(t, dur = 1.6, lvl = 0.05) {
    for (let i = 0; i < 9; i++) {
      const f = 1800 + R() * 4200, tt = t + i * 0.06 + R() * 0.05;
      const o = osc("sine", tt, dur, f, f * 1.03), a = g(); o.connect(a); env(a.gain, tt, 0.03, lvl * (0.6 + R() * 0.6), dur);
      out(a, (R() - 0.5) * 1.2, 2.2);
    }
  }
  function hum(t, dur, lvl = 0.16) {
    const o = osc("sawtooth", t, dur, 48, 104), o2 = osc("sine", t, dur, 96, 208), lp = filt("lowpass", 220, 3), a = g(), trem = g(1);
    lp.frequency.setValueAtTime(220, t); lp.frequency.exponentialRampToValueAtTime(1500, t + dur * 0.8);
    const lfo = osc("sine", t, dur, 7, 16), lg = g(0.35); lfo.connect(lg); lg.connect(trem.gain);
    o.connect(lp); o2.connect(lp); lp.connect(trem); trem.connect(a);
    a.gain.setValueAtTime(0.0001, t); a.gain.exponentialRampToValueAtTime(lvl, t + dur * 0.5);
    a.gain.setValueAtTime(lvl, t + dur - 0.35); a.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    out(a, 0, 1.2);
    // electric crackle
    for (let i = 0; i < 10; i++) click(t + dur * (0.2 + 0.75 * R()), 0.05, 5000 + R() * 3000, (R() - 0.5));
  }
  function swell(t, dur, lvl = 0.25) { // reverse-cymbal style build into a hit
    const n = noiseSrc(t, dur), hp = filt("highpass", 1800, 0.7), a = g();
    n.connect(hp); hp.connect(a); a.gain.setValueAtTime(0.0001, t); a.gain.exponentialRampToValueAtTime(lvl, t + dur); a.gain.setValueAtTime(0.0001, t + dur + 0.01);
    out(a, 0, 1.3);
  }

  // ---- named events (time t in context seconds)
  const S = {
    blip(t) { const o = osc("sine", t, 0.05, 1500, 2300), a = g(); o.connect(a); env(a.gain, t, 0.002, 0.09, 0.05); out(a, 0.2); ping(t + 0.018, 3400, 0.05, 0.03, 0.2); },
    jetIn(t, dur = 2.6) { whoosh(t, dur, 180, 2600, 0.45, -0.6, 0.1); rumble(t, dur + 0.6, 34, 52, 0.55); hiss(t + dur * 0.55, 0.9, 0.12); clunk(t + dur, 0.7); },
    open(t, part = 0, dur = 1.0) {
      const pan = [0, 0.45, 0, -0.45, 0.3][part] || 0;
      hiss(t, 0.55, 0.22, pan);
      servo(t + 0.04, dur * 0.8, 170 + part * 14, 560 + part * 40, 0.09, pan);
      ratchet(t + 0.1, dur * 0.68, part === 4 ? 22 : 12, 0.15, 1, pan);
    },
    lock(t, part = 0) { clunk(t, 1.3, [0, 0.45, 0, -0.45, 0.3][part] || 0); sub(t, 70, 34, 0.35, 0.6); },
    close(t, part = 0, dur = 0.5) {
      const pan = [0, 0.45, 0, -0.45, 0.3][part] || 0;
      servo(t, dur * 0.9, 640 + part * 30, 210, 0.11, pan);
      ratchet(t + 0.03, dur * 0.85, 9, 0.15, 0.8, pan);
      hiss(t + dur * 0.5, 0.25, 0.12, pan);
    },
    snap(t, part = 0) {
      const pan = [0, 0.45, 0, -0.45, 0.3][part] || 0;
      click(t, 0.5, 2600, pan); clunk(t + 0.01, 0.75, pan);
    },
    shimmer(t) { shimmer(t, 1.8, 0.05); },
    hum(t, dur) { hum(t, dur, 0.17); },
    thrust(t, dur) { whoosh(t + 0.12, dur, 900, 1500, 0.16, 0.4, -0.4); rumble(t + 0.12, dur, 40, 46, 0.18); },
    explode(t, dur = 1.4) {
      sub(t, 72, 26, 1.6, 1.0); clunk(t, 1.8);
      const n = noiseSrc(t, 1.8), lp = filt("lowpass", 900, 0.6), a = g(); lp.frequency.setValueAtTime(2400, t); lp.frequency.exponentialRampToValueAtTime(180, t + 1.6);
      n.connect(lp); lp.connect(a); env(a.gain, t, 0.004, 0.7, 1.6); out(a, 0, 1.4);
      whoosh(t + 0.05, dur + 0.4, 2400, 260, 0.35, -0.5, 0.5);
      for (let i = 0; i < 34; i++) { const tt = t + 0.15 + Math.pow(R(), 1.4) * (dur + 0.8); const f = 1800 + R() * 4200; ping(tt, f, 0.09 + R() * 0.12, 0.05 + R() * 0.05, (R() - 0.5) * 1.6); if (i % 3 === 0) click(tt, 0.12, f, (R() - 0.5) * 1.6); }
      for (let i = 0; i < 5; i++) servo(t + 0.3 + i * 0.22, 0.5, 300 + i * 40, 900 + i * 90, 0.035, (R() - 0.5) * 1.4);
    },
    reassemble(t, dur = 0.8) {
      ratchet(t, dur, 46, 0.2, 0.55, 0);
      for (let i = 0; i < 6; i++) servo(t + i * dur / 7, dur / 4, 800 - i * 40, 260, 0.05, (i % 2 ? 0.5 : -0.5));
      whoosh(t, dur, 300, 3200, 0.28, 0.6, -0.2);
      swell(t + dur - 0.55, 0.55, 0.22);
      S.slam(t + dur);
    },
    slam(t) {
      clunk(t, 2.2); sub(t, 60, 28, 1.2, 1.1);
      [180, 497, 853, 1231, 1716].forEach((f, i) => ping(t, f, 2.2 / (1 + i * 0.4), 0.12 / (1 + i * 0.5)));
      const n = noiseSrc(t, 0.25), hp = filt("highpass", 3000, 0.7), a = g(); n.connect(hp); hp.connect(a); env(a.gain, t, 0.001, 0.45, 0.2); out(a, 0, 1.6);
      hiss(t + 0.08, 0.9, 0.16);
    },
    jetAway(t, dur = 2.4) { whoosh(t, dur, 260, 4800, 0.5, 0, 0.7); rumble(t, dur, 36, 78, 0.55); hiss(t, dur * 0.8, 0.14); servo(t, 0.5, 900, 260, 0.06); },
  };

  // ---- drone bed
  let drone = null;
  function startDrone(t = ctx.currentTime, dur = 0) {
    if (drone) return drone;
    const a = g(), lp = filt("lowpass", 200, 1.2);
    const o1 = ctx.createOscillator(), o2 = ctx.createOscillator(), o3 = ctx.createOscillator();
    o1.type = "sawtooth"; o1.frequency.value = 41.2; o2.type = "sawtooth"; o2.frequency.value = 41.55; o3.type = "sine"; o3.frequency.value = 82.4;
    const lfo = ctx.createOscillator(); lfo.frequency.value = 0.07; const lg = g(110); lfo.connect(lg); lg.connect(lp.frequency);
    const n = ctx.createBufferSource(); n.buffer = nb; n.loop = true; const nf = filt("bandpass", 900, 0.6), ng = g(0.05);
    [o1, o2, o3].forEach((o) => o.connect(lp)); n.connect(nf); nf.connect(ng); ng.connect(a); lp.connect(a);
    a.gain.setValueAtTime(0.0001, t); a.gain.exponentialRampToValueAtTime(0.085, t + 2.5);
    a.connect(input); const w = g(0.6); a.connect(w); w.connect(verbIn);
    [o1, o2, o3, lfo, n].forEach((o) => { o.start(t); if (dur) o.stop(t + dur); });
    if (dur) { a.gain.setValueAtTime(0.085, t + dur - 1.2); a.gain.exponentialRampToValueAtTime(0.0001, t + dur - 0.05); }
    drone = { a, nodes: [o1, o2, o3, lfo, n] };
    return drone;
  }
  function stopDrone() { if (!drone) return; const t = ctx.currentTime; drone.a.gain.cancelScheduledValues(t); drone.a.gain.setTargetAtTime(0.0001, t, 0.3); const d = drone; setTimeout(() => d.nodes.forEach((o) => { try { o.stop(); } catch (e) {} }), 1500); drone = null; }

  function play(ev, t) { const f = S[ev.type]; if (f) f(t, ...(ev.args || [])); }
  function cancel() { // fade and drop everything scheduled on the current bus
    const old = bus; const t = ctx.currentTime;
    old.dry.gain.setTargetAtTime(0.0001, t, 0.05);
    setTimeout(() => { old.nodes.forEach((n) => { try { n.stop(); } catch (e) {} }); try { old.dry.disconnect(); } catch (e) {} }, 400);
    newBus();
  }
  function rms() { const d = new Float32Array(analyser.fftSize); analyser.getFloatTimeDomainData(d); let x = 0; for (let i = 0; i < d.length; i++) x += d[i] * d[i]; return Math.sqrt(x / d.length); }
  return { ctx, S, play, cancel, startDrone, stopDrone, master, analyser, rms };
}

/** Render a list of timed events to an AudioBuffer offline. */
export async function renderOffline(events, duration, sampleRate = 48000) {
  const OAC = window.OfflineAudioContext || window.webkitOfflineAudioContext;
  const ctx = new OAC(2, Math.ceil(duration * sampleRate), sampleRate);
  const sfx = createSfx(ctx, { volume: 0.9 });
  sfx.startDrone(0, duration);
  events.forEach((e) => sfx.play(e, e.t));
  return ctx.startRendering();
}
export function toWav(buf) {
  const ch = buf.numberOfChannels, n = buf.length, sr = buf.sampleRate;
  const dv = new DataView(new ArrayBuffer(44 + n * ch * 2));
  const w = (o, s) => { for (let i = 0; i < s.length; i++) dv.setUint8(o + i, s.charCodeAt(i)); };
  w(0, "RIFF"); dv.setUint32(4, 36 + n * ch * 2, true); w(8, "WAVE"); w(12, "fmt "); dv.setUint32(16, 16, true); dv.setUint16(20, 1, true);
  dv.setUint16(22, ch, true); dv.setUint32(24, sr, true); dv.setUint32(28, sr * ch * 2, true); dv.setUint16(32, ch * 2, true); dv.setUint16(34, 16, true);
  w(36, "data"); dv.setUint32(40, n * ch * 2, true);
  const data = []; for (let c = 0; c < ch; c++) data.push(buf.getChannelData(c));
  let o = 44; for (let i = 0; i < n; i++) for (let c = 0; c < ch; c++) { const v = Math.max(-1, Math.min(1, data[c][i])); dv.setInt16(o, v < 0 ? v * 0x8000 : v * 0x7fff, true); o += 2; }
  return dv.buffer;
}
