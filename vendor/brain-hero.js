/**
 * Neural brain hero v2 — glowing point cloud + synapse lines + signal pulses
 * travelling along edges, additive "bloom" halos, mouse-reactive rotation.
 * Geometry is centered at origin; camera fits the bounding sphere on every resize.
 */
import * as THREE from "./three.module.min.js";

function hash(n) { const x = Math.sin(n * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); }
function vnoise(x, y, z) {
  const xi = Math.floor(x), yi = Math.floor(y), zi = Math.floor(z);
  const xf = x - xi, yf = y - yi, zf = z - zi;
  const u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf), w = zf * zf * (3 - 2 * zf);
  const h = (a, b, c) => hash(a + b * 57 + c * 113);
  const x00 = h(xi, yi, zi) * (1 - u) + h(xi + 1, yi, zi) * u;
  const x10 = h(xi, yi + 1, zi) * (1 - u) + h(xi + 1, yi + 1, zi) * u;
  const x01 = h(xi, yi, zi + 1) * (1 - u) + h(xi + 1, yi, zi + 1) * u;
  const x11 = h(xi, yi + 1, zi + 1) * (1 - u) + h(xi + 1, yi + 1, zi + 1) * u;
  return (x00 * (1 - v) + x10 * v) * (1 - w) + (x01 * (1 - v) + x11 * v) * w;
}
function fbm(x, y, z) { return vnoise(x, y, z) * 0.6 + vnoise(x * 2.1, y * 2.1, z * 2.1) * 0.3 + vnoise(x * 4.3, y * 4.3, z * 4.3) * 0.1; }

/** Anatomical-ish brain: two folded hemispheres, cerebellum, brain stem. */
function sampleBrainPoint(i) {
  const r1 = hash(i * 1.37), r2 = hash(i * 7.91), r3 = hash(i * 3.17), r4 = hash(i * 9.73);
  const part = r4;
  let x, y, z;
  if (part < 0.84) {
    const side = i % 2 === 0 ? -1 : 1;
    const th = Math.acos(2 * r1 - 1), ph = r2 * Math.PI * 2;
    let dx = Math.sin(th) * Math.cos(ph), dy = Math.cos(th), dz = Math.sin(th) * Math.sin(ph);
    if (dx * side < 0) dx *= 0.3; // flatter medial wall
    const shell = r3 < 0.82 ? 1 : 0.55 + r3 * 0.4; // mostly surface, some volume
    const fold = 1 + (fbm(dx * 3.4 + side, dy * 3.4, dz * 3.4) - 0.5) * 0.28 + Math.sin(dz * 13 + dy * 9 + side) * 0.025;
    x = side * 0.2 + dx * 0.6 * shell * fold;
    y = dy * 0.66 * shell * fold;
    z = dz * 0.92 * shell * fold;
    if (y < -0.25) y = -0.25 + (y + 0.25) * 0.55; // flatter base
    y += 0.06 * Math.cos(z * 2.2);
  } else if (part < 0.95) {
    const th = Math.acos(2 * r1 - 1), ph = r2 * Math.PI * 2;
    const f = 1 + Math.sin(Math.cos(th) * 30) * 0.05;
    x = Math.sin(th) * Math.cos(ph) * 0.52 * f;
    y = -0.42 + Math.cos(th) * 0.22 * f;
    z = -0.6 + Math.sin(th) * Math.sin(ph) * 0.3 * f;
  } else {
    const a = r1 * Math.PI * 2, rr = 0.11 * Math.sqrt(r2);
    const t = r3;
    x = Math.cos(a) * rr * (1 - t * 0.3);
    y = -0.3 - t * 0.62;
    z = -0.22 - t * 0.18 + Math.sin(a) * rr;
  }
  return new THREE.Vector3(x, y, z);
}

function centerPoints(points) {
  const box = new THREE.Box3();
  for (const p of points) box.expandByPoint(p);
  const c = new THREE.Vector3(); box.getCenter(c);
  let r = 0;
  for (const p of points) { p.sub(c); r = Math.max(r, p.length()); }
  return r;
}

function glowTexture() {
  const s = 128, cv = document.createElement("canvas"); cv.width = cv.height = s;
  const g = cv.getContext("2d");
  const grd = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
  grd.addColorStop(0, "rgba(255,255,255,1)");
  grd.addColorStop(0.2, "rgba(170,230,255,.55)");
  grd.addColorStop(0.5, "rgba(120,140,255,.16)");
  grd.addColorStop(1, "rgba(0,0,0,0)");
  g.fillStyle = grd; g.fillRect(0, 0, s, s);
  const t = new THREE.CanvasTexture(cv); return t;
}

const PT_VERT = `
attribute float aSize; attribute float aPhase; attribute vec3 aColor;
uniform float uTime; uniform float uPR; uniform float uScale;
varying vec3 vColor; varying float vAlpha;
void main(){
  vec4 mv = modelViewMatrix * vec4(position,1.0);
  float tw = 0.55 + 0.45*sin(uTime*2.2 + aPhase);
  vColor = aColor; vAlpha = 0.45 + 0.55*tw;
  gl_PointSize = aSize * uPR * uScale * (0.75+0.5*tw) / -mv.z;
  gl_Position = projectionMatrix * mv;
}`;
const PT_FRAG = `
varying vec3 vColor; varying float vAlpha;
void main(){
  vec2 c = gl_PointCoord - 0.5; float d = length(c);
  float core = smoothstep(0.5, 0.0, d);
  float a = pow(core, 2.2) * vAlpha;
  if (a < 0.01) discard;
  gl_FragColor = vec4(vColor * (0.6 + core*1.2), a);
}`;

export function mountBrainHero(container, opts = {}) {
  if (!container) return () => {};
  // reduced motion (OS setting or the site's "减少动态" toggle) → render one static frame, no animation loop
  const isReduced = () => (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) || document.documentElement.classList.contains("reduce-motion");
  let reduced = isReduced();
  const mobile = Math.min(window.innerWidth, window.innerHeight) < 720;
  const nodesAttr = parseInt(container.getAttribute("data-nodes") || "0", 10);
  const COUNT = opts.count || (mobile ? 1600 : (nodesAttr || 4200));
  const LINKS = mobile ? 2 : 3;

  const probe = document.createElement("canvas");
  const gl = probe.getContext("webgl2") || probe.getContext("webgl");
  if (!gl) return null;
  const canvas = document.createElement("canvas");

  const scene = new THREE.Scene();
  const FOV = 38;
  const camera = new THREE.PerspectiveCamera(FOV, 1, 0.05, 100);
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: !mobile, alpha: true, powerPreference: "high-performance" });
  renderer.setClearColor(0x000000, 0);
  Object.assign(canvas.style, { position: "absolute", inset: "0", width: "100%", height: "100%", display: "block", margin: "0", transform: "none" });
  container.appendChild(canvas);

  const target = [];
  for (let i = 0; i < COUNT; i++) target.push(sampleBrainPoint(i));
  const baseRadius = Math.max(centerPoints(target), 0.8);

  const cA = new THREE.Color(0x5ce1ff), cB = new THREE.Color(0xa78bfa), cC = new THREE.Color(0x5ef0c0), cW = new THREE.Color(0xffffff);
  const positions = new Float32Array(COUNT * 3), sizes = new Float32Array(COUNT), phases = new Float32Array(COUNT), colors = new Float32Array(COUNT * 3);
  for (let i = 0; i < COUNT; i++) {
    const r = baseRadius * (1.1 + hash(i * 9.1) * 1.1);
    const th = hash(i * 2.2) * Math.PI * 2, ph = Math.acos(2 * hash(i * 4.4) - 1);
    positions[i * 3] = r * Math.sin(ph) * Math.cos(th);
    positions[i * 3 + 1] = r * Math.cos(ph);
    positions[i * 3 + 2] = r * Math.sin(ph) * Math.sin(th);
    phases[i] = hash(i * 5.5) * Math.PI * 2;
    const big = hash(i * 6.6) > 0.965;
    sizes[i] = big ? 9 + hash(i) * 7 : 2.6 + hash(i * 8.8) * 3.2;
    const p = target[i];
    const mix = THREE.MathUtils.clamp((p.x / baseRadius + 1) / 2, 0, 1);
    const col = cA.clone().lerp(cB, mix);
    if (hash(i * 4.2) > 0.9) col.lerp(cC, 0.7);
    if (big) col.lerp(cW, 0.5);
    colors[i * 3] = col.r; colors[i * 3 + 1] = col.g; colors[i * 3 + 2] = col.b;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geo.setAttribute("aSize", new THREE.BufferAttribute(sizes, 1));
  geo.setAttribute("aPhase", new THREE.BufferAttribute(phases, 1));
  geo.setAttribute("aColor", new THREE.BufferAttribute(colors, 3));
  const uniforms = { uTime: { value: 0 }, uPR: { value: 1 }, uScale: { value: 1 } };
  const mat = new THREE.ShaderMaterial({ vertexShader: PT_VERT, fragmentShader: PT_FRAG, uniforms, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
  const points = new THREE.Points(geo, mat);

  // synapses (spatial hash nearest neighbours)
  const edges = []; const cell = 0.2; const buckets = new Map();
  const key = (x, y, z) => `${x},${y},${z}`;
  target.forEach((p, i) => {
    const k = key(Math.floor(p.x / cell), Math.floor(p.y / cell), Math.floor(p.z / cell));
    if (!buckets.has(k)) buckets.set(k, []); buckets.get(k).push(i);
  });
  const adj = Array.from({ length: COUNT }, () => []);
  for (let i = 0; i < COUNT; i++) {
    const p = target[i]; const cand = [];
    const cx = Math.floor(p.x / cell), cy = Math.floor(p.y / cell), cz = Math.floor(p.z / cell);
    for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) for (let dz = -1; dz <= 1; dz++) {
      const arr = buckets.get(key(cx + dx, cy + dy, cz + dz)); if (!arr) continue;
      for (const j of arr) { if (j <= i) continue; const d = p.distanceTo(target[j]); if (d < 0.2 && d > 0.02) cand.push([d, j]); }
    }
    cand.sort((a, b) => a[0] - b[0]);
    for (let n = 0; n < Math.min(LINKS, cand.length); n++) {
      const j = cand[n][1]; const e = edges.length; edges.push([i, j]); adj[i].push(e); adj[j].push(e);
    }
  }
  const linePos = new Float32Array(edges.length * 6), lineCol = new Float32Array(edges.length * 6);
  edges.forEach(([a, b], e) => {
    linePos.set([target[a].x, target[a].y, target[a].z, target[b].x, target[b].y, target[b].z], e * 6);
    lineCol.set([colors[a * 3], colors[a * 3 + 1], colors[a * 3 + 2], colors[b * 3], colors[b * 3 + 1], colors[b * 3 + 2]], e * 6);
  });
  const lineGeo = new THREE.BufferGeometry();
  lineGeo.setAttribute("position", new THREE.BufferAttribute(linePos, 3));
  lineGeo.setAttribute("color", new THREE.BufferAttribute(lineCol, 3));
  const lineMat = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false });
  const lines = new THREE.LineSegments(lineGeo, lineMat);

  // signal pulses that hop edge → edge
  const PULSES = mobile ? 70 : 180;
  const pulsePos = new Float32Array(PULSES * 3), pulseSize = new Float32Array(PULSES), pulsePhase = new Float32Array(PULSES), pulseCol = new Float32Array(PULSES * 3);
  const pulses = [];
  for (let i = 0; i < PULSES; i++) {
    const e = Math.floor(hash(i * 11.1) * edges.length);
    pulses.push({ e, from: edges[e] ? edges[e][0] : 0, u: hash(i * 3.3), speed: 0.9 + hash(i * 2.7) * 1.6 });
    pulseSize[i] = 11 + hash(i * 1.9) * 9; pulsePhase[i] = hash(i) * 6.28;
    const col = hash(i * 7.7) > 0.5 ? cC : cW.clone().lerp(cA, 0.4);
    pulseCol.set([col.r, col.g, col.b], i * 3);
  }
  const pulseGeo = new THREE.BufferGeometry();
  pulseGeo.setAttribute("position", new THREE.BufferAttribute(pulsePos, 3));
  pulseGeo.setAttribute("aSize", new THREE.BufferAttribute(pulseSize, 1));
  pulseGeo.setAttribute("aPhase", new THREE.BufferAttribute(pulsePhase, 1));
  pulseGeo.setAttribute("aColor", new THREE.BufferAttribute(pulseCol, 3));
  const pulsePts = new THREE.Points(pulseGeo, mat);

  // halo "bloom" sprites
  const tex = glowTexture();
  const halo = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, color: 0x6fb8ff, transparent: true, opacity: 0.32, blending: THREE.AdditiveBlending, depthWrite: false }));
  halo.scale.setScalar(baseRadius * 3.2);
  const halo2 = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, color: 0xa78bfa, transparent: true, opacity: 0.22, blending: THREE.AdditiveBlending, depthWrite: false }));
  halo2.scale.setScalar(baseRadius * 2.1);

  const group = new THREE.Group();
  group.add(lines, points, pulsePts);
  scene.add(halo, halo2, group);

  let mouseX = 0, mouseY = 0, smx = 0, smy = 0;
  const onMove = (e) => {
    const r = container.getBoundingClientRect(); if (!r.width) return;
    mouseX = THREE.MathUtils.clamp(((e.clientX - r.left) / r.width) * 2 - 1, -1.5, 1.5);
    mouseY = THREE.MathUtils.clamp(((e.clientY - r.top) / r.height) * 2 - 1, -1.5, 1.5);
  };
  window.addEventListener("pointermove", onMove, { passive: true });

  function fitCamera(w, h) {
    const aspect = Math.max(0.3, w / Math.max(1, h));
    camera.aspect = aspect;
    const vFov = THREE.MathUtils.degToRad(FOV);
    const hFov = 2 * Math.atan(Math.tan(vFov / 2) * aspect);
    const dist = (baseRadius * 1.08) / Math.sin(Math.min(vFov, hFov) / 2);
    camera.position.set(0, 0, dist); camera.near = dist / 100; camera.far = dist * 20;
    camera.lookAt(0, 0, 0); camera.updateProjectionMatrix();
    uniforms.uScale.value = Math.max(h, 1) / 260;
  }
  function resize() {
    const w = Math.max(1, container.clientWidth), h = Math.max(1, container.clientHeight);
    const dpr = Math.min(window.devicePixelRatio || 1, mobile ? 1.5 : 1.75);
    renderer.setPixelRatio(dpr); renderer.setSize(w, h, false);
    uniforms.uPR.value = dpr; fitCamera(w, h);
  }
  resize();
  const ro = new ResizeObserver(resize); ro.observe(container);

  const baseTargets = target.map((p) => p.clone());
  let shock = 0;
  function triggerShockwave() {
    if (reduced) return;
    shock = 1;
    for (let i = 0; i < COUNT; i++) {
      const dir = baseTargets[i].clone(); if (dir.lengthSq() < 1e-6) dir.set(0, 1, 0); else dir.normalize();
      target[i].copy(baseTargets[i]).addScaledVector(dir, 0.5 + hash(i * 1.7) * 0.5);
    }
  }
  container.addEventListener("click", triggerShockwave);
  window.__brainAPI = { triggerShockwave, destroy: null };

  let visible = true; let raf = 0;
  const io = new IntersectionObserver((en) => { visible = en[0].isIntersecting; if (visible && !raf) raf = requestAnimationFrame(frame); }, { threshold: 0 });
  io.observe(container);
  const onVis = () => { if (!document.hidden && visible && !raf) raf = requestAnimationFrame(frame); };
  document.addEventListener("visibilitychange", onVis);

  const t0 = performance.now(); let last = t0;
  function staticFrame() {
    const pos = geo.attributes.position.array;
    for (let i = 0; i < COUNT; i++) { pos[i * 3] = target[i].x; pos[i * 3 + 1] = target[i].y; pos[i * 3 + 2] = target[i].z; }
    geo.attributes.position.needsUpdate = true;
    lineMat.opacity = 0.22; pulsePts.visible = false;
    group.rotation.set(0.12, -0.5, 0);
    halo.material.opacity = 0.26; halo2.material.opacity = 0.18;
    uniforms.uTime.value = 0;
    renderer.render(scene, camera);
  }
  function frame(now) {
    raf = 0;
    if (reduced) { staticFrame(); return; }
    if (!visible || document.hidden) return;
    const dt = Math.min(0.1, (now - last) / 1000); last = now;
    const t = (now - t0) / 1000;
    const k = 1 - Math.pow(0.0009, dt); // frame-rate independent lerp
    uniforms.uTime.value = t;
    if (shock > 0) { shock = Math.max(0, shock - dt * 0.9); for (let i = 0; i < COUNT; i++) target[i].lerp(baseTargets[i], k * 0.6); }
    const pos = geo.attributes.position.array;
    for (let i = 0; i < COUNT; i++) {
      const tx = target[i].x, ty = target[i].y, tz = target[i].z;
      pos[i * 3] += (tx - pos[i * 3]) * k * 0.55;
      pos[i * 3 + 1] += (ty - pos[i * 3 + 1]) * k * 0.55;
      pos[i * 3 + 2] += (tz - pos[i * 3 + 2]) * k * 0.55;
    }
    geo.attributes.position.needsUpdate = true;
    const assembled = Math.min(1, t / 2.4);
    lineMat.opacity = assembled * (0.2 + 0.07 * Math.sin(t * 1.7));

    for (let i = 0; i < PULSES; i++) {
      const p = pulses[i]; if (!edges.length) break;
      p.u += dt * p.speed * 2.2;
      if (p.u >= 1) {
        const [a, b] = edges[p.e]; const end = p.from === a ? b : a;
        const nexts = adj[end];
        const ne = nexts.length ? nexts[Math.floor(Math.random() * nexts.length)] : Math.floor(Math.random() * edges.length);
        p.e = ne; p.from = nexts.length ? end : edges[ne][0]; p.u = 0;
      }
      const [a, b] = edges[p.e]; const s = p.from === a ? a : b, d = p.from === a ? b : a;
      pulsePos[i * 3] = pos[s * 3] + (pos[d * 3] - pos[s * 3]) * p.u;
      pulsePos[i * 3 + 1] = pos[s * 3 + 1] + (pos[d * 3 + 1] - pos[s * 3 + 1]) * p.u;
      pulsePos[i * 3 + 2] = pos[s * 3 + 2] + (pos[d * 3 + 2] - pos[s * 3 + 2]) * p.u;
    }
    pulseGeo.attributes.position.needsUpdate = true;

    smx += (mouseX - smx) * k * 0.25; smy += (mouseY - smy) * k * 0.25;
    group.rotation.y = -0.5 + t * 0.16 + smx * 0.6;
    group.rotation.x = 0.12 + smy * 0.3 + Math.sin(t * 0.4) * 0.04;
    group.rotation.z = smx * 0.06;
    halo.material.opacity = 0.26 + 0.08 * Math.sin(t * 1.3);
    halo2.material.opacity = 0.18 + 0.08 * Math.sin(t * 0.9 + 1);
    renderer.render(scene, camera);
    raf = requestAnimationFrame(frame);
  }
  raf = requestAnimationFrame(frame);
  // live toggle from the "减少动态" button
  const onReduce = () => { const r = isReduced(); if (r === reduced) return; reduced = r; if (!raf) { last = performance.now(); raf = requestAnimationFrame(frame); } };
  window.addEventListener("ai168:reduce-motion", onReduce);

  const destroy = function () {
    cancelAnimationFrame(raf); io.disconnect(); ro.disconnect();
    window.removeEventListener("pointermove", onMove); document.removeEventListener("visibilitychange", onVis); window.removeEventListener("ai168:reduce-motion", onReduce);
    geo.dispose(); lineGeo.dispose(); pulseGeo.dispose(); mat.dispose(); lineMat.dispose(); tex.dispose(); renderer.dispose();
    if (canvas.parentNode) canvas.parentNode.removeChild(canvas);
    window.__brainAPI = null;
  };
  window.__brainAPI.destroy = destroy;
  container.classList.add("brain-live");
  return destroy;
}
