/* 星际信号站 · 匿名留言板  (three.js r160, no build step)
   Messages are glowing stars in a 3D galaxy. Posting = encrypted envelope → public relay
   → GitHub Actions moderation (strict, server-side) → api/board.json. */
import * as THREE from './three.module.min.js';

const $ = (s, r = document) => r.querySelector(s);
const CFG = JSON.parse($('#board-cfg').textContent);
const BASE = CFG.base || '/';
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const mobile = Math.min(innerWidth, innerHeight) < 720;
const T0 = Date.now();
const LS_MINE = 'aiym_board_mine_v1', LS_NICK = 'aiym_board_nick_v1', LS_DEV = 'aiym_board_dev_v1', LS_LAST = 'aiym_board_last_v1';

/* ---------------- helpers ---------------- */
const hex = (n) => Array.from(crypto.getRandomValues(new Uint8Array(n)), b => b.toString(16).padStart(2, '0')).join('');
const b64 = (buf) => { let s = ''; const u = new Uint8Array(buf); for (let i = 0; i < u.length; i++) s += String.fromCharCode(u[i]); return btoa(s); };
const unb64 = (s) => Uint8Array.from(atob(s), c => c.charCodeAt(0));
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
function fmtTime(t) { const d = new Date(t * 1000); const p = n => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`; }
function ago(t) { const s = Date.now() / 1000 - t; if (s < 90) return '刚刚'; if (s < 3600) return Math.floor(s / 60) + ' 分钟前'; if (s < 86400) return Math.floor(s / 3600) + ' 小时前'; return Math.floor(s / 86400) + ' 天前'; }
function hashNum(str) { let h = 2166136261; for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); } return (h >>> 0) / 4294967295; }
function toast(msg, kind = '') { const t = $('#bd-toast'); t.textContent = msg; t.className = 'bd-toast show ' + kind; clearTimeout(toast._t); toast._t = setTimeout(() => t.className = 'bd-toast', 4200); }

/* sync SHA-256 (for proof-of-work; WebCrypto is async and too slow per hash) */
const K = new Uint32Array([0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2]);
const W = new Uint32Array(64);
function sha256hex(bytes) {
  const l = bytes.length, nb = ((l + 9 + 63) >> 6) << 6, m = new Uint8Array(nb);
  m.set(bytes); m[l] = 0x80; const bl = l * 8; const dv = new DataView(m.buffer); dv.setUint32(nb - 4, bl >>> 0); dv.setUint32(nb - 8, Math.floor(bl / 4294967296));
  let h0 = 0x6a09e667, h1 = 0xbb67ae85, h2 = 0x3c6ef372, h3 = 0xa54ff53a, h4 = 0x510e527f, h5 = 0x9b05688c, h6 = 0x1f83d9ab, h7 = 0x5be0cd19;
  for (let o = 0; o < nb; o += 64) {
    for (let i = 0; i < 16; i++) W[i] = dv.getUint32(o + i * 4);
    for (let i = 16; i < 64; i++) { const a = W[i - 15], b = W[i - 2]; const s0 = ((a >>> 7) | (a << 25)) ^ ((a >>> 18) | (a << 14)) ^ (a >>> 3); const s1 = ((b >>> 17) | (b << 15)) ^ ((b >>> 19) | (b << 13)) ^ (b >>> 10); W[i] = (W[i - 16] + s0 + W[i - 7] + s1) | 0; }
    let a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, h = h7;
    for (let i = 0; i < 64; i++) {
      const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7)); const ch = (e & f) ^ (~e & g); const t1 = (h + S1 + ch + K[i] + W[i]) | 0;
      const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10)); const mj = (a & b) ^ (a & c) ^ (b & c); const t2 = (S0 + mj) | 0;
      h = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0;
    }
    h0 = (h0 + a) | 0; h1 = (h1 + b) | 0; h2 = (h2 + c) | 0; h3 = (h3 + d) | 0; h4 = (h4 + e) | 0; h5 = (h5 + f) | 0; h6 = (h6 + g) | 0; h7 = (h7 + h) | 0;
  }
  return [h0, h1, h2, h3, h4, h5, h6, h7].map(x => (x >>> 0).toString(16).padStart(8, '0')).join('');
}
const enc = new TextEncoder();
async function proofOfWork(prefixStr, onProgress) {
  const want = CFG.pow_prefix || '0000';
  let nonce = 0; const t = performance.now();
  while (true) {
    for (let i = 0; i < 4000; i++, nonce++) {
      if (sha256hex(enc.encode(prefixStr + nonce)).startsWith(want)) return String(nonce);
    }
    onProgress && onProgress(nonce);
    await new Promise(r => setTimeout(r, 0));
    if (performance.now() - t > 60000) throw new Error('pow-timeout');
  }
}

/* ---------------- client-side pre-check (server re-checks strictly) ---------------- */
let RULES = null;
fetch(BASE + 'vendor/board-rules.json').then(r => r.json()).then(j => {
  const dec = (s) => new TextDecoder().decode(unb64(s)).split('\n').filter(Boolean);
  RULES = { words: dec(j.w), latin: dec(j.l), prefix: dec(j.p) };
}).catch(() => {});
const CN_NUM = { '零': 0, '〇': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '壹': 1, '贰': 2, '叁': 3, '肆': 4, '伍': 5, '陆': 6, '柒': 7, '捌': 8, '玖': 9, '两': 2, '幺': 1 };
function compactText(s) { return (s || '').normalize('NFKC').toLowerCase().replace(/[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]/g, '').replace(/\$/g, 's').replace(/[^0-9a-z\u3400-\u9fff]+/g, ''); }
function precheck(text, nick) {
  const raw = (text || '').trim();
  if (!raw) return '先写点什么吧，宇宙在等你的信号。';
  if (raw.length > CFG.max_len) return `信号太长啦，请控制在 ${CFG.max_len} 字以内。`;
  if ((nick || '').length > CFG.max_nick) return `昵称最多 ${CFG.max_nick} 个字。`;
  for (const [s, isNick] of [[raw, false], [nick || '', true]]) {
    const c = compactText(s); if (!c) continue;
    if (!isNick) { const n = (c.match(/[\u3400-\u9fff]/g) || []).length; if (n < 2 || n < 0.3 * c.length) return '请用中文留言（至少包含两个汉字）。'; }
    const ns = s.normalize('NFKC').toLowerCase().replace(/\s+/g, '');
    if (/(https?|ftp)[:：]|www\.|:\/|\/\/|[a-z0-9-]+(\.|点|。|dot)(com|cn|net|org|top|xyz|io|me|cc|vip|info|site|club|app|ai|dev|link|shop|tv|co)(?![a-z])/.test(ns)) return '为防止广告，留言中不能包含网址或链接。';
    if (/[a-z0-9._%+-]+\s*(@|＠)\s*[a-z0-9-]+/.test(ns)) return '为保护隐私，留言中不能包含邮箱。';
    const dv = c.replace(/./g, ch => (ch in CN_NUM ? CN_NUM[ch] : ch));
    if (/\d{5,}/.test(dv)) return '为保护隐私、防止引流，留言中不能出现手机号、QQ、微信等联系方式。';
    if (RULES) {
      for (const w of RULES.words) if (w && c.includes(w)) return isNick ? '昵称含有不适宜的内容，请换一个。' : '信号含有不适宜的内容（涉政、辱骂、色情、赌博、诈骗或广告等），已被星际防火墙拦截。请文明友善地交流。';
      for (const run of c.match(/[a-z0-9]+/g) || []) {
        if (RULES.prefix.some(p => run.startsWith(p))) return '为保护隐私、防止引流，留言中不能出现手机号、QQ、微信等联系方式。';
        if (RULES.latin.some(w => run === w || (w.length >= 5 && run.includes(w)))) return isNick ? '昵称含有不适宜的内容，请换一个。' : '信号含有不适宜的内容，已被星际防火墙拦截。请文明友善地交流。';
      }
    }
  }
  return '';
}

/* ---------------- identity ---------------- */
const CODENAMES = ['星际旅人', '量子信使', '银河漫游者', '光年行者', '星云观测员', '虫洞拾荒者', '赛博游侠', '深空领航员', '引力波猎手', '暗物质诗人', '脉冲星听众', '轨道守望者', '彗星骑手', '超新星信徒', '星图绘制师'];
function codename() { return `${CODENAMES[Math.floor(Math.random() * CODENAMES.length)]}-${hex(2).toUpperCase()}`; }
function deviceId() { let d = localStorage.getItem(LS_DEV); if (!d) { d = hex(16); localStorage.setItem(LS_DEV, d); } return d; }
async function fingerprint() {
  const parts = [navigator.userAgent, navigator.language, screen.width + 'x' + screen.height, screen.colorDepth, Intl.DateTimeFormat().resolvedOptions().timeZone, navigator.hardwareConcurrency, deviceId()].join('|');
  return sha256hex(enc.encode(parts)).slice(0, 24);
}

/* ---------------- encryption (RSA-OAEP-256 + AES-GCM-256) ---------------- */
let pubKeyP = null;
function pubKey() { return pubKeyP || (pubKeyP = crypto.subtle.importKey('spki', unb64(CFG.pubkey_spki), { name: 'RSA-OAEP', hash: 'SHA-256' }, false, ['encrypt'])); }
async function seal(obj) {
  const aes = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, true, ['encrypt']);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, aes, enc.encode(JSON.stringify(obj)));
  const raw = await crypto.subtle.exportKey('raw', aes);
  const ek = await crypto.subtle.encrypt({ name: 'RSA-OAEP' }, await pubKey(), raw);
  return ['ab1', b64(ek), b64(iv), b64(ct)].join('.');
}

/* ---------------- data ---------------- */
let MESSAGES = [];
const mine = () => { try { return JSON.parse(localStorage.getItem(LS_MINE) || '[]'); } catch { return []; } };
const saveMine = (l) => localStorage.setItem(LS_MINE, JSON.stringify(l.slice(-30)));
async function loadBoard() {
  try {
    const r = await fetch(BASE + 'api/board.json?t=' + Math.floor(Date.now() / 60000), { cache: 'no-store' });
    if (r.ok) { const j = await r.json(); MESSAGES = j.messages || []; $('#bd-updated').textContent = (j.updated || '').replace(' Asia/Shanghai', ''); }
  } catch (e) {}
  renderList(); renderStats(); Galaxy.sync();
}
function renderStats() {
  const now = Date.now() / 1000;
  const today = MESSAGES.filter(m => now - m.t < 86400).length;
  countUp($('#bd-total'), MESSAGES.length); countUp($('#bd-today'), today);
  $('#bd-latest').textContent = MESSAGES[0] ? ago(MESSAGES[0].t) : '等待第一颗星';
}
function countUp(node, to) { const from = +node.textContent || 0; const t0 = performance.now(); const step = (t) => { const k = Math.min(1, (t - t0) / 900); node.textContent = Math.round(from + (to - from) * (1 - Math.pow(1 - k, 3))); if (k < 1) requestAnimationFrame(step); }; requestAnimationFrame(step); }

function card(m, pending) {
  const c = el('article', 'bd-card' + (pending ? ' pending' : ''));
  c.style.setProperty('--h', m.hue ?? 190);
  const head = el('header', 'bd-card-h');
  head.append(el('i', 'bd-dot'), el('b', '', m.nick || '匿名旅人'), el('span', 'bd-id', m.id || '审核中'), el('time', '', m.t ? fmtTime(m.t) : ''));
  const p = el('p', '', m.text);   // textContent only — never innerHTML (XSS-safe)
  c.append(head, p);
  c.addEventListener('click', () => { if (m.id) { Galaxy.focus(m.id); document.getElementById('bd-stage').scrollIntoView({ behavior: 'smooth' }); } });
  return c;
}
function renderList() {
  const box = $('#bd-list'); box.textContent = '';
  const q = ($('#bd-q').value || '').trim().toLowerCase();
  const rows = MESSAGES.filter(m => !q || (m.text + m.nick + m.id).toLowerCase().includes(q));
  if (!rows.length) { box.append(el('div', 'bd-empty', MESSAGES.length ? '没有匹配的信号' : '星空还很安静……成为第一个发射信号的人吧。')); return; }
  rows.forEach((m, i) => { const c = card(m); c.style.animationDelay = Math.min(i, 20) * 40 + 'ms'; box.append(c); });
}
function renderMine() {
  const box = $('#bd-mine-list'); box.textContent = '';
  const l = mine().slice().reverse();
  $('#bd-mine').classList.toggle('has', l.length > 0);
  l.slice(0, 6).forEach(x => {
    const row = el('div', 'bd-mine-row ' + x.s);
    const st = { pending: '审核中 · 约 10–30 分钟出现在星空', ok: '已点亮 · ' + (x.id || ''), rej: '已拦截' }[x.s] || x.s;
    row.append(el('span', 'bd-mine-s', st), el('p', '', x.text));
    if (x.s === 'rej' && x.msg) row.append(el('small', '', x.msg));
    box.append(row);
  });
}
async function pollReceipts() {
  const l = mine(); if (!l.some(x => x.s === 'pending')) return;
  try {
    const r = await fetch(BASE + 'api/board_receipts.json?t=' + Date.now(), { cache: 'no-store' });
    if (!r.ok) return; const rec = await r.json(); let changed = false, lit = false;
    for (const x of l) { const v = rec[x.cid]; if (x.s === 'pending' && v) { x.s = v.s; x.id = v.id; x.msg = v.msg; changed = true; if (v.s === 'ok') lit = true; if (v.s === 'rej') { toast('你的一条信号未通过审核：' + (v.msg || ''), 'err'); Galaxy.dropPending(x.cid); } } }
    if (changed) { saveMine(l); renderMine(); }
    if (lit) { toast('你的信号已被点亮，正在星空中闪烁 ✦', 'ok'); loadBoard(); }
  } catch (e) {}
}

/* ---------------- galaxy (three.js) ---------------- */
const Galaxy = (() => {
  const stage = $('#bd-stage'), host = $('#bd-canvas');
  let ok = false, renderer, scene, camera, world, orbGroup, lines, pulse, core, ring1, ring2, warpLines, beam;
  const orbs = new Map(); let hovered = null, pinned = null;
  let rotY = 0.4, rotX = 0.32, vY = 0.0006, vX = 0, dragging = false, lastX = 0, lastY = 0, zoom = mobile ? 44 : 27, zoomT = zoom, warp = 0;
  const ray = new THREE.Raycaster(), ptr = new THREE.Vector2(-9, -9);
  const tmp = new THREE.Vector3();

  function glowTex(inner = 'rgba(255,255,255,1)', mid = 'rgba(160,230,255,.55)') {
    const c = document.createElement('canvas'); c.width = c.height = 128; const g = c.getContext('2d');
    const gr = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    gr.addColorStop(0, inner); gr.addColorStop(0.18, mid); gr.addColorStop(0.45, 'rgba(120,160,255,.12)'); gr.addColorStop(1, 'rgba(0,0,0,0)');
    g.fillStyle = gr; g.fillRect(0, 0, 128, 128);
    const lg = g.createLinearGradient(0, 0, 128, 0); lg.addColorStop(0, 'rgba(255,255,255,0)'); lg.addColorStop(.5, 'rgba(255,255,255,.4)'); lg.addColorStop(1, 'rgba(255,255,255,0)');
    g.globalCompositeOperation = 'lighter'; g.fillStyle = lg; g.fillRect(14, 63, 100, 2); g.save(); g.translate(64, 64); g.rotate(Math.PI / 2); g.translate(-64, -64); g.fillRect(14, 63, 100, 2); g.restore();
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
  }
  function cloudTex() {
    const c = document.createElement('canvas'); c.width = c.height = 256; const g = c.getContext('2d');
    for (let i = 0; i < 26; i++) { const x = 128 + (Math.random() - .5) * 120, y = 128 + (Math.random() - .5) * 120, r = 40 + Math.random() * 70; const gr = g.createRadialGradient(x, y, 0, x, y, r); gr.addColorStop(0, 'rgba(255,255,255,.08)'); gr.addColorStop(1, 'rgba(255,255,255,0)'); g.fillStyle = gr; g.fillRect(0, 0, 256, 256); }
    return new THREE.CanvasTexture(c);
  }
  const pointsMat = (size) => new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, vertexColors: true,
    uniforms: { uTime: { value: 0 }, uSize: { value: size * Math.min(devicePixelRatio, 2) }, uWarp: { value: 0 } },
    vertexShader: `attribute float aSeed; uniform float uTime; uniform float uSize; uniform float uWarp; varying vec3 vC; varying float vA;
      void main(){ vC=color; vec4 mv=modelViewMatrix*vec4(position,1.); float tw=.55+.45*sin(uTime*(1.2+aSeed*2.)+aSeed*40.);
        vA=tw; gl_PointSize=uSize*(.6+aSeed)*(1.+uWarp*2.)*(60./-mv.z); gl_Position=projectionMatrix*mv; }`,
    fragmentShader: `varying vec3 vC; varying float vA; void main(){ vec2 d=gl_PointCoord-.5; float r=length(d); if(r>.5) discard; float a=smoothstep(.5,0.,r); a=a*a; gl_FragColor=vec4(vC*(.6+vA*.7),a*vA); }`
  });

  function init() {
    try {
      renderer = new THREE.WebGLRenderer({ antialias: !mobile, alpha: true, powerPreference: 'high-performance' });
    } catch (e) { return false; }
    renderer.setPixelRatio(Math.min(devicePixelRatio, mobile ? 1.6 : 2));
    renderer.setClearColor(0x000000, 0);
    host.appendChild(renderer.domElement);
    scene = new THREE.Scene(); scene.fog = new THREE.FogExp2(0x02040a, 0.006);
    camera = new THREE.PerspectiveCamera(60, 1, 0.1, 2000);
    world = new THREE.Group(); scene.add(world);

    // galaxy: 3-arm spiral
    const N = mobile ? 7000 : 14000, pos = new Float32Array(N * 3), col = new Float32Array(N * 3), seed = new Float32Array(N);
    const cA = new THREE.Color('#5ce1ff'), cB = new THREE.Color('#a78bfa'), cC = new THREE.Color('#ff7ad9'), cD = new THREE.Color('#5ef0c0'), cc = new THREE.Color();
    for (let i = 0; i < N; i++) {
      const r = Math.pow(Math.random(), 1.6) * 30 + 0.6, arm = (i % 3) * (Math.PI * 2 / 3), spin = r * 0.32;
      const rnd = (s) => Math.pow(Math.random(), 3) * (Math.random() < .5 ? 1 : -1) * s * (0.4 + r * 0.06);
      pos[i * 3] = Math.cos(arm + spin) * r + rnd(2.2); pos[i * 3 + 1] = rnd(1.1) * (1.4 - r / 40); pos[i * 3 + 2] = Math.sin(arm + spin) * r + rnd(2.2);
      const k = r / 30; cc.copy(cA).lerp(cB, Math.min(1, k * 1.4)); if (k > .7) cc.lerp(cC, (k - .7) * 1.6); if (Math.random() < .06) cc.copy(cD);
      col[i * 3] = cc.r; col[i * 3 + 1] = cc.g; col[i * 3 + 2] = cc.b; seed[i] = Math.random();
    }
    const gg = new THREE.BufferGeometry(); gg.setAttribute('position', new THREE.BufferAttribute(pos, 3)); gg.setAttribute('color', new THREE.BufferAttribute(col, 3)); gg.setAttribute('aSeed', new THREE.BufferAttribute(seed, 1));
    const gal = new THREE.Points(gg, pointsMat(2.6)); gal.name = 'gal'; world.add(gal);

    // far stars
    const M = mobile ? 1500 : 3000, p2 = new Float32Array(M * 3), c2 = new Float32Array(M * 3), s2 = new Float32Array(M);
    for (let i = 0; i < M; i++) { const v = new THREE.Vector3().randomDirection().multiplyScalar(220 + Math.random() * 300); p2.set([v.x, v.y, v.z], i * 3); const w = .6 + Math.random() * .4; c2.set([w * .8, w * .9, w], i * 3); s2[i] = Math.random(); }
    const sg = new THREE.BufferGeometry(); sg.setAttribute('position', new THREE.BufferAttribute(p2, 3)); sg.setAttribute('color', new THREE.BufferAttribute(c2, 3)); sg.setAttribute('aSeed', new THREE.BufferAttribute(s2, 1));
    const far = new THREE.Points(sg, pointsMat(9)); far.name = 'far'; scene.add(far);

    // nebula clouds
    const ct = cloudTex();
    ['#5ce1ff', '#a78bfa', '#ff7ad9', '#5ef0c0', '#7b6cff', '#5ce1ff', '#a78bfa', '#ff7ad9'].forEach((h, i) => {
      const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: ct, color: h, transparent: true, opacity: .2, depthWrite: false, blending: THREE.AdditiveBlending }));
      const a = i / 8 * Math.PI * 2; s.position.set(Math.cos(a) * (10 + i * 2), (Math.random() - .5) * 4, Math.sin(a) * (10 + i * 2)); s.scale.setScalar(26 + Math.random() * 20); s.userData.rs = (Math.random() - .5) * .002; world.add(s);
    });

    // core + accretion rings
    core = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex('rgba(255,255,255,1)', 'rgba(200,190,255,.7)'), color: '#d9d2ff', transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    core.scale.setScalar(9); world.add(core);
    const ringMat = (c, o) => new THREE.MeshBasicMaterial({ color: c, transparent: true, opacity: o, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending });
    ring1 = new THREE.Mesh(new THREE.RingGeometry(3.2, 3.36, 128), ringMat('#5ce1ff', .65)); ring1.rotation.x = Math.PI / 2; world.add(ring1);
    ring2 = new THREE.Mesh(new THREE.RingGeometry(4.6, 4.66, 128), ringMat('#a78bfa', .45)); ring2.rotation.x = Math.PI / 2.3; world.add(ring2);

    orbGroup = new THREE.Group(); world.add(orbGroup);
    lines = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: '#8fd8ff', transparent: true, opacity: .2, depthWrite: false, blending: THREE.AdditiveBlending }));
    world.add(lines);
    pulse = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex(), color: '#bff4ff', transparent: true, depthWrite: false, blending: THREE.AdditiveBlending })); pulse.scale.setScalar(1.6); world.add(pulse);

    // warp streaks (only visible during launch)
    const WN = 500, wp = new Float32Array(WN * 6);
    for (let i = 0; i < WN; i++) { const a = Math.random() * Math.PI * 2, r = 2 + Math.random() * 40, z = -Math.random() * 300; wp.set([Math.cos(a) * r, Math.sin(a) * r, z, Math.cos(a) * r, Math.sin(a) * r, z - 4], i * 6); }
    const wg = new THREE.BufferGeometry(); wg.setAttribute('position', new THREE.BufferAttribute(wp, 3));
    warpLines = new THREE.LineSegments(wg, new THREE.LineBasicMaterial({ color: '#bfefff', transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending }));
    camera.add(warpLines); scene.add(camera);

    beam = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex('rgba(255,255,255,1)', 'rgba(120,240,255,.9)'), color: '#ffffff', transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending }));
    beam.scale.setScalar(3); scene.add(beam);

    bind(); resize(); addEventListener('resize', resize);
    ok = true; requestAnimationFrame(loop);
    return true;
  }

  const orbTex = glowTexLazy();
  function glowTexLazy() { let t; return () => t || (t = glowTex()); }
  function orbPosition(m, i) {
    const u = hashNum(m.id || m.cid || String(i)), v = hashNum((m.id || m.cid || '') + 'v');
    const r = 6 + Math.sqrt(i + 1) * 2.6 + u * 3, arm = Math.floor(v * 3) * (Math.PI * 2 / 3), spin = r * 0.32;
    return new THREE.Vector3(Math.cos(arm + spin + u * .5) * r, (v - .5) * 3.2, Math.sin(arm + spin + u * .5) * r);
  }
  function makeOrb(m, i, pending) {
    const c = new THREE.Color().setHSL(((m.hue ?? 190) % 360) / 360, .85, .66);
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: orbTex(), color: c, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: pending ? .55 : 1 }));
    const fresh = m.t && (Date.now() / 1000 - m.t) < 86400;
    s.userData = { m, base: (fresh ? 2.9 : 2.2) + Math.min(1.2, (m.text || '').length / 120), ph: Math.random() * 6, pending, fresh };
    s.position.copy(orbPosition(m, i)); s.scale.setScalar(.01);
    orbGroup.add(s); return s;
  }
  function sync() {
    if (!ok) return;
    const keep = new Set();
    MESSAGES.forEach((m, i) => { keep.add(m.id); if (!orbs.has(m.id)) orbs.set(m.id, makeOrb(m, i, false)); });
    mine().filter(x => x.s === 'pending').forEach((x, i) => { const k = 'p:' + x.cid; keep.add(k); if (!orbs.has(k)) orbs.set(k, makeOrb({ ...x, id: null, hue: 160, nick: x.nick, pendingLabel: true }, MESSAGES.length + i, true)); });
    for (const [k, s] of orbs) if (!keep.has(k)) { orbGroup.remove(s); orbs.delete(k); }
    // constellation: link the 28 most recent in time order
    const recent = MESSAGES.slice(0, 16).map(m => orbs.get(m.id)).filter(Boolean);
    const arr = [];
    for (let i = 0; i < recent.length - 1; i++) { const a = recent[i].position, b = recent[i + 1].position; arr.push(a.x, a.y, a.z, b.x, b.y, b.z); }
    lines.geometry.dispose(); lines.geometry = new THREE.BufferGeometry(); lines.geometry.setAttribute('position', new THREE.Float32BufferAttribute(arr, 3));
    lines.userData.path = recent.map(s => s.position);
  }
  function dropPending(cid) { const s = orbs.get('p:' + cid); if (s) { s.userData.dying = 1; } }

  function bind() {
    const cv = renderer.domElement;
    cv.addEventListener('pointerdown', (e) => { dragging = true; lastX = e.clientX; lastY = e.clientY; cv.setPointerCapture(e.pointerId); stage.classList.add('grab'); downAt = [e.clientX, e.clientY]; });
    cv.addEventListener('pointermove', (e) => {
      const r = cv.getBoundingClientRect(); ptr.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1); lastPtr = [e.clientX - r.left, e.clientY - r.top];
      if (dragging) { const dx = e.clientX - lastX, dy = e.clientY - lastY; vY = dx * 0.00042; vX = dy * 0.00032; rotY += dx * 0.005; rotX = Math.max(-0.9, Math.min(1.25, rotX + dy * 0.004)); lastX = e.clientX; lastY = e.clientY; }
    });
    const up = (e) => { dragging = false; stage.classList.remove('grab'); if (downAt && Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) < 6) clickAt(); downAt = null; };
    cv.addEventListener('pointerup', up); cv.addEventListener('pointercancel', () => { dragging = false; });
    cv.addEventListener('pointerleave', () => { ptr.set(-9, -9); });
    cv.addEventListener('wheel', (e) => { e.preventDefault(); zoomT = Math.max(14, Math.min(80, zoomT + e.deltaY * 0.03)); }, { passive: false });
    let pinch = 0; cv.addEventListener('touchmove', (e) => { if (e.touches.length === 2) { const d = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY); if (pinch) zoomT = Math.max(14, Math.min(80, zoomT - (d - pinch) * 0.08)); pinch = d; } }, { passive: true });
    cv.addEventListener('touchend', () => pinch = 0);
  }
  let downAt = null, lastPtr = [0, 0];
  function clickAt() {
    if (hovered) { pinned = hovered; Holo.show(hovered.userData.m, lastPtr, true); burst(hovered); }
    else { pinned = null; Holo.hide(); }
  }
  function focus(id) { const s = orbs.get(id); if (!s) return; pinned = s; hovered = s; const p = s.position; rotY = -Math.atan2(p.z, p.x) + Math.PI / 2; rotX = 0.2; zoomT = 22; setTimeout(() => { const sp = screenOf(s); Holo.show(s.userData.m, sp, true); burst(s); }, 650); }
  function screenOf(s) { s.getWorldPosition(tmp); tmp.project(camera); const r = renderer.domElement.getBoundingClientRect(); return [(tmp.x + 1) / 2 * r.width, (1 - tmp.y) / 2 * r.height]; }
  const bursts = [];
  function burst(s) { const b = new THREE.Sprite(new THREE.SpriteMaterial({ map: ringTex(), color: s.material.color, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending })); b.position.copy(s.position); b.scale.setScalar(1); orbGroup.add(b); bursts.push({ b, t: 0 }); }
  let _rt; function ringTex() { if (_rt) return _rt; const c = document.createElement('canvas'); c.width = c.height = 128; const g = c.getContext('2d'); g.strokeStyle = 'rgba(255,255,255,.9)'; g.lineWidth = 3; g.shadowColor = '#9ff'; g.shadowBlur = 12; g.beginPath(); g.arc(64, 64, 52, 0, Math.PI * 2); g.stroke(); return _rt = new THREE.CanvasTexture(c); }

  function resize() { const w = stage.clientWidth, h = stage.clientHeight; renderer.setSize(w, h, false); renderer.domElement.style.width = w + 'px'; renderer.domElement.style.height = h + 'px'; camera.aspect = w / h; camera.updateProjectionMatrix(); }
  let last = performance.now(), visible = true;
  new IntersectionObserver(([e]) => { visible = e.isIntersecting; }).observe(stage);
  function loop(t) {
    requestAnimationFrame(loop);
    const dt = Math.min(50, t - last); last = t; if (!visible || document.hidden) return;
    const time = t / 1000;
    if (!dragging) { rotY += vY * dt * 0.06 + 0.00011 * dt * (1 + warp * 30); vY *= 0.96; vX *= 0.9; }
    world.rotation.y += (rotY - world.rotation.y) * 0.08; world.rotation.x += (rotX - world.rotation.x) * 0.08;
    zoom += (zoomT - zoom) * 0.06;
    camera.position.set(0, zoom * 0.12, zoom); camera.lookAt(0, 0, 0);
    camera.fov += ((60 + warp * 45) - camera.fov) * 0.12; camera.updateProjectionMatrix();
    scene.traverse(o => { if (o.material && o.material.uniforms && o.material.uniforms.uTime) { o.material.uniforms.uTime.value = time; o.material.uniforms.uWarp.value = warp; } });
    world.children.forEach(o => { if (o.userData && o.userData.rs) o.material.rotation += o.userData.rs * dt; });
    core.scale.setScalar(8.5 + Math.sin(time * 1.7) * .6 + warp * 6);
    ring1.rotation.z += 0.0009 * dt; ring2.rotation.z -= 0.0006 * dt;
    // warp streaks
    warpLines.material.opacity = Math.min(.9, warp * 1.2);
    if (warp > 0.01) { const a = warpLines.geometry.attributes.position.array; for (let i = 0; i < a.length; i += 6) { a[i + 2] += dt * 0.6 * warp; a[i + 5] = a[i + 2] - 4 - warp * 30; if (a[i + 2] > 0) { a[i + 2] = -300; a[i + 5] = -304; } } warpLines.geometry.attributes.position.needsUpdate = true; }
    // orbs
    ray.setFromCamera(ptr, camera);
    let best = null, bestD = 1e9;
    orbGroup.children.forEach(s => {
      const u = s.userData; if (!u || !u.m) return;
      if (u.dying) { u.dying -= dt * 0.0012; s.material.opacity = Math.max(0, u.dying); s.material.color.setHSL(0, 1, .6); if (u.dying <= 0) orbGroup.remove(s); return; }
      const target = u.base * (1 + 0.14 * Math.sin(time * (u.pending ? 5 : 1.6) + u.ph)) * (s === hovered || s === pinned ? 1.9 : 1);
      s.scale.setScalar(s.scale.x + (target - s.scale.x) * 0.12);
      const d = ray.ray.distanceSqToPoint(s.getWorldPosition(tmp)); const near = camera.position.distanceTo(tmp);
      if (d < Math.pow(u.base * 0.42, 2) && near < bestD) { best = s; bestD = near; }
    });
    bursts.forEach((x, i) => { x.t += dt / 900; x.b.scale.setScalar(1 + x.t * 9); x.b.material.opacity = 1 - x.t; if (x.t >= 1) { orbGroup.remove(x.b); bursts.splice(i, 1); } });
    if (best !== hovered && !dragging) { hovered = best; renderer.domElement.style.cursor = best ? 'pointer' : 'grab'; if (best && !pinned) Holo.show(best.userData.m, lastPtr, false); else if (!best && !pinned) Holo.hide(); }
    if (pinned && pinned.parent) { Holo.place(screenOf(pinned)); }
    updateLabels();
    // pulse travelling along constellation
    const path = lines.userData.path || [];
    if (path.length > 1) { const k = (time * 0.35) % (path.length - 1), i = Math.floor(k), f = k - i; pulse.position.lerpVectors(path[i], path[i + 1], f); pulse.material.opacity = .9; lines.material.opacity = .14 + .08 * Math.sin(time * 2); } else pulse.material.opacity = 0;
    // beam
    if (beam.userData.run) { const b = beam.userData; b.t += dt / 1300; const k = Math.min(1, b.t), e = 1 - Math.pow(1 - k, 3); beam.position.lerpVectors(b.from, b.to.clone().applyMatrix4(world.matrixWorld), e); beam.scale.setScalar(4 * (1 - k) + 1.5); beam.material.opacity = k < 1 ? 1 : 0; if (k >= 1) { b.run = false; b.done && b.done(); } }
    warp *= 0.965;
    renderer.render(scene, camera);
  }
  const labelBox = $('#bd-labels'); const labels = [];
  function updateLabels() {
    const top = MESSAGES.slice(0, mobile ? 3 : 6).map(m => orbs.get(m.id)).filter(Boolean);
    while (labels.length < top.length) { const d = el('div', 'bd-label'); labelBox.append(d); labels.push(d); }
    const placed = [];
    labels.forEach((d, i) => {
      const s = top[i]; if (!s) { d.style.opacity = 0; return; }
      const m = s.userData.m; if (d._id !== m.id) { d._id = m.id; d.textContent = '✦ ' + (m.nick || '匿名旅人'); d.style.setProperty('--h', m.hue ?? 190); }
      s.getWorldPosition(tmp); const dist = camera.position.distanceTo(tmp); tmp.project(camera);
      const r = renderer.domElement.getBoundingClientRect(); const x = (tmp.x + 1) / 2 * r.width, y = (1 - tmp.y) / 2 * r.height;
      let vis = tmp.z < 1 && s !== hovered && s !== pinned && x > 20 && x < r.width - 140;
      if (vis && placed.some(([px, py]) => Math.abs(px - x) < 150 && Math.abs(py - y) < 26)) vis = false;
      if (vis) placed.push([x, y]);
      d.style.transform = `translate(${x + 14}px, ${y - 10}px)`; d.style.opacity = vis ? Math.max(0, Math.min(.9, 1.6 - dist / 40)) : 0;
    });
  }
  function launch(onArrive) {
    if (!ok) { onArrive && onArrive(); return; }
    warp = 1;
    const r = renderer.domElement.getBoundingClientRect(), comp = $('#bd-portal').getBoundingClientRect();
    const sx = ((comp.left + comp.width / 2 - r.left) / r.width) * 2 - 1, sy = -((comp.top + 20 - r.top) / r.height) * 2 + 1;
    const from = new THREE.Vector3(sx, Math.max(-0.95, sy), 0.5).unproject(camera);
    const to = orbPosition({ id: 'new' + Date.now() }, MESSAGES.length + 1);
    beam.userData = { run: true, t: 0, from, to, done: onArrive };
  }
  return { init, sync, launch, focus, dropPending, get ok() { return ok; } };
})();

/* ---------------- holographic card ---------------- */
const Holo = (() => {
  const h = $('#bd-holo'); let cur = null, typer = null;
  function show(m, at, pin) {
    if (cur !== m) {
      cur = m; h.style.setProperty('--h', m.hue ?? 190);
      $('#bd-holo-id').textContent = m.id ? 'SIGNAL ' + m.id : 'SIGNAL · 审核中';
      $('#bd-holo-time').textContent = m.t ? fmtTime(m.t) : '跃迁中'; $('#bd-holo-ago').textContent = m.t ? ago(m.t) : '';
      $('#bd-holo-nick').textContent = m.nick || '匿名旅人';
      const body = $('#bd-holo-text'); body.textContent = ''; clearInterval(typer);
      const txt = m.text || ''; let i = 0; const speed = reduced ? txt.length : Math.max(1, Math.ceil(txt.length / 40));
      typer = setInterval(() => { i += speed; body.textContent = txt.slice(0, i); if (i >= txt.length) clearInterval(typer); }, 22);
      h.classList.remove('glitch'); void h.offsetWidth; h.classList.add('glitch');
    }
    h.classList.add('on'); h.classList.toggle('pinned', !!pin); place(at);
  }
  function place(at) {
    const st = $('#bd-stage').getBoundingClientRect(), w = h.offsetWidth, hh = h.offsetHeight;
    if (mobile) { const ph = $('#bd-portal').offsetHeight; h.style.left = '50%'; h.style.top = Math.max(70, st.height - ph - hh - 70) + 'px'; h.style.transform = 'translateX(-50%)'; return; }
    let x = at[0] + 26, y = at[1] - hh / 2; if (x + w > st.width - 16) x = at[0] - w - 26; y = Math.max(80, Math.min(st.height - hh - 150, y));
    h.style.transform = 'none'; h.style.left = x + 'px'; h.style.top = y + 'px';
  }
  function hide() { h.classList.remove('on', 'pinned'); cur = null; }
  $('#bd-holo-x').addEventListener('click', (e) => { e.stopPropagation(); hide(); });
  return { show, hide, place };
})();

/* ---------------- composer ---------------- */
function initComposer() {
  const ta = $('#bd-text'), nick = $('#bd-nick'), cnt = $('#bd-count'), btn = $('#bd-send'), portal = $('#bd-portal');
  const saved = localStorage.getItem(LS_NICK); nick.placeholder = saved || codename(); if (saved) nick.value = '';
  $('#bd-dice').addEventListener('click', () => { nick.value = codename(); nick.dispatchEvent(new Event('input')); });
  ta.addEventListener('input', () => { const n = ta.value.length; cnt.textContent = `${n} / ${CFG.max_len}`; cnt.classList.toggle('over', n > CFG.max_len); portal.style.setProperty('--fill', Math.min(1, n / CFG.max_len)); });
  ta.addEventListener('focus', () => portal.classList.add('focus')); ta.addEventListener('blur', () => portal.classList.remove('focus'));
  ta.addEventListener('keydown', (e) => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') send(); });
  // typewriter placeholder
  const ideas = ['写下你想对宇宙说的话……', '推荐一个你最近在用的免费大模型……', '给站长留句话，或者许个愿……', '今天你用 AI 做了什么有趣的事？', '你希望这里再收录哪些免费资源？'];
  let ii = 0, ci = 0, del = false;
  (function tick() { if (document.activeElement !== ta && !ta.value) { const s = ideas[ii]; ci += del ? -1 : 1; ta.placeholder = s.slice(0, ci) + (ci % 2 ? '▍' : ''); if (ci >= s.length + 14) del = true; if (del && ci <= 0) { del = false; ii = (ii + 1) % ideas.length; } } setTimeout(tick, del ? 28 : 80); })();
  const setPH = () => document.getElementById('bd-stage').style.setProperty('--portal-h', portal.offsetHeight + 'px'); setPH(); addEventListener('resize', setPH);
  btn.addEventListener('click', send);
  let busy = false;
  async function send() {
    if (busy) return;
    const text = ta.value.trim(); const nk = nick.value.trim() || nick.placeholder;
    if ($('#bd-hp').value) return;  // honeypot: silently ignore bots
    const err = precheck(text, nick.value.trim() ? nk : '');
    if (err) { toast(err, 'err'); portal.classList.remove('shake'); void portal.offsetWidth; portal.classList.add('shake'); return; }
    const last = +localStorage.getItem(LS_LAST) || 0; if (Date.now() - last < 45000) { toast('发射冷却中，请 ' + Math.ceil((45000 - (Date.now() - last)) / 1000) + ' 秒后再试。', 'err'); return; }
    if (Date.now() - T0 < 3000) { toast('先感受一下星空，3 秒后再发射吧。', 'err'); return; }
    busy = true; portal.classList.add('charging'); btn.disabled = true; $('#bd-send-t').textContent = '校准坐标';
    try {
      const cid = hex(12), t1 = Date.now();
      const payload = { v: 1, cid, nick: nk, text, t0: T0, t1, fp: await fingerprint(), hp: '' };
      const pre = `${cid}|${t1}|${text}|${nk}|`;
      payload.nonce = await proofOfWork(pre, (n) => { portal.style.setProperty('--pow', Math.min(1, n / 90000)); });
      $('#bd-send-t').textContent = '加密跃迁';
      const env = await seal(payload);
      const r = await fetch(`${CFG.relay}/${CFG.topic}`, { method: 'POST', body: env });
      if (!r.ok) throw new Error('relay ' + r.status);
      localStorage.setItem(LS_LAST, String(Date.now()));
      if (nick.value.trim()) localStorage.setItem(LS_NICK, nk);
      const l = mine(); l.push({ cid, text, nick: nk, t: Math.floor(t1 / 1000), s: 'pending' }); saveMine(l);
      portal.classList.add('launch');
      Galaxy.launch(() => { Galaxy.sync(); });
      ta.value = ''; ta.dispatchEvent(new Event('input'));
      renderMine();
      toast('信号已发射 ✦ 正在穿越审核星门，通过后约 10–30 分钟出现在星空。', 'ok');
    } catch (e) {
      toast(String(e.message || e).includes('429') ? '发射太频繁啦，请稍后再试。' : '信号发射失败，可能是网络不稳定，请稍后再试。', 'err');
    } finally {
      busy = false; btn.disabled = false; $('#bd-send-t').textContent = '发射信号'; portal.classList.remove('charging'); portal.style.setProperty('--pow', 0);
      setTimeout(() => portal.classList.remove('launch'), 1400);
    }
  }
}

/* ---------------- scramble title ---------------- */
function scramble(node) {
  const final = node.textContent, glyph = '█▓▒░<>/\\|#$%&*+=?01アイウエオ星云光';
  if (reduced) return; let f = 0;
  const iv = setInterval(() => { node.textContent = final.split('').map((c, i) => (i < f / 2 ? c : glyph[Math.floor(Math.random() * glyph.length)])).join(''); if (++f > final.length * 2) { clearInterval(iv); node.textContent = final; } }, 40);
}

/* ---------------- boot ---------------- */
function boot() {
  initComposer(); renderMine();
  document.querySelectorAll('[data-scramble]').forEach(scramble);
  $('#bd-q').addEventListener('input', renderList);
  const can3d = !reduced && (() => { try { const c = document.createElement('canvas'); return !!(c.getContext('webgl2') || c.getContext('webgl')); } catch { return false; } })();
  if (!can3d || !Galaxy.init()) document.body.classList.add('bd-flat');
  $('#bd-view').addEventListener('click', () => { document.getElementById('bd-flow').scrollIntoView({ behavior: 'smooth' }); });
  loadBoard();
  window.__board = { focus: (id) => Galaxy.focus(id || (MESSAGES[0] && MESSAGES[0].id)) };
  setInterval(pollReceipts, 45000); setTimeout(pollReceipts, 4000);
  setInterval(loadBoard, 5 * 60000);
}
boot();
