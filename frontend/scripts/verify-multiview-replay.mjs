// 多视角重建回放验收：打开双江口三维页，导入 summary.json + 两个 *-voxels.ply，
// 校验绑定、切换 1800/3600 时间点（候选体素 33,599 → 43,005 → 33,599）、
// 错误资产绑定被拒绝、退出回放后图层清空。截图与结果写入 evidence/multiview-replay/。
import { chromium } from 'playwright'
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs'

const FRONTEND = process.env.FIREX_FRONTEND || 'http://127.0.0.1:4173'
const REPO = process.env.FIREX_REPO || '/home/dailen/projects/firex-platform'
const DATA_DIR = process.env.FIREX_MV_DIR || `${REPO}/runtime-data/sjk-local-ab.gIen7N/terrain-clip`
const OUT = process.env.EVIDENCE_DIR || 'evidence/multiview-replay'
mkdirSync(OUT, { recursive: true })

const summary = `${DATA_DIR}/summary.json`
const ply1 = `${DATA_DIR}/group_01-voxels.ply`
const ply2 = `${DATA_DIR}/group_02-voxels.ply`

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
const state = { consoleErrors: [], pageErrors: [], failedRequests: [] }
page.on('console', (m) => { if (m.type() === 'error') state.consoleErrors.push(m.text()) })
page.on('pageerror', (e) => state.pageErrors.push(String(e)))
page.on('requestfailed', (r) => { const e = r.failure()?.errorText ?? ''; if (e !== 'net::ERR_ABORTED') state.failedRequests.push(`${r.method()} ${r.url()} ${e}`) })

const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`) }
let fatalCount = 0
let failures = 0
const startTime = Date.now()
const infoText = () => page.locator('.replay-info').innerText().catch(() => '')

try {
  await page.goto(`${FRONTEND}/#/scene/sjk_hydropower_sim_v0_1`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.viewer-toolbar', { timeout: 30000 })
  await page.waitForSelector('.loaded-status', { timeout: 30000 })
  await page.waitForTimeout(1000)
  check('scene-loads', (await page.locator('.loaded-status').innerText().catch(() => '')).includes('双江口'))
  check('replay-panel-present', (await page.locator('.replay-panel').count()) === 1)

  // 导入成功
  await page.locator('.replay-import input').setInputFiles([summary, ply1, ply2])
  await page.waitForTimeout(600)
  check('replay-active-badge', await page.getByText('离线重建回放 · 候选体素').first().isVisible().catch(() => false))
  const i1800 = await infoText()
  check('time-1800-voxels-33599', i1800.includes('33,599'), i1800.replace(/\s+/g, ' ').trim())
  check('time-1800-two-cameras', i1800.includes('重建机位 2'), i1800.replace(/\s+/g, ' ').trim())
  await page.screenshot({ path: `${OUT}/1800s.png` })

  // 3600 s
  await page.getByRole('button', { name: '3600 s' }).click()
  await page.waitForTimeout(500)
  const i3600 = await infoText()
  check('time-3600-voxels-43005', i3600.includes('43,005'), i3600.replace(/\s+/g, ' ').trim())
  await page.screenshot({ path: `${OUT}/3600s.png` })

  // 切回 1800 s（同视角）
  await page.getByRole('button', { name: '1800 s' }).click()
  await page.waitForTimeout(500)
  const i1800back = await infoText()
  check('time-back-1800-voxels-33599', i1800back.includes('33,599'), i1800back.replace(/\s+/g, ' ').trim())

  // 错误资产绑定被拒绝
  const raw = JSON.parse(readFileSync(summary, 'utf8'))
  raw.scene_id = 'wrong_scene_id'
  const badSummary = '/tmp/mv-bad-summary.json'
  writeFileSync(badSummary, JSON.stringify(raw))
  await page.locator('.replay-import input').setInputFiles([badSummary, ply1, ply2])
  await page.waitForTimeout(500)
  const err = await page.locator('.replay-error').innerText().catch(() => '')
  check('bad-binding-rejected', err.includes('场景 ID 不匹配'), err.trim())
  const afterBad = await infoText()
  check('previous-result-preserved', afterBad.includes('33,599'), afterBad.replace(/\s+/g, ' ').trim())

  // 退出回放
  await page.getByRole('button', { name: '退出回放' }).click()
  await page.waitForTimeout(500)
  check('exit-clears-badge', !(await page.getByText('离线重建回放 · 候选体素').first().isVisible().catch(() => false)))
  check('exit-restores-import', (await page.locator('.replay-import input').count()) === 1)
} catch (e) {
  fatalCount++
  console.error('FATAL:', e instanceof Error ? e.message : String(e))
  await page.screenshot({ path: `${OUT}/error.png` }).catch(() => {})
} finally {
  const elapsedMs = Date.now() - startTime
  const appConsoleErrors = state.consoleErrors.filter((e) => !e.startsWith('Failed to load resource:'))
  failures = results.filter((r) => !r.ok).length + appConsoleErrors.length + state.pageErrors.length + state.failedRequests.length + fatalCount
  const exitCode = failures === 0 ? 0 : 1
  console.log('\n--- app console errors ---'); console.log(appConsoleErrors.length ? appConsoleErrors.join('\n') : '(none)')
  console.log('--- page errors ---'); console.log(state.pageErrors.length ? state.pageErrors.join('\n') : '(none)')
  console.log('--- unexpected failed requests ---'); console.log(state.failedRequests.length ? state.failedRequests.join('\n') : '(none)')
  writeFileSync(`${OUT}/result.json`, JSON.stringify({
    executed_at: new Date().toISOString(), elapsed_ms: elapsedMs, checks: results,
    checks_passed: results.filter((r) => r.ok).length, checks_total: results.length,
    app_console_errors: appConsoleErrors, page_errors: state.pageErrors, failed_requests: state.failedRequests,
    fatal_count: fatalCount, exit_status: exitCode,
  }, null, 2))
  await browser.close()
}

console.log(`\nRESULT: ${results.filter((r) => r.ok).length}/${results.length} checks passed, ${failures} failures`)
process.exit(failures === 0 ? 0 : 1)
