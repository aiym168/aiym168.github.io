/**
 * HYALOS GX-8 · 玻璃机械章鱼 — procedural three.js teardown simulator.
 * Every part is generated in code (no model files). Choreography:
 *   jet in → 5 part beats (open 1 s / hold / close 0.5 s, own camera each)
 *   → full explode on a 330° turntable → fast reassembly while turning → jet away.
 * Reference spec (mantle height H = 1): mantle Ø 0.92H, eye Ø 0.15H, arm length ≈ 1.9H,
 * arm base Ø 0.15H → tip Ø 0.03H, tip-to-tip span ≈ 3.4H, arms spread with curled tips.
 */
import * as THREE from "./three.module.min.js";
import { OrbitControls } from "./three-addons/OrbitControls.js";
import { RoomEnvironment } from "./three-addons/RoomEnvironment.js";
import { EffectComposer } from "./three-addons/EffectComposer.js";
import { RenderPass } from "./three-addons/RenderPass.js";
import { UnrealBloomPass } from "./three-addons/UnrealBloomPass.js";
import { OutputPass } from "./three-addons/OutputPass.js";
import { createSfx, renderOffline, toWav } from "./octo-audio.js";
import { createSoundSwitch } from "./site-audio.js";

// ------------------------------------------------------------------ helpers
const TAU = Math.PI * 2;
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const lerp = (a, b, t) => a + (b - a) * t;
const smooth = (x) => { x = clamp(x); return x * x * (3 - 2 * x); };
const eio = (x) => { x = clamp(x); return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };
const eout = (x) => { x = clamp(x); return 1 - Math.pow(1 - x, 3); };
const ein = (x) => { x = clamp(x); return x * x * x; };
function hash(n) { const x = Math.sin(n * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); }
const V = (x = 0, y = 0, z = 0) => new THREE.Vector3(x, y, z);

// ------------------------------------------------------------------ choreography
const BEATS = [3.0, 6.7, 10.4, 14.1, 17.8];
const OPEN = 1.0, HOLD = 1.6, CLOSE = 0.5;
const EXP0 = 21.6, EXP1 = 23.0, RE0 = 26.0, RE1 = 26.8, TURN0 = 21.6, TURN1 = 27.0;
const OUT0 = 27.6, OUT1 = 30.0, LOOP = 31.0;
const TURN_DEG = 330;

const PARTS = [
  { id: "shell", name: "玻璃头罩", en: "GLASS MANTLE", verb: "抬起并翻转",
    fn: "高透硼硅玻璃外壳，承受水压并保护内部机构，核心的光从这里透出。" },
  { id: "eye", name: "光学眼", en: "OPTIC UNIT", verb: "镜组分离",
    fn: "双目视觉单元：三片镜组 + 6 片光圈叶片，负责测距、追踪与夜视。" },
  { id: "core", name: "反应核心", en: "REACTOR CORE", verb: "升出机体",
    fn: "为 8 条机械腕和喷射泵供能，三层约束环高速旋转、稳定能流。" },
  { id: "siphon", name: "虹吸喷射管", en: "SIPHON JET", verb: "伸缩展开",
    fn: "吸入海水后由叶轮加压喷出，提供冲刺推力，也负责转向。" },
  { id: "arm", name: "机械腕", en: "ARM 01", verb: "链节展开",
    fn: "锥形链节逐节变细，每节都有关节环、两侧活塞和吸盘，可独立卷曲抓取。" },
];
const PHASES = [
  { t: 0, name: "入场", cap: "HYALOS GX-8 喷射入场", sub: "虹吸管高压喷水推进，8 条机械腕收拢减阻，抵达后张开。" },
  ...PARTS.map((p, i) => ({ t: BEATS[i] - 0.8, beat: i, name: p.name, cap: `${p.name} · ${p.verb}`, sub: p.fn, at: BEATS[i] })),
  { t: EXP0 - 0.8, name: "全机拆解", cap: "全机拆解 · 330° 转台", sub: "全部零件沿径向依次飞出，内部零件仍在运转。", at: EXP0 },
  { t: RE0, name: "快速重组", cap: "快速重组", sub: "零件按相反顺序归位，转台不停。", at: RE0 },
  { t: OUT0, name: "离场", cap: "喷射离场", sub: "机械腕收拢，虹吸管全功率喷射。", at: OUT0 },
];
// sound events on the same timeline (see vendor/octo-audio.js)
const SFX_EVENTS = (() => {
  const ev = [{ t: 0, type: "jetIn", args: [2.6] }];
  BEATS.forEach((B, i) => {
    ev.push({ t: B - 0.12, type: "blip" });
    ev.push({ t: B, type: "open", args: [i, OPEN] });
    if (i === 0) ev.push({ t: B + 0.12, type: "shimmer" });
    if (i === 2) { ev.push({ t: B, type: "hum", args: [OPEN + HOLD + CLOSE] }); ev.push({ t: B + 0.2, type: "shimmer" }); }
    if (i === 3) ev.push({ t: B + OPEN, type: "thrust", args: [HOLD] });
    ev.push({ t: B + OPEN, type: "lock", args: [i] });
    ev.push({ t: B + OPEN + HOLD, type: "close", args: [i, CLOSE] });
    ev.push({ t: B + OPEN + HOLD + CLOSE, type: "snap", args: [i] });
  });
  ev.push({ t: EXP0 - 0.12, type: "blip" });
  ev.push({ t: EXP0, type: "explode", args: [EXP1 - EXP0] });
  ev.push({ t: RE0, type: "reassemble", args: [RE1 - RE0] });
  ev.push({ t: OUT0, type: "jetAway", args: [OUT1 - OUT0] });
  return ev.sort((a, b) => a.t - b.t);
})();
function beatK(t, B) {
  if (t < B) return 0;
  if (t < B + OPEN) return eio((t - B) / OPEN);
  if (t < B + OPEN + HOLD) return 1;
  if (t < B + OPEN + HOLD + CLOSE) return 1 - eio((t - B - OPEN - HOLD) / CLOSE);
  return 0;
}
function explodeE(t) {
  if (t < EXP0) return 0;
  if (t < EXP1) return eio((t - EXP0) / (EXP1 - EXP0));
  if (t < RE0) return 1;
  if (t < RE1) return 1 - eio((t - RE0) / (RE1 - RE0));
  return 0;
}
const fmtT = (t) => { const m = Math.floor(t / 60), s = t - m * 60; return `${String(m).padStart(2, "0")}:${s.toFixed(1).padStart(4, "0")}`; };

// ------------------------------------------------------------------ geometry factories
function gearGeo(teeth, r, depth, holeR = 0.28, windows = 5) {
  const s = new THREE.Shape();
  const rt = r, rr = r * (1 - Math.min(0.22, 2.4 / teeth)), da = TAU / teeth;
  for (let i = 0; i < teeth; i++) {
    const a = i * da;
    const pts = [[rr, a], [rt, a + da * 0.22], [rt, a + da * 0.48], [rr, a + da * 0.7]];
    pts.forEach(([R, A], k) => { const x = Math.cos(A) * R, y = Math.sin(A) * R; if (i === 0 && k === 0) s.moveTo(x, y); else s.lineTo(x, y); });
  }
  s.closePath();
  const h = new THREE.Path(); h.absarc(0, 0, r * holeR * 0.5, 0, TAU, true); s.holes.push(h);
  if (windows) for (let w = 0; w < windows; w++) {
    const a = (w / windows) * TAU, p = new THREE.Path();
    p.absarc(Math.cos(a) * r * 0.55, Math.sin(a) * r * 0.55, r * 0.15, 0, TAU, true); s.holes.push(p);
  }
  const g = new THREE.ExtrudeGeometry(s, { depth, bevelEnabled: true, bevelThickness: depth * 0.18, bevelSize: depth * 0.18, bevelSegments: 1, curveSegments: 10 });
  g.translate(0, 0, -depth / 2);
  return g;
}
function mantleProfile() {
  const ctrl = [[0.47, -0.12], [0.58, 0.03], [0.68, 0.26], [0.73, 0.52], [0.71, 0.78], [0.61, 1.02], [0.44, 1.22], [0.22, 1.35], [0.001, 1.39]];
  const curve = new THREE.CatmullRomCurve3(ctrl.map(([r, y]) => V(r, y, 0)));
  return curve.getPoints(44).map((p) => new THREE.Vector2(Math.max(0.001, p.x), p.y));
}

// ------------------------------------------------------------------ main
export function mountOctopus(stage) {
  const canvasHost = stage.querySelector("[data-octo-canvas]");
  const q = (s) => stage.querySelector(s);
  const doc = document.documentElement;
  const isReduced = () => (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) || doc.classList.contains("reduce-motion");
  const lite = (window.matchMedia && window.matchMedia("(max-width: 760px), (pointer: coarse)").matches) || /lite=1/.test(location.search);
  let reduced = isReduced();

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: "high-performance", preserveDrawingBuffer: /capture=1/.test(location.search) });
  } catch (e) { return false; }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, lite ? 1.5 : 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.82;
  renderer.setClearColor(0x02050b, 1);
  canvasHost.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(renderer), 0.04).texture;
  scene.environmentIntensity = 1;
  const camera = new THREE.PerspectiveCamera(32, 16 / 9, 0.05, 200);
  camera.position.set(3, 1.4, 5);

  // ---------- backdrop + bokeh (depth-of-field feel)
  const backdrop = new THREE.Mesh(new THREE.SphereGeometry(60, 32, 16), new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false,
    vertexShader: "varying vec3 vP; void main(){ vP = normalize(position); gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.); }",
    fragmentShader: `varying vec3 vP;
      void main(){
        vec3 base = vec3(0.006,0.012,0.028);
        float up = vP.y*0.5+0.5;
        vec3 c = base + vec3(0.0,0.05,0.09)*pow(max(0.,1.-length(vP.xy-vec2(0.15,0.25))),3.0)
                      + vec3(0.06,0.025,0.12)*pow(1.-up,2.5)*0.7;
        gl_FragColor = vec4(c,1.);
      }`,
  }));
  backdrop.userData.noCount = true;
  scene.add(backdrop);

  function makePoints(n, rMin, rMax, size, color, seed) {
    const pos = new Float32Array(n * 3), sz = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      const u = hash(i * 3.1 + seed), v = hash(i * 7.7 + seed), w = hash(i * 1.9 + seed);
      const th = u * TAU, ph = Math.acos(2 * v - 1), r = lerp(rMin, rMax, w);
      pos.set([Math.sin(ph) * Math.cos(th) * r, Math.cos(ph) * r * 0.6, Math.sin(ph) * Math.sin(th) * r], i * 3);
      sz[i] = size * (0.4 + hash(i * 5.3 + seed) * 1.2);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    g.setAttribute("size", new THREE.BufferAttribute(sz, 1));
    const m = new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { uColor: { value: new THREE.Color(color) }, uScale: { value: 300 }, uOp: { value: 1 } },
      vertexShader: `attribute float size; uniform float uScale; varying float vD;
        void main(){ vec4 mv = modelViewMatrix*vec4(position,1.); vD = -mv.z; gl_PointSize = size*uScale/max(0.1,-mv.z); gl_Position = projectionMatrix*mv; }`,
      fragmentShader: `uniform vec3 uColor; uniform float uOp; varying float vD;
        void main(){ vec2 d = gl_PointCoord-0.5; float r = length(d); float a = smoothstep(0.5,0.18,r)*0.9 + smoothstep(0.5,0.44,r)*0.25*step(0.3,r);
          gl_FragColor = vec4(uColor*a*uOp, a*uOp); }`,
    });
    const p = new THREE.Points(g, m); p.userData.noCount = true; p.frustumCulled = false;
    return p;
  }
  const bokeh = makePoints(lite ? 40 : 80, 10, 24, 0.5, 0x1d4f66, 1);
  const bokeh2 = makePoints(lite ? 20 : 40, 10, 22, 0.6, 0x34255a, 9);
  const dust = makePoints(lite ? 120 : 260, 1.6, 7, 0.035, 0x7fdcff, 4);
  scene.add(bokeh, bokeh2, dust);

  // ---------- lights: key + strong cyan/violet rims + core point
  scene.add(new THREE.HemisphereLight(0x8fb8ff, 0x0a0614, 0.18));
  const key = new THREE.DirectionalLight(0xfff4ea, 1.5); key.position.set(-3, 5, 4); scene.add(key);
  const rimC = new THREE.DirectionalLight(0x5ce1ff, 3.2); rimC.position.set(4, 3, -5); scene.add(rimC);
  const rimV = new THREE.DirectionalLight(0xa78bfa, 2.6); rimV.position.set(-5, 1.5, -4); scene.add(rimV);
  const under = new THREE.DirectionalLight(0x5ef0c0, 0.8); under.position.set(0, -4, 2); scene.add(under);

  // ---------- materials
  const M = {
    titan: new THREE.MeshPhysicalMaterial({ color: 0x8e97a6, metalness: 1, roughness: 0.3, clearcoat: 0.6, clearcoatRoughness: 0.2, envMapIntensity: 1.2 }),
    gun: new THREE.MeshStandardMaterial({ color: 0x3a414e, metalness: 1, roughness: 0.34, envMapIntensity: 1.1 }),
    dark: new THREE.MeshStandardMaterial({ color: 0x16191f, metalness: 0.85, roughness: 0.42, envMapIntensity: 0.9 }),
    black: new THREE.MeshStandardMaterial({ color: 0x07080b, metalness: 0.6, roughness: 0.55 }),
    chrome: new THREE.MeshStandardMaterial({ color: 0xe8eef8, metalness: 1, roughness: 0.08, envMapIntensity: 1.4 }),
    copper: new THREE.MeshStandardMaterial({ color: 0xc07a4c, metalness: 1, roughness: 0.28 }),
    brass: new THREE.MeshStandardMaterial({ color: 0xc9a65a, metalness: 1, roughness: 0.3 }),
    rubber: new THREE.MeshStandardMaterial({ color: 0x1b1e26, metalness: 0.1, roughness: 0.75 }),
    cyan: new THREE.MeshStandardMaterial({ color: 0x0b2a33, emissive: 0x5ce1ff, emissiveIntensity: 2.6, metalness: 0.2, roughness: 0.3 }),
    violet: new THREE.MeshStandardMaterial({ color: 0x1a1233, emissive: 0xa78bfa, emissiveIntensity: 2.2, metalness: 0.2, roughness: 0.3 }),
    lens: new THREE.MeshPhysicalMaterial({ color: 0x020304, metalness: 0, roughness: 0.04, clearcoat: 1, clearcoatRoughness: 0.02, envMapIntensity: 1.6 }),
    glass: new THREE.MeshPhysicalMaterial({
      color: 0xdff6ff, metalness: 0, roughness: 0.04, transmission: 1, thickness: 0.35, ior: 1.47,
      attenuationColor: new THREE.Color(0x8fdcff), attenuationDistance: 2.5,
      clearcoat: 1, clearcoatRoughness: 0.03, iridescence: 0.55, iridescenceIOR: 1.3, iridescenceThicknessRange: [180, 520],
      specularIntensity: 1, envMapIntensity: 1.5, transparent: false,
    }),
    lensGlass: new THREE.MeshPhysicalMaterial({ color: 0xbfefff, metalness: 0, roughness: 0.02, transmission: 1, thickness: 0.08, ior: 1.6, clearcoat: 1 }),
    core: new THREE.MeshStandardMaterial({ color: 0x9ff3ff, emissive: 0x5ce1ff, emissiveIntensity: 4.5, roughness: 0.2 }),
  };
  Object.values(M).forEach((m) => { if (m.envMapIntensity !== undefined) m.envMapIntensity *= 0.45; });
  const wireMat = new THREE.MeshBasicMaterial({ color: 0x5ce1ff, wireframe: true, transparent: true, opacity: 0.22, depthWrite: false });

  // ---------- part registry
  let partCount = 0;
  const explodables = []; // { obj, base, rot, dir, dist, delay, tumble, bo, br }
  function reg(obj, dirHint, dist = 1, delay = null, tumble = 0.6) {
    const d = (dirHint || obj.position.clone()).clone();
    if (d.lengthSq() < 1e-4) d.set(0, 1, 0);
    d.normalize();
    const e = { obj, base: obj.position.clone(), rot: obj.rotation.clone(), dir: d, dist,
      delay: delay == null ? hash(explodables.length * 4.7) * 0.6 : delay, tumble: tumble * (hash(explodables.length * 2.3) - 0.5),
      bo: V(), br: V() };
    explodables.push(e);
    return e;
  }
  const mesh = (geo, mat, parent) => { const m = new THREE.Mesh(geo, mat); if (parent) parent.add(m); return m; };

  // ---------- octopus root
  const octo = new THREE.Group();
  scene.add(octo);
  const body = new THREE.Group(); octo.add(body); // tilt / sway

  // === 1. glass mantle (beat: lift + flip)
  const head = new THREE.Group(); head.rotation.x = -0.3; head.position.z = 0.02; body.add(head);
  const shellBeat = new THREE.Group(); head.add(shellBeat);
  const shellExp = new THREE.Group(); shellBeat.add(shellExp);
  const prof = mantleProfile();
  const glassGeo = new THREE.LatheGeometry(prof, lite ? 48 : 72);
  const glass = mesh(glassGeo, M.glass, shellExp);
  const fres = mesh(glassGeo, new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { c1: { value: new THREE.Color(0x5ce1ff) }, c2: { value: new THREE.Color(0xc4b5ff) }, op: { value: 0.9 } },
    vertexShader: "varying vec3 vN; varying vec3 vV; void main(){ vec4 mv = modelViewMatrix*vec4(position,1.); vN = normalize(normalMatrix*normal); vV = normalize(-mv.xyz); gl_Position = projectionMatrix*mv; }",
    fragmentShader: "uniform vec3 c1; uniform vec3 c2; uniform float op; varying vec3 vN; varying vec3 vV; void main(){ float f = pow(1.-abs(dot(normalize(vN),normalize(vV))), 3.0); vec3 c = mix(c1,c2,f); gl_FragColor = vec4(c*f*op, f*op); }",
  }), shellExp);
  fres.scale.setScalar(1.004); fres.userData.noCount = true;
  // meridian ribs + rivets + base ring + crown sensor
  const ribCount = 6;
  const rivetGeo = new THREE.SphereGeometry(0.014, 8, 6);
  const rivetPts = [];
  for (let k = 0; k < ribCount; k++) {
    const a = (k / ribCount) * TAU + 0.26;
    const pts = prof.filter((_, i) => i % 2 === 0).map((p) => V(Math.sin(a) * p.x * 1.012, p.y, Math.cos(a) * p.x * 1.012));
    mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), 48, 0.011, 6, false), M.titan, shellExp);
    pts.forEach((p, i) => { if (i % 3 === 1 && i < pts.length - 2) rivetPts.push(p.clone().multiplyScalar(1.01)); });
  }
  const rivetsShell = new THREE.InstancedMesh(rivetGeo, M.chrome, rivetPts.length);
  rivetPts.forEach((p, i) => rivetsShell.setMatrixAt(i, new THREE.Matrix4().makeTranslation(p.x, p.y, p.z)));
  shellExp.add(rivetsShell);
  const baseRing = mesh(new THREE.TorusGeometry(0.475, 0.03, 10, 72), M.titan, shellExp); baseRing.rotation.x = Math.PI / 2; baseRing.position.y = -0.11;
  const baseGlow = mesh(new THREE.TorusGeometry(0.478, 0.006, 6, 96), M.cyan, shellExp); baseGlow.rotation.x = Math.PI / 2; baseGlow.position.y = -0.075;
  const crown = mesh(new THREE.CylinderGeometry(0.06, 0.09, 0.05, 24), M.titan, shellExp); crown.position.y = 1.39;
  const crownGlow = mesh(new THREE.TorusGeometry(0.07, 0.008, 6, 32), M.violet, shellExp); crownGlow.rotation.x = Math.PI / 2; crownGlow.position.y = 1.42;
  
  shellBeat.position.y = 0.65; shellExp.position.y = -0.65;
  const shellE = reg(shellExp, V(0, 1, -0.15), 2.1, 0.0, 0.3);
  const shellAnchor = new THREE.Object3D(); shellAnchor.position.set(0, 1.1, 0.35); shellExp.add(shellAnchor);

  // === internal mechanism (visible through the glass)
  const mech = new THREE.Group(); head.add(mech);
  const spine = mesh(new THREE.CylinderGeometry(0.05, 0.07, 1.15, 16), M.chrome, mech); spine.position.y = 0.5; reg(spine, V(0, 1, 0), 1.1);
  const gears = [];
  const gearDefs = [
    // teeth, radius, depth, pos, axis('y'|'x'|'z'), speed, mat
    [28, 0.30, 0.045, V(0, 0.92, 0), "y", 0.6, M.brass],
    [16, 0.17, 0.04, V(0.27, 0.80, 0.18), "y", -1.05, M.gun],
    [20, 0.21, 0.05, V(-0.08, 0.55, 0.30), "z", 0.8, M.titan],
    [12, 0.12, 0.04, V(0.18, 0.62, 0.32), "z", -1.4, M.brass],
    [24, 0.24, 0.05, V(0.33, 0.48, -0.16), "x", 0.7, M.gun],
    [14, 0.13, 0.04, V(-0.34, 0.75, -0.1), "x", -1.3, M.copper],
    [18, 0.18, 0.045, V(-0.2, 1.12, -0.05), "y", 1.1, M.titan],
    [10, 0.09, 0.035, V(0.05, 1.22, 0.14), "z", -2.0, M.brass],
    [22, 0.2, 0.04, V(-0.3, 0.38, -0.25), "z", 0.9, M.brass],
  ];
  gearDefs.forEach(([t, r, d, p, ax, sp, mat], i) => {
    const holder = new THREE.Group(); holder.position.copy(p); mech.add(holder);
    if (ax === "y") holder.rotation.x = Math.PI / 2; if (ax === "x") holder.rotation.y = Math.PI / 2;
    const g = mesh(gearGeo(t, r, d), mat, holder);
    const hub = mesh(new THREE.CylinderGeometry(r * 0.16, r * 0.16, d * 2.2, 14), M.chrome, holder); hub.rotation.x = Math.PI / 2;
    gears.push({ g, sp });
    reg(holder, p.clone().add(V(0, 0.15, 0)), 1.7 + hash(i) * 0.9);
  });
  // servos (dark boxes with spinning horns)
  const servoHorns = [];
  for (let i = 0; i < 4; i++) {
    const a = (i / 4) * TAU + 0.8;
    const s = new THREE.Group(); s.position.set(Math.sin(a) * 0.36, 0.18, Math.cos(a) * 0.36); s.rotation.y = a; mech.add(s);
    mesh(new THREE.BoxGeometry(0.16, 0.11, 0.09), M.dark, s);
    const lbl = mesh(new THREE.BoxGeometry(0.162, 0.018, 0.092), M.violet, s); lbl.position.y = 0.035;
    const horn = mesh(new THREE.BoxGeometry(0.14, 0.012, 0.025), M.titan, s); horn.position.set(0.03, 0.065, 0); servoHorns.push(horn);
    mesh(new THREE.CylinderGeometry(0.018, 0.018, 0.03, 10), M.chrome, s).position.set(0.03, 0.06, 0);
    reg(s, s.position.clone().setY(0.3), 1.7);
  }
  // cables (core → collar) + brain fins
  for (let i = 0; i < 10; i++) {
    const a = (i / 10) * TAU + 0.3, r0 = 0.12, r1 = 0.44;
    const c = new THREE.CatmullRomCurve3([V(Math.sin(a) * r0, 0.35, Math.cos(a) * r0), V(Math.sin(a + 0.4) * 0.34, 0.42 + hash(i) * 0.2, Math.cos(a + 0.4) * 0.34), V(Math.sin(a + 0.6) * r1, -0.05, Math.cos(a + 0.6) * r1)]);
    const cab = mesh(new THREE.TubeGeometry(c, 24, i % 4 === 0 ? 0.012 : 0.009, 6, false), i % 4 === 0 ? M.copper : M.rubber, mech);
    reg(cab, V(Math.sin(a), 0.3, Math.cos(a)), 0.7);
  }
  const finRing = new THREE.Group(); finRing.position.y = 1.02; mech.add(finRing);
  for (let i = 0; i < 18; i++) {
    const f = mesh(new THREE.BoxGeometry(0.008, 0.07, 0.11), i % 6 === 0 ? M.cyan : M.dark, finRing);
    const a = (i / 18) * TAU; f.position.set(Math.sin(a) * 0.4, 0, Math.cos(a) * 0.4); f.rotation.y = a;
  }
  reg(finRing, V(0, 1, 0), 2.0);

  // === 3. reactor core
  const coreBeat = new THREE.Group(); coreBeat.position.y = 0.32; head.add(coreBeat);
  const coreExp = new THREE.Group(); coreBeat.add(coreExp);
  const coreBall = mesh(new THREE.IcosahedronGeometry(0.12, 3), M.core, coreExp);
  const coreCage = mesh(new THREE.IcosahedronGeometry(0.15, 1), new THREE.MeshStandardMaterial({ color: 0x9aa6bb, metalness: 1, roughness: 0.25, wireframe: true }), coreExp);
  const coreRings = [];
  [[0.22, 0.016, M.titan], [0.27, 0.012, M.gun], [0.32, 0.01, M.titan]].forEach(([r, tb, mat], i) => {
    const holder = new THREE.Group(); coreExp.add(holder);
    const ring = mesh(new THREE.TorusGeometry(r, tb, 10, 80), mat, holder);
    const glow = mesh(new THREE.TorusGeometry(r, tb * 0.35, 6, 80), i === 1 ? M.violet : M.cyan, holder); glow.scale.setScalar(1.0); glow.position.z = tb * 0.7;
    for (let k = 0; k < 6; k++) { const b = mesh(new THREE.BoxGeometry(0.03, 0.03, 0.03), M.dark, holder); const a = (k / 6) * TAU; b.position.set(Math.cos(a) * r, Math.sin(a) * r, 0); }
    holder.rotation.set(i * 0.9 + 0.4, i * 1.3, 0);
    coreRings.push({ holder, sp: [1.6, -1.1, 0.8][i] });
    reg(holder, V(0, 1, 0).applyAxisAngle(V(0, 0, 1), (i - 1) * 0.6), 0.5);
  });
  const coil = mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(Array.from({ length: 60 }, (_, i) => V(Math.cos(i * 0.62) * 0.07, -0.16 - i * 0.004, Math.sin(i * 0.62) * 0.07))), 120, 0.007, 5, false), M.copper, coreExp);
  const coreLight = new THREE.PointLight(0x5ce1ff, 2.0, 2.4, 1.6); coreExp.add(coreLight);
  reg(coreExp, V(0, 1, 0.35), 1.5, 0.15, 0.2);
  const coreAnchor = new THREE.Object3D(); coreExp.add(coreAnchor);

  // === collar: armor plates, servo pods, beak
  const collar = new THREE.Group(); body.add(collar);
  const collarRing = mesh(new THREE.TorusGeometry(0.5, 0.05, 12, 72), M.gun, collar); collarRing.rotation.x = Math.PI / 2; collarRing.position.y = -0.17;
  reg(collarRing, V(0, -1, 0), 0.5, 0.3, 0);
  const PLATES = 16;
  const plateGeo = new THREE.CylinderGeometry(0.585, 0.53, 0.22, 10, 1, true, -TAU / PLATES * 0.46, TAU / PLATES * 0.92);
  for (let i = 0; i < PLATES; i++) {
    const a = (i / PLATES) * TAU;
    const pg = new THREE.Group(); pg.rotation.y = a; collar.add(pg);
    const inner = new THREE.Group(); pg.add(inner); inner.position.y = -0.2;
    const pl = mesh(plateGeo, i % 4 === 0 ? M.gun : M.titan, inner); pl.material.side = THREE.DoubleSide;
    for (let k = 0; k < 4; k++) {
      const rv = mesh(rivetGeo, M.chrome, inner);
      const aa = ((k % 2) - 0.5) * (TAU / PLATES) * 0.65, yy = k < 2 ? 0.07 : -0.07;
      rv.position.set(Math.sin(aa) * (0.565 - yy * 0.12), yy, Math.cos(aa) * (0.565 - yy * 0.12));
    }
    if (i % 2 === 0) { const strip = mesh(new THREE.BoxGeometry(0.012, 0.15, 0.01), i % 8 === 0 ? M.violet : M.cyan, inner); strip.position.set(0, 0, 0.585); }
    reg(inner, V(Math.sin(a), -0.1, Math.cos(a)).applyAxisAngle(V(0, 1, 0), -a), 1.5 + hash(i * 3) * 0.6);
  }
  const beak = mesh(new THREE.ConeGeometry(0.16, 0.22, 24), M.dark, collar); beak.rotation.x = Math.PI; beak.position.y = -0.36;
  const beakRing = mesh(new THREE.TorusGeometry(0.15, 0.02, 8, 40), M.titan, collar); beakRing.rotation.x = Math.PI / 2; beakRing.position.y = -0.27;
  reg(beak, V(0, -1, 0), 0.9); reg(beakRing, V(0, -1, 0), 0.7);

  // === 2. eyes
  const eyes = [];
  [-1, 1].forEach((side) => {
    const a = side * 0.56;
    const eb = new THREE.Group(); eb.position.set(Math.sin(a) * 0.6, 0.04, Math.cos(a) * 0.6); body.add(eb);
    eb.lookAt(eb.position.clone().multiplyScalar(2).setY(0.08)); // +z outward
    const housing = mesh(new THREE.CylinderGeometry(0.11, 0.13, 0.1, 32), M.titan, eb); housing.rotation.x = Math.PI / 2; housing.position.z = -0.02;
    const back = mesh(new THREE.CylinderGeometry(0.08, 0.1, 0.08, 20), M.dark, eb); back.rotation.x = Math.PI / 2; back.position.z = -0.1;
    const bezel = mesh(new THREE.TorusGeometry(0.105, 0.012, 8, 48), M.cyan, eb); bezel.position.z = 0.035;
    const lens = mesh(new THREE.SphereGeometry(0.095, 32, 16, 0, TAU, 0, Math.PI / 2), M.lens, eb); lens.rotation.x = Math.PI / 2; lens.scale.set(1, 0.55, 1); lens.position.z = 0.02;
    const pupil = mesh(new THREE.CircleGeometry(0.022, 24), M.core, eb); pupil.position.z = 0.074;
    const outerLens = mesh(new THREE.SphereGeometry(0.1, 24, 12, 0, TAU, 0, Math.PI / 2.6), M.lensGlass, eb); outerLens.rotation.x = Math.PI / 2; outerLens.scale.set(1, 0.4, 1); outerLens.position.z = 0.05;
    const iris = new THREE.Group(); iris.position.z = 0.045; eb.add(iris);
    for (let k = 0; k < 6; k++) { const bl = mesh(new THREE.BoxGeometry(0.06, 0.018, 0.004), M.gun, iris); const aa = (k / 6) * TAU; bl.position.set(Math.cos(aa) * 0.055, Math.sin(aa) * 0.055, 0); bl.rotation.z = aa + 1.1; }
    const brow = mesh(new THREE.TorusGeometry(0.14, 0.018, 8, 32, Math.PI * 0.9), M.gun, eb); brow.position.z = -0.01; brow.rotation.z = Math.PI * 0.05;
    const els = [back, housing, iris, lens, pupil, bezel, outerLens, brow];
    const sep = [-0.14, -0.04, 0.12, 0.2, 0.3, 0.38, 0.52, -0.08];
    const exps = els.map((o, i) => { const e = reg(o, V(0, 0, 1), 0.25 + i * 0.03, 0.35, 0.2); return e; });
    reg(eb, eb.position.clone().setY(0.15), 1.9, 0.2, 0.4);
    const anchor = new THREE.Object3D(); anchor.position.z = 0.1; eb.add(anchor);
    eyes.push({ eb, exps, sep, iris, anchor });
  });

  // === 4. siphon jet
  const siphonMount = new THREE.Group(); body.add(siphonMount);
  const sa = Math.PI + 0.62;
  siphonMount.position.set(Math.sin(sa) * 0.5, -0.12, Math.cos(sa) * 0.5);
  siphonMount.rotation.y = sa; siphonMount.rotateX(0.55); // +z points out/back/down
  const siphonSegs = [];
  for (let i = 0; i < 6; i++) {
    const r = 0.095 - i * 0.007;
    const sg = new THREE.Group(); sg.position.z = i * 0.055; siphonMount.add(sg);
    const tube = mesh(new THREE.CylinderGeometry(r, r * 1.04, 0.05, 28, 1, true), i % 2 ? M.titan : M.gun, sg); tube.rotation.x = Math.PI / 2; tube.material.side = THREE.DoubleSide;
    const ring = mesh(new THREE.TorusGeometry(r * 1.03, 0.008, 6, 36), i === 5 ? M.cyan : M.chrome, sg); ring.position.z = 0.025;
    const e = reg(sg, V(0, 0, 1), 0.4 + i * 0.07, 0.1 + i * 0.05, 0.1);
    siphonSegs.push(e);
  }
  const nozzle = new THREE.Group(); nozzle.position.z = 0.34; siphonMount.add(nozzle);
  const noz = mesh(new THREE.CylinderGeometry(0.075, 0.05, 0.08, 28, 1, true), M.chrome, nozzle); noz.rotation.x = Math.PI / 2; noz.material.side = THREE.DoubleSide;
  const impeller = new THREE.Group(); nozzle.add(impeller);
  for (let k = 0; k < 7; k++) { const b = mesh(new THREE.BoxGeometry(0.004, 0.06, 0.03), M.brass, impeller); b.rotation.z = (k / 7) * TAU; b.rotation.y = 0.5; b.position.set(Math.sin(-(k / 7) * TAU) * 0.025, Math.cos((k / 7) * TAU) * 0.025, 0); }
  mesh(new THREE.CylinderGeometry(0.012, 0.012, 0.05, 10), M.chrome, impeller).rotation.x = Math.PI / 2;
  const fins = [];
  for (let k = 0; k < 4; k++) {
    const fh = new THREE.Group(); fh.rotation.z = (k / 4) * TAU + Math.PI / 4; nozzle.add(fh);
    const f = mesh(new THREE.BoxGeometry(0.008, 0.07, 0.11), M.gun, fh); f.position.set(0, 0.09, -0.02); fins.push(f);
  }
  const nozzleE = reg(nozzle, V(0, 0, 1), 0.9, 0.35, 0.2);
  const siphonAnchor = new THREE.Object3D(); siphonAnchor.position.z = 0.05; nozzle.add(siphonAnchor);
  reg(siphonMount, siphonMount.position.clone().setY(-0.3), 1.8, 0.25, 0.2);

  // jet stream (analytic particles, deterministic in time)
  const JET_N = lite ? 70 : 140;
  const jetGeo = new THREE.BufferGeometry();
  const jetPos = new Float32Array(JET_N * 3), jetSz = new Float32Array(JET_N);
  jetGeo.setAttribute("position", new THREE.BufferAttribute(jetPos, 3));
  jetGeo.setAttribute("size", new THREE.BufferAttribute(jetSz, 1));
  const jetMat = dust.material.clone(); jetMat.uniforms = THREE.UniformsUtils.clone(dust.material.uniforms); jetMat.uniforms.uColor.value.set(0x9fe9ff);
  const jet = new THREE.Points(jetGeo, jetMat); jet.frustumCulled = false; jet.userData.noCount = true; nozzle.add(jet);

  // === 5. arms (instanced, hierarchical pose)
  const N = lite ? 14 : 22;
  const L0 = lite ? 0.225 : 0.175, LR = lite ? 0.94 : 0.962;
  const ARMS = 8;
  const armSpace = new THREE.Object3D();
  const arms = [];
  for (let a = 0; a < ARMS; a++) {
    const ang = ((a + 0.5) / ARMS) * TAU - 0.0;
    const base = new THREE.Object3D(); base.rotation.order = "YXZ";
    base.position.set(Math.sin(ang) * 0.43, -0.27, Math.cos(ang) * 0.43); base.rotation.y = ang;
    armSpace.add(base);
    const segs = []; let parent = base; let len = L0 * (0.92 + hash(a * 9.1) * 0.16);
    const lens = [];
    for (let j = 0; j < N; j++) {
      const s = new THREE.Object3D(); if (j > 0) s.position.z = lens[j - 1]; parent.add(s); segs.push(s); lens.push(len); parent = s; len *= LR;
    }
    arms.push({ ang, base, segs, lens, phase: hash(a * 3.3) * TAU, phase2: hash(a * 5.1) * TAU, curl: 0.85 + hash(a * 7.7) * 0.45, lift: (hash(a * 1.7) - 0.5) * 0.35 });
  }
  const radiusAt = (j) => 0.098 * Math.pow(1 - 0.82 * (j / N), 1.15) + 0.011;
  // geometries along +z
  const gLink = new THREE.CylinderGeometry(0.82, 1, 1, 16, 1); gLink.rotateX(Math.PI / 2); gLink.translate(0, 0, 0.5);
  const gJoint = new THREE.TorusGeometry(1, 0.22, 8, 22);
  const gPlate = new THREE.CylinderGeometry(1.0, 1.14, 1, 12, 1, true, Math.PI * 0.62, Math.PI * 0.76); gPlate.rotateX(Math.PI / 2); gPlate.translate(0, 0, 0.5);
  const gCup = new THREE.CylinderGeometry(1, 0.7, 1, 14, 1); gCup.translate(0, -0.5, 0);
  const gRim = new THREE.TorusGeometry(1, 0.18, 6, 16); gRim.rotateX(Math.PI / 2);
  const gPiston = new THREE.CylinderGeometry(1, 1, 1, 8); gPiston.rotateX(Math.PI / 2); gPiston.translate(0, 0, 0.5);
  const gClaw = new THREE.ConeGeometry(1, 1, 8); gClaw.rotateX(Math.PI / 2); gClaw.translate(0, 0, 0.5);
  const plateMat = new THREE.MeshPhysicalMaterial({ color: 0x67707f, metalness: 1, roughness: 0.38, clearcoat: 0.5, clearcoatRoughness: 0.3, envMapIntensity: 0.5, side: THREE.DoubleSide });
  const accentMat = M.cyan.clone(); accentMat.emissiveIntensity = 1.5;
  const I = {
    link: new THREE.InstancedMesh(gLink, M.gun, ARMS * N),
    joint: new THREE.InstancedMesh(gJoint, M.dark, ARMS * N),
    plate: new THREE.InstancedMesh(gPlate, plateMat, ARMS * N),
    cup: new THREE.InstancedMesh(gCup, M.black, ARMS * N),
    rim: new THREE.InstancedMesh(gRim, M.gun, ARMS * N),
    piston: new THREE.InstancedMesh(gPiston, M.chrome, ARMS * N * 2),
    accent: new THREE.InstancedMesh(gJoint, accentMat, ARMS * Math.ceil((N - 1) / 3)),
    claw: new THREE.InstancedMesh(gClaw, M.titan, ARMS * 3),
  };
  Object.values(I).forEach((im) => { im.instanceMatrix.setUsage(THREE.DynamicDrawUsage); im.frustumCulled = false; body.add(im); });
  const armAnchor = new THREE.Object3D(); body.add(armAnchor);

  // ---------- part count (real meshes; instanced parts counted per instance)
  function countParts() {
    let n = 0;
    scene.traverse((o) => { if (o.userData.noCount) return; if (o.isInstancedMesh) n += o.count; else if (o.isMesh) n += 1; });
    return n;
  }

  // ---------- pose state
  const S = { open: [0, 0, 0, 0, 0], explode: 0, spread: 1, jet: 0, pos: V(), rotX: 0, turn: 0, simT: 0, armBeat: 0, swim: 1 };

  const _m = new THREE.Matrix4(), _m2 = new THREE.Matrix4(), _p = V(), _q = new THREE.Quaternion(), _s = V(), _ax = V(), _ay = V(), _az = V(), _off = V(), _dir = V();
  const _e = new THREE.Euler(), _t = V();
  function stagger(e, d) { return eio(clamp((e * 1.6 - d) / 1.0)); }

  function poseArms() {
    const t = S.simT, sp = S.spread;
    const ka = S.open[4];
    for (let a = 0; a < ARMS; a++) {
      const A = arms[a];
      const sel = a === 0 ? ka : 0;
      const stroke = 0.5 + 0.5 * Math.sin(t * 1.15 + A.phase * 0.2);
      A.base.rotation.x = lerp(1.38, 0.22 + A.lift + 0.12 * stroke * S.swim, sp) - sel * 0.25;
      A.base.rotation.y = A.ang + Math.sin(t * 0.5 + A.phase) * 0.06 * S.swim;
      for (let j = 0; j < N; j++) {
        const u = j / N;
        const wave = Math.sin(t * 1.7 - j * 0.42 + A.phase) * S.swim;
        const curl = (0.035 + 0.34 * Math.pow(u, 2.1)) * A.curl;
        let bend = -lerp(0.02 + u * 0.05, curl, sp) + wave * 0.055 * (0.35 + u);
        bend *= 1 - sel * 0.75;
        A.segs[j].rotation.set(bend * (22 / N), Math.sin(t * 0.9 - j * 0.3 + A.phase2) * 0.045 * S.swim * (22 / N) * (1 - sel), 0);
      }
    }
    armSpace.updateMatrixWorld(true);
    let ia = 0, ic = 0;
    const eg = S.explode;
    for (let a = 0; a < ARMS; a++) {
      const A = arms[a];
      const sel = a === 0 ? ka : 0;
      for (let j = 0; j < N; j++) {
        const r = radiusAt(j), L = A.lens[j];
        const mw = A.segs[j].matrixWorld;
        mw.decompose(_p, _q, _s);
        _ax.setFromMatrixColumn(mw, 0); _ay.setFromMatrixColumn(mw, 1); _az.setFromMatrixColumn(mw, 2);
        const ge = stagger(eg, 0.15 + (j / N) * 0.35 + a * 0.02);
        _dir.set(_p.x, _p.y * 0.35 - 0.15, _p.z).normalize();
        const radial = (0.3 + j * (1.3 / N)) * ge;
        const fan = sel; // single-arm teardown
        const sepK = Math.max(ge * 0.9, fan);
        const base = _off.copy(_dir).multiplyScalar(radial).addScaledVector(_az, j * 0.05 * fan * (22 / N));
        const k = a * N + j;
        const put = (im, idx, lx, ly, lz, ox, oy, oz, sx, sy, sz) => {
          _t.copy(_p).add(base).addScaledVector(_ax, lx + ox * sepK).addScaledVector(_ay, ly + oy * sepK).addScaledVector(_az, lz + oz * sepK);
          _m.compose(_t, _q, _s.set(sx, sy, sz));
          im.setMatrixAt(idx, _m);
        };
        put(I.link, k, 0, 0, 0, 0, 0, 0, r, r, L * 0.96);
        put(I.joint, k, 0, 0, 0, 0, 0, -0.03, r * 1.1, r * 1.1, r * 1.3);
        put(I.plate, k, 0, 0, L * 0.06, 0, 0.16, 0, r * 1.02, r * 1.02, L * 0.78);
        const cupR = r * 0.44;
        put(I.cup, k, 0, -r * 0.92, L * 0.5, 0, -0.17, 0, cupR, r * 0.42, cupR);
        put(I.rim, k, 0, -r * 1.34, L * 0.5, 0, -0.2, 0, cupR * 1.02, cupR * 1.02, cupR * 1.02);
        const pump = 0.82 + 0.14 * Math.sin(S.simT * 3 + j * 0.7 + a);
        put(I.piston, k * 2, -r * 1.02, 0, L * 0.05, -0.14, 0, 0, r * 0.15, r * 0.15, L * pump);
        put(I.piston, k * 2 + 1, r * 1.02, 0, L * 0.05, 0.14, 0, 0, r * 0.15, r * 0.15, L * pump);
        if (j % 3 === 1) put(I.accent, ic++, 0, 0, L * 0.5, 0, 0, 0.02, r * 0.95, r * 0.95, r * 0.5);
        if (j === N - 1) {
          for (let c = 0; c < 3; c++) {
            const ca = (c / 3) * TAU;
            const cm = new THREE.Matrix4().compose(_p.clone().add(base).addScaledVector(_az, L * 0.85).addScaledVector(_ax, Math.cos(ca) * r * 0.7).addScaledVector(_ay, Math.sin(ca) * r * 0.7), _q, _s.set(r * 0.45, r * 0.45, r * 3.2));
            cm.multiply(_m2.makeRotationAxis(V(-Math.sin(ca), Math.cos(ca), 0), 0.35));
            I.claw.setMatrixAt(ia++, cm);
          }
        }
        if (a === 0 && j === Math.floor(N * 0.42)) armAnchor.position.copy(_p).add(base);
      }
    }
    Object.values(I).forEach((im) => { im.instanceMatrix.needsUpdate = true; });
  }

  function applyPose() {
    const t = S.simT;
    octo.position.copy(S.pos);
    octo.rotation.set(S.rotX, S.turn, 0, "YXZ");
    body.position.y = Math.sin(t * 0.8) * 0.05 * S.swim;
    body.rotation.z = Math.sin(t * 0.5) * 0.04 * S.swim;
    body.rotation.x = Math.sin(t * 0.63) * 0.03 * S.swim;
    const [k1, k2, k3, k4] = S.open;
    // beat transforms
    shellBeat.position.set(0, 0.65 + k1 * 1.75 + k3 * 1.3, k1 * 0.1 - k3 * 0.9);
    shellBeat.rotation.set(Math.PI * eio(k1) - k3 * 1.05, k1 * 0.6 * Math.sin(t * 0.7), k1 * 0.15);
    coreBeat.position.y = 0.32 + k3 * 0.85; coreBeat.scale.setScalar(1 + k3 * 0.25);
    const eR = eyes[1];
    eR.eb.position.set(Math.sin(0.56) * (0.6 + k2 * 0.32), 0.04 + k2 * 0.05, Math.cos(0.56) * (0.6 + k2 * 0.32));
    eR.exps.forEach((e, i) => e.bo.set(0, 0, eR.sep[i] * k2 * 1.15));
    siphonSegs.forEach((e, i) => e.bo.set(0, 0, i * 0.075 * k4));
    nozzleE.bo.set(0, 0, 0.45 * k4);
    fins.forEach((f, i) => { f.parent.rotation.y = 0; f.rotation.x = -k4 * 0.7; });
    // explode
    const E = S.explode;
    for (const x of explodables) {
      const ee = stagger(E, x.delay);
      x.obj.position.copy(x.base).add(x.bo).addScaledVector(x.dir, x.dist * ee);
      x.obj.rotation.set(x.rot.x + x.tumble * ee * 1.4 + x.br.x, x.rot.y + x.tumble * ee * 2.0 + x.br.y, x.rot.z + x.br.z);
    }
    // continuous mechanism motion
    const fast = 1 + k3 * 2.5;
    gears.forEach((g) => { g.g.rotation.z = t * g.sp * (1 + E * 0.5); });
    servoHorns.forEach((h, i) => { h.rotation.y = Math.sin(t * 2.2 + i) * 0.7; });
    coreRings.forEach((r, i) => { r.holder.rotation.z += 0; r.holder.children[0].parent.rotation.y = i * 1.3 + t * r.sp * fast; });
    coreBall.scale.setScalar(1 + 0.06 * Math.sin(t * 6));
    coreCage.rotation.y = -t * 0.8 * fast;
    coreLight.intensity = 1.8 + 0.5 * Math.sin(t * 5) + k3 * 1.2;
    eyes.forEach((e, i) => { e.iris.rotation.z = t * (0.4 + (i ? k2 * 3 : 0)); });
    impeller.rotation.z = t * (6 + k4 * 20 + S.jet * 30);
    finRing.rotation.y = t * 0.3;
    // jet particles
    const jetI = Math.max(S.jet, k4 * 0.8);
    for (let i = 0; i < JET_N; i++) {
      const life = 0.9, age = ((t * 1.4 + hash(i) * life) % life) / life;
      const sp = 0.25 + 2.6 * age * (0.5 + jetI);
      const jx = (hash(i * 2.1) - 0.5) * age * 0.35, jy = (hash(i * 3.7) - 0.5) * age * 0.35;
      jetPos[i * 3] = jx; jetPos[i * 3 + 1] = jy; jetPos[i * 3 + 2] = 0.03 + sp * age;
      jetSz[i] = (0.02 + age * 0.09) * jetI;
    }
    jetGeo.attributes.position.needsUpdate = true; jetGeo.attributes.size.needsUpdate = true;
    jetMat.uniforms.uOp.value = 0.8 * jetI;
    dust.rotation.y = t * 0.02; bokeh.rotation.y = t * 0.008; bokeh2.rotation.y = -t * 0.006;
    poseArms();
  }

  // ---------- anchors (world positions for cameras/cards)
  const anchors = [shellAnchor, eyes[1].anchor, coreAnchor, siphonAnchor, armAnchor];
  const anchorWorld = (i, out = V()) => anchors[i].getWorldPosition(out);
  const center = () => octo.localToWorld(V(0, 0.25, 0));

  // ---------- cameras
  const SHOTS = [
    { dir: V(-0.62, 0.22, 1), d0: 5.3, d1: 5.0, mix: 0.3, mix0: 1.0 },
    { dir: V(1.05, 0.3, 0.8), d0: 2.5, d1: 1.85, mix: 0.12 },
    { dir: V(0.45, 0.55, 1), d0: 3.1, d1: 2.4, mix: 0.3 },
    { dir: V(-0.85, -0.08, -0.95), d0: 2.5, d1: 1.9, mix: 0.2 },
    { dir: V(0.8, -0.55, 0.95), d0: 3.4, d1: 2.7, mix: 0.25 },
  ];
  SHOTS.forEach((s) => s.dir.normalize());
  const aspectK = () => { const a = camera.aspect; return a >= 1.45 ? 1 : a >= 1 ? 1.18 : 1.55 / Math.sqrt(Math.max(0.45, a)); };
  function shotBeat(i, t, B) {
    const s = SHOTS[i];
    const an = anchorWorld(i), c = center();
    const mx = s.mix0 != null ? lerp(s.mix0, s.mix, smooth((t - B) / OPEN)) : s.mix;
    const tgt = an.clone().lerp(c, mx);
    const push = smooth((t - B) / (OPEN + HOLD));
    const d = lerp(s.d0, s.d1, push) * aspectK();
    const dir = s.dir.clone().applyQuaternion(octo.quaternion);
    return { pos: tgt.clone().addScaledVector(dir, d), tgt };
  }
  function shotHero(t) {
    const c = center();
    const p = smooth(t / 2.6);
    const d = lerp(6.6, 5.2, p) * aspectK();
    const dir = V(0.55 + Math.sin(t * 0.3) * 0.05, 0.36, 1).normalize();
    return { pos: c.clone().addScaledVector(dir, d), tgt: c.clone().add(V(0, -0.3, 0)) };
  }
  function shotExplode(t) {
    const p = smooth((t - (EXP0 - 0.8)) / 6);
    const d = lerp(9.4, 8.3, p) * aspectK();
    const tgt = V(0, 0.9, 0);
    return { pos: tgt.clone().add(V(0.0, 0.42, 1).normalize().multiplyScalar(d)), tgt };
  }
  function shotOut(t) {
    const s = shotExplode(RE1);
    const q = smooth((t - OUT0) / 1.8);
    s.tgt.lerp(octo.position.clone().add(V(0, 0.3, 0)), 0.35 * q);
    return s;
  }
  const SEGS = [
    { t0: -1, f: shotHero },
    ...BEATS.map((B, i) => ({ t0: B - 0.85, f: (t) => shotBeat(i, t, B) })),
    { t0: EXP0 - 0.85, f: shotExplode },
    { t0: OUT0 - 0.4, f: shotOut },
  ];
  function camAt(t) {
    let i = 0; while (i + 1 < SEGS.length && t >= SEGS[i + 1].t0) i++;
    let s = SEGS[i].f(t);
    const bl = (t - SEGS[i].t0) / 0.85;
    if (i > 0 && bl < 1) {
      const p = SEGS[i - 1].f(t), k = eio(bl);
      s = { pos: p.pos.lerp(s.pos, k), tgt: p.tgt.lerp(s.tgt, k) };
    }
    return s;
  }

  // ---------- demo timeline → state
  function demoState(t) {
    S.simT = t;
    S.open = BEATS.map((B) => beatK(t, B));
    S.explode = explodeE(t);
    S.swim = 1;
    // jet in
    if (t < 3) {
      const p = eout(t / 2.6);
      S.pos.set(lerp(-0.6, 0, p), lerp(-3.4, 0, p), lerp(-9, 0, p));
      S.rotX = lerp(0.95, 0, eout(t / 2.3));
      S.spread = smooth((t - 0.55) / 1.7);
      S.jet = 1 - smooth((t - 1.4) / 1.2);
    } else { S.pos.set(0, 0, 0); S.rotX = 0; S.spread = 1; S.jet = 0; }
    S.turn = t >= TURN0 ? (TURN_DEG * Math.PI / 180) * eio((t - TURN0) / (TURN1 - TURN0)) : 0;
    if (t >= OUT0) {
      const qq = (t - OUT0) / (OUT1 - OUT0);
      S.spread = 1 - smooth(qq * 2.6) + 0.15 * Math.sin(qq * 20) * (1 - qq);
      S.rotX = -0.95 * smooth(qq * 2.2);
      S.jet = smooth(qq * 4);
      const dist = ein(qq) * 16 + qq * 0.4;
      S.pos.set(0, dist * 0.45, -dist);
    }
  }

  // ---------- DOM: HUD, pills, cursor, cards
  const elParts = q("[data-octo-parts]"), elLayer = q("[data-octo-layer]"), elTime = q("[data-octo-time]");
  const elStage = q("[data-octo-stage]"), elCap = q("[data-octo-caption]"), elCapT = q("[data-octo-caption-time]"), elCapS = q("[data-octo-caption-sub]");
  const elSteps = [...stage.querySelectorAll("[data-octo-step]")];
  const pills = [...stage.querySelectorAll("[data-octo-part]")];
  const pillAll = q("[data-octo-all]");
  const cursor = q("[data-octo-cursor]");
  const svg = q("[data-octo-leaders]");
  const card = q("[data-octo-card]");
  const labels = [...stage.querySelectorAll("[data-octo-label]")];
  const btnDemo = document.querySelector("[data-octo-demo]"), btnExplode = document.querySelector("[data-octo-explode]");
  const btnXray = document.querySelector("[data-octo-xray]"), btnReset = document.querySelector("[data-octo-reset]");
  const total = countParts();
  if (elParts) elParts.textContent = String(total);
  stage.querySelectorAll("[data-octo-total]").forEach((n) => (n.textContent = String(total)));

  const proj = (v) => { const p = v.clone().project(camera); return { x: (p.x * 0.5 + 0.5) * W, y: (-p.y * 0.5 + 0.5) * H, ok: p.z < 1 && p.z > -1 }; };
  function readout(i, t, k) {
    const f = (x, n = 0) => x.toFixed(n);
    switch (i) {
      case 0: return [["抬升", `${f(k * 1050)} mm`], ["翻转", `${f(eio(k) * 180)}°`], ["透光率", "92%"]];
      case 1: return [["光圈", `f/${f(1.4 + k * 6.6, 1)}`], ["镜组间距", `${f(k * 38)} mm`], ["追踪", "锁定"]];
      case 2: return [["转速", `${f(4200 + k * 7600 + Math.sin(t * 7) * 140)} rpm`], ["温度", `${f(312 + k * 96 + Math.sin(t * 3) * 3)} K`], ["输出", `${f(68 + k * 31)}%`]];
      case 3: return [["推力", `${f(k * 860 + Math.sin(t * 9) * 12)} N`], ["叶轮", `${f(2400 + k * 9000)} rpm`], ["伸长", `${f(k * 450)} mm`]];
      default: return [["链节", `${N} 节`], ["展开", `${f(k * 100)}%`], ["活塞行程", `${f(12 + Math.sin(t * 3) * 3, 1)} mm`]];
    }
  }
  let W = 1, H = 1;
  let lastCardPart = -1;
  function updateOverlay(t, info) {
    // status + caption
    if (elTime) elTime.textContent = info.time;
    if (elStage) elStage.textContent = info.status;
    if (elLayer) elLayer.textContent = info.layer;
    elSteps.forEach((s, i) => { s.classList.toggle("on", i === info.phase); s.classList.toggle("done", i < info.phase); });
    if (elCap) {
      elCap.classList.toggle("show", !!info.cap);
      if (info.cap) { elCapT.textContent = info.capT; q("[data-octo-caption-title]").textContent = info.cap; elCapS.textContent = info.capSub; }
    }
    pills.forEach((p, i) => { p.classList.toggle("is-on", info.part === i); p.classList.toggle("is-press", info.press === i); });
    if (pillAll) { pillAll.classList.toggle("is-on", info.allOn); pillAll.classList.toggle("is-press", info.press === 5); pillAll.textContent = info.allLabel || "全部拆解"; }
    // card + leader
    let paths = "";
    const showCard = info.part >= 0 && info.k > 0.35;
    if (card) {
      card.classList.toggle("show", showCard);
      if (showCard) {
        const i = info.part;
        const a = proj(anchorWorld(i));
        const cw = card.offsetWidth || 220, ch = card.offsetHeight || 120;
        const left = a.x > W * 0.52;
        let cx = left ? a.x - cw - Math.min(140, W * 0.12) : a.x + Math.min(140, W * 0.12);
        let cy = a.y - ch - Math.min(70, H * 0.1);
        cx = clamp(cx, 12, W - cw - 12); cy = clamp(cy, 56, H - ch - 70);
        card.style.transform = `translate(${cx.toFixed(1)}px, ${cy.toFixed(1)}px)`;
        if (lastCardPart !== i) {
          lastCardPart = i;
          card.querySelector("[data-card-en]").textContent = `0${i + 1} · ${PARTS[i].en}`;
          card.querySelector("[data-card-name]").textContent = PARTS[i].name;
          card.querySelector("[data-card-fn]").textContent = PARTS[i].fn;
        }
        card.querySelector("[data-card-read]").innerHTML = readout(i, t, info.k).map(([k, v]) => `<span><i>${k}</i><b>${v}</b></span>`).join("");
        const ex = left ? cx + cw : cx, ey = cy + ch * 0.5;
        const mx = left ? ex + 26 : ex - 26;
        paths += `<path d="M${a.x.toFixed(1)} ${a.y.toFixed(1)} L${mx.toFixed(1)} ${ey.toFixed(1)} L${ex.toFixed(1)} ${ey.toFixed(1)}" class="ld"/><circle cx="${a.x.toFixed(1)}" cy="${a.y.toFixed(1)}" r="4" class="dot"/><circle cx="${a.x.toFixed(1)}" cy="${a.y.toFixed(1)}" r="${(9 + 4 * Math.sin(t * 6)).toFixed(1)}" class="ring"/>`;
      }
    }
    // explode labels
    const lv = info.labels;
    labels.forEach((lb, i) => {
      lb.classList.toggle("show", lv > 0.5);
      if (lv > 0.5) {
        const a = proj(anchorWorld(i));
        const dx = (i % 2 ? 1 : -1) * 46, dy = -30 - (i % 3) * 10;
        const lx = clamp(a.x + dx, 8, W - 120), ly = clamp(a.y + dy, 50, H - 60);
        lb.style.transform = `translate(${lx.toFixed(1)}px, ${(ly - 12).toFixed(1)}px)`;
        paths += `<path d="M${a.x.toFixed(1)} ${a.y.toFixed(1)} L${lx.toFixed(1)} ${ly.toFixed(1)}" class="ld thin"/><circle cx="${a.x.toFixed(1)}" cy="${a.y.toFixed(1)}" r="3" class="dot"/>`;
      }
    });
    if (svg) svg.innerHTML = paths;
    // cursor
    if (cursor) {
      cursor.classList.toggle("show", info.cursor != null);
      if (info.cursor) {
        cursor.style.transform = `translate(${info.cursor.x.toFixed(1)}px, ${info.cursor.y.toFixed(1)}px) scale(${info.cursor.s.toFixed(3)})`;
        cursor.classList.toggle("click", !!info.cursor.click);
      }
    }
  }
  const stageRect = () => stage.getBoundingClientRect();
  function elCenter(el) {
    const r = el.getBoundingClientRect(), s = stageRect();
    return { x: r.left - s.left + r.width * 0.55, y: r.top - s.top + r.height * 0.6 };
  }
  const CLICKS = [...BEATS.map((B, i) => ({ t: B - 0.12, el: () => pills[i], id: i })), { t: EXP0 - 0.12, el: () => pillAll, id: 5 }];
  function demoCursor(t) {
    if (!pills.length) return null;
    const rest = { x: W * 0.86, y: H * 0.62 };
    if (t > OUT0 + 0.8) return null;
    let prev = rest, cur = null;
    for (let i = 0; i < CLICKS.length; i++) {
      const c = CLICKS[i]; const target = c.el() ? elCenter(c.el()) : rest;
      if (t < c.t - 0.95) { cur = prev; break; }
      if (t < c.t - 0.15) { const k = eio((t - (c.t - 0.95)) / 0.8); cur = { x: lerp(prev.x, target.x, k), y: lerp(prev.y, target.y, k) - Math.sin(k * Math.PI) * 30 }; break; }
      prev = target; cur = target;
    }
    if (!cur) cur = prev;
    if (t > RE1) { const k = eio((t - RE1) / 1.2); cur = { x: lerp(cur.x, rest.x, k), y: lerp(cur.y, rest.y, k) }; }
    let s = 1, click = false;
    for (const c of CLICKS) { const d = t - c.t; if (d > -0.12 && d < 0.18) { s = 1 - 0.16 * Math.sin(clamp((d + 0.12) / 0.3) * Math.PI); click = true; } }
    return { x: cur.x, y: cur.y, s, click };
  }
  function demoInfo(t) {
    let ph = 0; for (let i = 0; i < PHASES.length; i++) if (t >= PHASES[i].t) ph = i;
    const P = PHASES[ph];
    let part = -1, k = 0, sub = "";
    BEATS.forEach((B, i) => { const kk = beatK(t, B); if (t >= B - 0.85 && t < B + OPEN + HOLD + CLOSE) { part = i; k = kk; } });
    if (part >= 0) { const B = BEATS[part]; sub = t < B ? "准备" : t < B + OPEN ? "展开中" : t < B + OPEN + HOLD ? "保持 · 运转中" : "闭合中"; }
    else if (ph === 6) sub = t < EXP1 ? "展开中" : "330° 转台";
    else if (ph === 7) sub = "归位中";
    else if (ph === 0) sub = t < 2.6 ? "推进中" : "就位";
    else if (ph === 8) sub = "推进中";
    let press = -1; CLICKS.forEach((c) => { if (t - c.t > -0.12 && t - c.t < 0.25) press = c.id; });
    const capAt = P.at != null ? P.at : P.t;
    return {
      time: fmtT(t), status: `阶段 ${ph + 1}/${PHASES.length} · ${P.name}${sub ? " · " + sub : ""}`,
      layer: part >= 0 ? PARTS[part].name : ph === 6 ? "全部零件" : "整机",
      phase: ph, part, k, press, allOn: t >= EXP0 && t < RE1, allLabel: t >= EXP0 - 0.12 && t < RE0 ? "组装" : "全部拆解",
      cap: P.cap, capT: fmtT(capAt), capSub: P.sub, labels: S.explode, cursor: demoCursor(t),
    };
  }

  // ---------- renderer / composer
  let composer = null, bloom = null;
  if (!lite) {
    const rt = new THREE.WebGLRenderTarget(2, 2, { type: THREE.HalfFloatType, samples: 4 });
    composer = new EffectComposer(renderer, rt);
    composer.addPass(new RenderPass(scene, camera));
    bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.42, 0.45, 1.15);
    composer.addPass(bloom);
    composer.addPass(new OutputPass());
  }
  function resize() {
    const r = canvasHost.getBoundingClientRect();
    W = Math.max(1, Math.round(r.width)); H = Math.max(1, Math.round(r.height));
    renderer.setSize(W, H, false);
    renderer.domElement.style.width = W + "px"; renderer.domElement.style.height = H + "px";
    camera.aspect = W / H; camera.updateProjectionMatrix();
    if (composer) { composer.setPixelRatio(renderer.getPixelRatio()); composer.setSize(W, H); }
    [bokeh, bokeh2, dust, jet].forEach((p) => (p.material.uniforms.uScale.value = H * renderer.getPixelRatio() * 0.9));
  }
  resize();
  const ro = new ResizeObserver(() => { resize(); if (!running) renderOnce(); }); ro.observe(canvasHost);

  // ---------- controls / modes
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.dampingFactor = 0.08; controls.enablePan = false;
  controls.minDistance = 1.2; controls.maxDistance = 14; controls.enabled = false;
  let mode = "demo", demoT = 0, frozen = false;
  const man = { open: [0, 0, 0, 0, 0], target: [0, 0, 0, 0, 0], prog: [0, 0, 0, 0, 0], exp: 0, expT: 0, expP: 0, part: -1, cam: null, xray: false };

  function toManual() {
    if (mode === "manual") return;
    mode = "manual";
    if (sfx) sfx.cancel();
    man.prog = S.open.slice(); man.target = [0, 0, 0, 0, 0]; man.expP = S.explode; man.expT = S.explode > 0.5 ? 1 : 0; man.part = -1;
    controls.target.copy(camera.userData.tgt || V(0, 0.25, 0)); controls.enabled = true;
    stage.classList.remove("is-demo"); syncButtons();
  }
  function startDemo() {
    if (sfx) sfx.cancel(); evIdx = 0; lastDemoT = -1;
    mode = "demo"; demoT = 0; controls.enabled = false; stage.classList.add("is-demo"); syncButtons();
    if (reduced) { demoT = 4.6; }
    kick();
  }
  // ---------- sound (default ON; shared unlock in vendor/site-audio.js). 减少动态 → no drone / no autoplayed film sound
  let sfx = null, soundOn = false, evIdx = 0, lastDemoT = -1;
  const resyncSfx = () => { evIdx = SFX_EVENTS.findIndex((e) => e.t >= demoT); if (evIdx < 0) evIdx = SFX_EVENTS.length; };
  const snd = createSoundSwitch({
    storageKey: "ai168-octo-sound",
    buttons: [...document.querySelectorAll("[data-octo-sound]")],
    cta: stage.querySelector("[data-octo-sound-cta]"),
    root: stage,
    createEngine: (ctx) => (sfx = createSfx(ctx)),
    onOn: (e) => { soundOn = true; if (!reduced) e.startDrone(); resyncSfx(); },
    onOff: (e) => { soundOn = false; e.cancel(); e.stopDrone(); },
    onRunning: () => resyncSfx(),
  });
  soundOn = snd.on;
  function enableSound(on) { if (on) snd.enable(); else snd.disable(); soundOn = snd.on; }
  function sfxNow(type, args = [], delay = 0) { if (sfx && soundOn) sfx.play({ type, args }, sfx.ctx.currentTime + 0.02 + delay); }

  function camTween(toPos, toTgt, dur = 1.1) { man.cam = { fromP: camera.position.clone(), fromT: controls.target.clone(), toP: toPos, toT: toTgt, t: 0, dur: reduced ? 0.001 : dur }; }
  function manualShot(i) {
    S.pos.set(0, 0, 0); S.rotX = 0; octo.position.set(0, 0, 0); octo.rotation.set(0, S.turn, 0); octo.updateMatrixWorld(true);
    const keep = S.open.slice(); S.open = S.open.map((_, j) => (j === i ? 1 : 0)); applyPose(); octo.updateMatrixWorld(true);
    const s = shotBeat(i, 99, 0); S.open = keep; applyPose();
    return s;
  }
  function selectPart(i) {
    toManual();
    const on = man.target[i] < 0.5;
    sfxNow("blip");
    man.target.forEach((v, j) => { if (v > 0.5 && j !== i) { sfxNow("close", [j, CLOSE]); sfxNow("snap", [j], CLOSE); } });
    if (man.expT > 0.5) sfxNow("reassemble", [1.2]);
    if (on) { sfxNow("open", [i, OPEN]); sfxNow("lock", [i], OPEN); if (i === 0) sfxNow("shimmer", [], 0.12); if (i === 2) sfxNow("hum", [2.2]); }
    else { sfxNow("close", [i, CLOSE]); sfxNow("snap", [i], CLOSE); }
    man.target = man.target.map((_, j) => (j === i && on ? 1 : 0));
    man.expT = 0; man.part = on ? i : -1;
    const s = on ? manualShot(i) : shotHero(4);
    camTween(s.pos, s.tgt);
    kick();
  }
  function toggleExplode() {
    toManual();
    man.expT = man.expT > 0.5 ? 0 : 1; man.target = [0, 0, 0, 0, 0]; man.part = -1;
    if (man.expT) sfxNow("explode", [1.4]); else sfxNow("reassemble", [1.2]);
    const s = man.expT ? shotExplode(EXP0 + 3) : shotHero(4);
    camTween(s.pos, s.tgt);
    kick();
  }
  function setXray(on) {
    man.xray = on;
    glass.material = on ? wireMat : M.glass;
    fres.visible = !on;
    plateMat.transparent = on; plateMat.opacity = on ? 0.12 : 1; plateMat.depthWrite = !on; plateMat.needsUpdate = true;
    I.link.material = on ? M.gun.clone() : M.gun;
    if (on) { I.link.material.transparent = true; I.link.material.opacity = 0.35; I.link.material.depthWrite = false; }
    collar.children.forEach((g) => g.traverse((o) => { if (o.isMesh && o.material === M.titan) { o.userData.m = o.material; o.material = wireMat; } else if (o.isMesh && !on && o.userData.m) { o.material = o.userData.m; } }));
    if (btnXray) { btnXray.setAttribute("aria-pressed", on ? "true" : "false"); btnXray.querySelector("b").textContent = on ? "透视" : "实体"; }
    kick();
  }
  function syncButtons() {
    if (btnDemo) btnDemo.setAttribute("aria-pressed", mode === "demo" ? "true" : "false");
    if (btnExplode) btnExplode.textContent = (mode === "manual" ? man.expT > 0.5 : S.explode > 0.5) ? "组装" : "拆解";
  }
  pills.forEach((p, i) => p.addEventListener("click", (ev) => { ev.preventDefault(); selectPart(i); syncButtons(); }));
  if (pillAll) pillAll.addEventListener("click", (ev) => { ev.preventDefault(); sfxNow("blip"); toggleExplode(); syncButtons(); });
  if (btnExplode) btnExplode.addEventListener("click", () => { toggleExplode(); syncButtons(); });
  if (btnDemo) btnDemo.addEventListener("click", () => { enableSound(true); startDemo(); });
  if (btnXray) btnXray.addEventListener("click", () => setXray(!man.xray));
  if (btnReset) btnReset.addEventListener("click", () => { toManual(); if (man.expT > 0.5) sfxNow("reassemble", [1.2]); else if (man.target.some((v) => v > 0.5)) { const j = man.target.findIndex((v) => v > 0.5); sfxNow("close", [j, CLOSE]); sfxNow("snap", [j], CLOSE); } man.target = [0, 0, 0, 0, 0]; man.expT = 0; man.part = -1; const s = shotHero(4); camTween(s.pos, s.tgt); kick(); syncButtons(); });
  renderer.domElement.addEventListener("pointerdown", () => { if (mode === "demo") toManual(); });
  renderer.domElement.addEventListener("wheel", () => { if (mode === "demo") toManual(); }, { passive: true });
  controls.addEventListener("change", () => { if (!running) renderOnce(); });

  function manualStep(dt) {
    S.simT += reduced ? 0 : dt;
    for (let i = 0; i < 5; i++) {
      const tgt = man.target[i];
      if (reduced) man.prog[i] = tgt;
      else if (man.prog[i] < tgt) man.prog[i] = Math.min(tgt, man.prog[i] + dt / OPEN);
      else if (man.prog[i] > tgt) man.prog[i] = Math.max(tgt, man.prog[i] - dt / CLOSE);
    }
    S.open = man.prog.map((p) => eio(p));
    if (reduced) man.expP = man.expT; else man.expP += clamp(man.expT - man.expP, -dt / 1.2, dt / 1.4);
    S.explode = eio(man.expP);
    const f = 1 - Math.exp(-dt * 3);
    S.pos.lerp(V(), reduced ? 1 : f); S.rotX = lerp(S.rotX, 0, reduced ? 1 : f); S.spread = lerp(S.spread, 1, reduced ? 1 : f); S.jet = lerp(S.jet, 0, reduced ? 1 : f);
    S.swim = reduced ? 0 : 1;
    if (man.cam) {
      const c = man.cam; c.t += dt; const k = eio(c.t / c.dur);
      camera.position.lerpVectors(c.fromP, c.toP, k); controls.target.lerpVectors(c.fromT, c.toT, k);
      if (c.t >= c.dur) man.cam = null;
    }
    controls.update();
    const i = man.part;
    return {
      time: "手动", status: man.expT > 0.5 ? "手动 · 全机拆解" : i >= 0 ? `手动 · ${PARTS[i].name}` : "手动 · 拖动旋转，滚轮缩放",
      layer: man.expT > 0.5 ? "全部零件" : i >= 0 ? PARTS[i].name : "整机", phase: -1, part: i, k: i >= 0 ? S.open[i] : 0, press: -1,
      allOn: man.expT > 0.5, allLabel: man.expT > 0.5 ? "组装" : "全部拆解", cap: null, labels: S.explode, cursor: null,
    };
  }

  function step(dt) {
    let info;
    if (mode === "demo") {
      if (!frozen) { demoT += dt; if (demoT >= LOOP) demoT = 0; }
      if (sfx && soundOn && !frozen && !reduced && sfx.ctx.state === "running") {
        if (demoT < lastDemoT) evIdx = 0;
        while (evIdx < SFX_EVENTS.length && SFX_EVENTS[evIdx].t <= demoT + 0.12) {
          const e = SFX_EVENTS[evIdx++];
          if (e.t >= demoT - 0.06) sfx.play(e, sfx.ctx.currentTime + Math.max(0, e.t - demoT));
        }
      }
      lastDemoT = demoT;
      demoState(demoT);
      applyPose(); octo.updateMatrixWorld(true);
      const s = camAt(demoT);
      camera.position.copy(s.pos); camera.lookAt(s.tgt); camera.userData.tgt = s.tgt;
      info = demoInfo(demoT);
    } else {
      info = manualStep(dt);
      applyPose(); octo.updateMatrixWorld(true);
    }
    camera.updateMatrixWorld();
    updateOverlay(mode === "demo" ? demoT : S.simT, info);
    if (composer) composer.render(); else renderer.render(scene, camera);
    syncBtnLite();
  }
  let lastExpLabel = "";
  function syncBtnLite() { if (!btnExplode) return; const l = (mode === "manual" ? man.expT > 0.5 : S.explode > 0.5) ? "组装" : "拆解"; if (l !== lastExpLabel) { lastExpLabel = l; btnExplode.textContent = l; } }

  // ---------- loop (pauses offscreen / hidden / reduced-motion idle)
  let running = false, raf = 0, last = 0, visible = true, idleFrames = 0;
  function frame(now) {
    raf = 0;
    if (frozen) { running = false; return; }
    const dt = Math.min(0.1, (now - last) / 1000 || 0.016); last = now;
    step(dt);
    const busy = man.cam || man.prog.some((p, i) => p !== man.target[i]) || Math.abs(man.expP - man.expT) > 1e-4;
    if (reduced && mode === "manual" && !busy && !controls.enableDamping) { running = false; return; }
    if (reduced && mode === "manual" && !busy) { if (++idleFrames > 30) { running = false; return; } } else idleFrames = 0;
    if (!visible || document.hidden) { running = false; return; }
    raf = requestAnimationFrame(frame);
  }
  function kick() { if (frozen) { renderOnce(); return; } if (!running) { running = true; last = performance.now(); raf = requestAnimationFrame(frame); } }
  function renderOnce() { step(0); }
  new IntersectionObserver((es) => { visible = es[0].isIntersecting; if (visible) kick(); }).observe(stage);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) kick(); });
  window.addEventListener("ai168:reduce-motion", () => {
    reduced = isReduced();
    if (reduced && mode === "demo") { toManual(); }
    if (sfx && soundOn) { if (reduced) sfx.stopDrone(); else sfx.startDrone(); }
    kick();
  });

  // start
  if (reduced) { mode = "manual"; controls.enabled = true; const s = shotHero(4); camera.position.copy(s.pos); controls.target.copy(s.tgt); stage.classList.remove("is-demo"); }
  else stage.classList.add("is-demo");
  syncButtons();
  stage.classList.add("ready");
  kick();

  // deterministic hooks for screenshots / film capture
  window.__octo = {
    parts: total,
    seek(t) { frozen = true; mode = "demo"; controls.enabled = false; demoT = t; step(0); return true; },
    play() { frozen = false; startDemo(); },
    manual: { selectPart, toggleExplode, setXray },
    settle() { man.prog = man.target.slice(); man.expP = man.expT; if (man.cam) { man.cam.t = man.cam.dur; } step(0.016); return mode; },
    renderer,
    sfxEvents: SFX_EVENTS,
    audio: { state: () => snd.state(), on: () => snd.on, fail: () => snd.fail, rms: () => (sfx ? sfx.rms() : 0) },
    async renderAudio(duration = LOOP) {
      const buf = await renderOffline(SFX_EVENTS, duration, 48000);
      const bytes = new Uint8Array(toWav(buf)); let bin = "";
      for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
      return btoa(bin);
    },
  };
  return true;
}
