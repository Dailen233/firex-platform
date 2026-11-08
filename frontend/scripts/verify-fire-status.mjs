// A1 全国地图火情反馈验收：直接打开首页（不输入 run_id、不进三维）。
// 阶段 A：首页无有效火情（frame 1 已过期 -> 历史/过期，不计入当前告警）。
// 阶段 B：页面保持打开，送入新的 fixture 帧 -> 一个轮询周期内自动点亮（不刷新/不切页）。
// 阶段 C：点开详情入口，能看到厂站详情。阶段 D：直接重开首页仍显示。
// 截图与结果写入 evidence/fire-status/。
import { chromium } from 'playwright'
import { execFileSync } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'

const FRONTEND = process.env.FIREX_FRONTEND || 'http://127.0.0.1:4173'
const BACKEND = process.env.FIREX_BACKEND || 'http://127.0.0.1:8002'
const REPO = process.env.FIREX_REPO || '/home/dailen/projects/firex-platform'
const RUN_ID = process.env.FIREX_RUN_ID ?? ''
const FRAME = process.env.FIREX_FRAME ?? '2'
const OUT = process.env.EVIDENCE_DIR || 'evidence/fire-status'
mkdirSync(OUT, { recursive: true })
if (!RUN_ID) {
  console.error('需要 FIREX_RUN_ID（被后端监测的 run）')
  process.exit(2)
}

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
const state = { consoleErrors: [], pageErrors: [], failedRequests: [], fireFetches: [] }
page.on('console', (m) => { if (m.type() === 'error') state.consoleErrors.push(m.text()) })
page.on('pageerror', (e) => state.pageErrors.push(String(e)))
page.on('requestfailed', (r) => { const e = r.failure()?.errorText ?? ''; if (e !== 'net::ERR_ABORTED') state.failedRequests.push(`${r.method()} ${r.url()} ${e}`) })
page.on('response', (r) => { if (r.url().includes('/api/v1/atlas/fire-status')) state.fireFetches.push(r.status()) })

const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`) }
let failures = 0
const startTime = Date.now()

try {
  // ---- 阶段 A：首页无有效火情（旧快照已过期）----
  await page.goto(`${FRONTEND}/#/atlas`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2500)
  check('homepage-loads', await page.getByText('火情反馈').first().isVisible().catch(() => false))
  check('no-fire-before-upload', (await page.locator('.fire-card').count()) === 0)
  check('stale-shown-as-history', await page.getByText('历史 / 过期记录').first().isVisible().catch(() => false))
  check('fire-fetch-200', state.fireFetches.some((s) => s === 200), state.fireFetches.join(','))
  await page.screenshot({ path: `${OUT}/phase-a-no-fire.png`, fullPage: true })

  // ---- 阶段 B：页面保持打开，送入新的 fixture 帧（不刷新/不切页/不输入 run_id）----
  const uploadOut = execFileSync('uv',
    ['--directory', 'backend', 'run', '--locked', 'python', 'scripts/upload_test_capture.py', '--base-url', BACKEND, '--frame', FRAME, RUN_ID],
    { cwd: REPO, encoding: 'utf8' })
  check('upload-accepted', /HTTP (202|200)/.test(uploadOut), uploadOut.split('\n').find((l) => l.startsWith('HTTP')) ?? '')
  await page.locator('.fire-card').first().waitFor({ timeout: 15000 })
  const fireCard = page.locator('.fire-card').filter({ hasText: '双江口' })
  check('fire-card-auto-lit', (await fireCard.count()) === 1)
  check('fire-tag-simulated', await fireCard.getByText('模拟告警 / 接口测试').first().isVisible().catch(() => false))
  const cardText = await fireCard.innerText().catch(() => '')
  check('fire-card-source', cardText.includes('fixture'), cardText.split('\n')[0] ?? '')
  check('fire-card-run', /[0-9a-f]{8}-[0-9a-f]{4}-/.test(cardText))
  check('fire-card-time', cardText.includes('观测'))
  await page.screenshot({ path: `${OUT}/phase-b-auto-lit.png`, fullPage: true })

  // ---- 阶段 C：点开详情入口 ----
  await fireCard.getByRole('button', { name: '查看电厂' }).click()
  await page.waitForTimeout(500)
  check('plant-detail-opens', await page.getByText('双江口水电站').first().isVisible().catch(() => false))
  await page.screenshot({ path: `${OUT}/phase-c-plant-detail.png` })

  // ---- 阶段 D：直接重开首页仍显示 ----
  await page.goto(`${FRONTEND}/#/atlas`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2500)
  const fireCard2 = page.locator('.fire-card').filter({ hasText: '双江口' })
  check('reopen-still-lit', (await fireCard2.count()) === 1)

  console.log('\n--- fire-status fetches ---\n' + state.fireFetches.join(', '))
} catch (e) {
  failures++
  console.error('FATAL:', e instanceof Error ? e.message : String(e))
  await page.screenshot({ path: `${OUT}/error.png`, fullPage: true }).catch(() => {})
} finally {
  const appConsoleErrors = state.consoleErrors.filter((e) => !e.startsWith('Failed to load resource:'))
  failures += results.filter((r) => !r.ok).length + appConsoleErrors.length + state.pageErrors.length + state.failedRequests.length
  const exitCode = failures === 0 ? 0 : 1
  console.log('\n--- app console errors ---'); console.log(appConsoleErrors.length ? appConsoleErrors.join('\n') : '(none)')
  console.log('--- page errors ---'); console.log(state.pageErrors.length ? state.pageErrors.join('\n') : '(none)')
  console.log('--- failed requests ---'); console.log(state.failedRequests.length ? state.failedRequests.join('\n') : '(none)')
  writeFileSync(`${OUT}/result.json`, JSON.stringify({
    executed_at: new Date().toISOString(), elapsed_ms: Date.now() - startTime,
    run_id: RUN_ID, frame: FRAME,
    checks: results, checks_passed: results.filter((r) => r.ok).length, checks_total: results.length,
    app_console_errors: appConsoleErrors, page_errors: state.pageErrors, failed_requests: state.failedRequests,
    fire_status_fetches: state.fireFetches, exit_status: exitCode,
  }, null, 2))
  await browser.close()
}
console.log(`\nRESULT: ${results.filter((r) => r.ok).length}/${results.length} checks passed, ${failures} failures`)
process.exit(failures === 0 ? 0 : 1)
