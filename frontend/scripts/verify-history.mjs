// 端到端验收：历史重建回看 + 一键回到最新。
// 先发布 1800s 并固定，再发布 3600s -> 有新结果提示且画面保持 1800s；
// 点「回到最新」显示 3600s，再从历史选回 1800s。GLB 只加载一次。
import { chromium } from 'playwright'
import { execSync } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'

const FRONTEND = 'http://127.0.0.1:4174'
const REPO = '/home/dailen/projects/firex-platform'
const DATA_DIR = `${REPO}/runtime-data/e2e-history`
const RESULTS_DIR = `${REPO}/runtime-data/sjk-local-ab.gIen7N/terrain-clip`
const OUT = process.env.EVIDENCE_DIR || 'evidence/history'
mkdirSync(OUT, { recursive: true })

const RUN_ID = process.env.RUN_ID || ''
if (!RUN_ID) throw new Error('RUN_ID 未设置')

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })

let glbRequests = 0
let plyRequests = 0
page.on('request', (r) => {
  const url = r.url()
  if (url.endsWith('.glb')) glbRequests++
  else if (url.endsWith('/ply')) plyRequests++
})

const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`) }
let failures = 0

const followInfo = () => page.locator('.follow-info').innerText().catch(() => '')
const publish = (group) => execSync(
  `.venv/bin/python scripts/publish_reconstruction.py --run-id ${RUN_ID} --results-dir ${RESULTS_DIR} --group-id ${group} --data-dir ${DATA_DIR}`,
  { cwd: `${REPO}/backend`, encoding: 'utf8' },
)

try {
  await page.goto(`${FRONTEND}/#/scene/sjk_hydropower_sim_v0_1?run_id=${RUN_ID}`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.viewer-toolbar', { timeout: 30000 })
  await page.waitForSelector('.loaded-status', { timeout: 30000 })
  await page.waitForTimeout(3000)
  const glbAfterLoad = glbRequests
  check('scene-loaded-glb-once', glbAfterLoad === 1, `glb=${glbAfterLoad}`)

  // 开启跟随 -> 显示最新 1800s / 33,599
  await page.getByRole('button', { name: '开始跟随' }).click()
  await page.waitForTimeout(3000)
  const i1800 = await followInfo()
  check('follow-shows-1800', i1800.includes('33,599'), i1800.replace(/\s+/g, ' ').trim())
  await page.waitForSelector('.history-item', { timeout: 5000 })

  // 固定 1800s
  await page.locator('.history-item', { hasText: '1800' }).click()
  await page.waitForTimeout(1500)
  const pinned1 = await page.locator('.history-pinned').innerText().catch(() => '')
  check('pin-1800-active', pinned1.includes('revision 1'), pinned1.replace(/\s+/g, ' ').trim())
  await page.screenshot({ path: `${OUT}/pinned-1800.png` })

  // 发布 3600s -> 有新结果提示，画面保持 1800s
  publish('group_02')
  let newer = ''
  const newerDeadline = Date.now() + 30000
  while (Date.now() < newerDeadline) {
    newer = await page.locator('.history-newer').innerText().catch(() => '')
    if (newer) break
    await page.waitForTimeout(500)
  }
  check('newer-hint-shown', /有新结果.*revision 2/.test(newer), newer)
  const iStill1800 = await followInfo()
  check('still-on-1800-while-pinned', iStill1800.includes('33,599') && !iStill1800.includes('43,005'), iStill1800.replace(/\s+/g, ' ').trim())
  await page.screenshot({ path: `${OUT}/newer-kept-1800.png` })

  // 回到最新 -> 显示 3600s / 43,005
  await page.getByRole('button', { name: '回到最新' }).click()
  await page.waitForTimeout(2500)
  const i3600 = await followInfo()
  check('back-to-latest-43005', i3600.includes('43,005'), i3600.replace(/\s+/g, ' ').trim())
  await page.screenshot({ path: `${OUT}/back-to-latest.png` })

  // 从历史选回 1800s
  await page.locator('.history-item', { hasText: '1800' }).click()
  await page.waitForTimeout(1500)
  const iBack1800 = await followInfo()
  check('select-1800-again', iBack1800.includes('33,599'), iBack1800.replace(/\s+/g, ' ').trim())
  await page.screenshot({ path: `${OUT}/select-1800-again.png` })

  check('glb-not-reloaded', glbRequests === glbAfterLoad, `glb=${glbRequests}`)
} catch (e) {
  failures++
  console.error('FATAL:', e instanceof Error ? e.message : String(e))
  await page.screenshot({ path: `${OUT}/error.png` }).catch(() => {})
} finally {
  failures += results.filter((r) => !r.ok).length
  writeFileSync(`${OUT}/result.json`, JSON.stringify({ run_id: RUN_ID, checks: results, glb_requests: glbRequests, ply_requests: plyRequests, exit_status: failures === 0 ? 0 : 1 }, null, 2))
  await browser.close()
}
console.log(`\nRESULT: ${results.length - results.filter((r) => !r.ok).length}/${results.length} checks passed`)
process.exit(failures === 0 ? 0 : 1)
