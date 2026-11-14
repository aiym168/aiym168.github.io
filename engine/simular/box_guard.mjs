// Box guard: keep Engine B's Simular cloud box alive (runs inside the GitHub watchdog).
// env: SIMULAR_BOX_KEY (secret, never printed), BOX_ID, FORCE_WAKE=1, ENGINE_B_AGE_MIN, SITE_DOWN (text: the box's own site is unreachable)
// Writes JSON result to stdout (last line) and to $OUT (default data/box_state.json).
import grpc from '@grpc/grpc-js'
import loader from '@grpc/proto-loader'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const BOX_ID = process.env.BOX_ID || 'cb-6ad4209d8372'
// Wake window lives in engine/wake.json. A 3600s hourly window ends on the same
// minute as the next wake, and hibernate wins, so the server sleeps through :25.
const SPEC = JSON.parse(fs.readFileSync(path.join(here, '..', 'wake.json'), 'utf8'))
const WANT = { cron: SPEC.cron, tz: SPEC.tz, awake_for_s: Number(SPEC.awake_for_s) }
const STALE_B_MIN = Number(process.env.STALE_B_MIN || 120)
const key = (process.env.SIMULAR_BOX_KEY || '').trim()
const fmt = ms => ms ? new Date(Number(ms)).toLocaleString('sv-SE', { timeZone: 'Asia/Shanghai' }).slice(0, 16) + ' Asia/Shanghai' : null
const ZH = { BOX_STATE_RUNNING: '运行中', BOX_STATE_STARTING: '启动中', BOX_STATE_HIBERNATING: '正在休眠', BOX_STATE_HIBERNATED: '休眠', BOX_STATE_FAILED: '故障', BOX_STATE_UNSPECIFIED: '未知' }

const def = loader.loadSync(path.join(here, 'boxes.proto'), { keepCase: true, longs: String, enums: String, defaults: true })
const pkg = grpc.loadPackageDefinition(def).cocoonbox.control.v1
const c = new pkg.Boxes('mcp.box.simular.ai:443', grpc.credentials.createSsl())
const md = new grpc.Metadata(); md.set('authorization', 'Bearer ' + key)
const call = (m, req) => new Promise((res, rej) => c[m](req, md, { deadline: Date.now() + 60000 }, (e, r) => e ? rej(e) : res(r)))
const sleep = ms => new Promise(r => setTimeout(r, ms))

const out = { box_id: BOX_ID.slice(0, 5) + '…', checked_at_ms: Date.now(), checked_at_label: fmt(Date.now()), actions: [], ok: true }
try {
  if (!key) throw new Error('no SIMULAR_BOX_KEY')
  let box = await call('Get', { box_id: BOX_ID })
  out.state_before = box.state
  out.failure_reason = box.failure_reason || ''
  const bAge = process.env.ENGINE_B_AGE_MIN ? Number(process.env.ENGINE_B_AGE_MIN) : null
  out.engine_b_age_min = bAge
  const reasons = []
  if (process.env.FORCE_WAKE === '1') reasons.push('手动强制唤醒')
  if (box.state !== 'BOX_STATE_RUNNING' && box.state !== 'BOX_STATE_STARTING') reasons.push(`服务器状态为「${ZH[box.state] || box.state}」`)
  if (bAge !== null && bAge > STALE_B_MIN) reasons.push(`引擎 B 已 ${bAge} 分钟无心跳（阈值 ${STALE_B_MIN}）`)
  if (process.env.SITE_DOWN) reasons.push(`信号站连不上（${process.env.SITE_DOWN}）`)
  out.wake_reasons = reasons
  if (reasons.length) {
    const r = await call('Ensure', { box_id: BOX_ID })
    out.actions.push(`Ensure(wake) op=${r.operation?.id ? 'started' : 'already-running'}`)
    let tries = 1
    for (let i = 0; i < 60; i++) {
      box = await call('Get', { box_id: BOX_ID })
      if (box.state === 'BOX_STATE_RUNNING') break
      if (box.state === 'BOX_STATE_FAILED' && tries < 6) {
        // e.g. "node at capacity, try again shortly" — retry the wake with backoff
        out.actions.push(`retry Ensure (${box.failure_reason || 'failed'})`)
        await sleep(10000 * tries)
        await call('Ensure', { box_id: BOX_ID })
        tries++
        continue
      }
      await sleep(5000)
    }
    out.failure_reason_after = box.state === 'BOX_STATE_RUNNING' ? '' : (box.failure_reason || '')
  }
  out.state_after = box.state
  out.state_after_zh = ZH[box.state] || box.state
  out.image = box.image
  out.last_saved_label = fmt(box.last_saved_at_ms)
  // re-assert the hourly wake schedule
  const ls = await call('ListWakeSchedules', {})
  let s = (ls.schedules || []).find(x => x.box_id === BOX_ID)
  if (!s || s.cron !== WANT.cron || s.tz !== WANT.tz || Number(s.awake_for_s) !== WANT.awake_for_s) {
    s = await call('SetWakeSchedule', { box_id: BOX_ID, ...WANT })
    out.actions.push(`SetWakeSchedule(${WANT.cron}, ${WANT.tz}, ${WANT.awake_for_s}s)`)
  }
  out.wake_schedule = { cron: s.cron, tz: s.tz, awake_for_s: Number(s.awake_for_s), next_label: fmt(s.next_at_ms), last_wake_label: fmt(s.last_wake_at_ms) }
  out.ok = box.state === 'BOX_STATE_RUNNING'
} catch (e) {
  out.ok = false
  out.error = `${e.code ?? ''} ${(e.details || e.message || '').toString().slice(0, 200)}`.replace(/cb_[A-Za-z0-9_-]+/g, 'cb_***')
}
const file = process.env.OUT || path.join(here, '..', '..', 'data', 'box_state.json')
fs.writeFileSync(file, JSON.stringify(out, null, 2) + '\n')
console.log(JSON.stringify(out))
process.exit(0)
