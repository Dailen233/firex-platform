// A2 YOLO 火情反馈验收：首页保持打开 → 上传人工核对过的正样本（有火焰）→
// 后端实际运行 YOLO → 地图自动点亮并标注「仿真影像 · YOLO 检测」；再上传更晚的
// 已核对无火焰负样本 → 当前高亮解除，只显示「本次未检出」。
// 截图与结果写入 evidence/yolo-fire-status/。
import { chromium } from 'playwright'
import { execFileSync } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'

const FRONTEND = process.env.FIREX_FRONTEND || 'http://127.0.0.1:4173'
const BACKEND = process.env.FIREX_BACKEND || 'http://127.0.0.1:8002'
const REPO = process.env.FIREX_REPO || '/home/dailen/projects/firex-platform'
const RUN_ID = process.env.FIREX_RUN_ID ?? ''
const POSITIVE = process.env.FIREX_POSITIVE_IMAGE ?? '/home/dailen/Nutstore Files/Fire_X/demo_sequences/case01_single_fire/images/frame_0021.png'
const NEGATIVE = process.env.FIREX_NEGATIVE_IMAGE ?? '/home/dailen/Nutstore Files/Fire_X/demo_sequences/case05_false_positive_challenge/images/frame_0001.png'
const OUT = process.env.EVIDENCE_DIR || 'evidence/yolo-fire-status'
mkdirSync(OUT, { recursive: true })
if (!RUN_ID) { console.error('需要 FIREX_RUN_ID'); process.exit(2) }

function upload(frame, image) {
  return execFileSync('uv',
    ['--directory', 'backend', 'run', '--locked', 'python', 'scripts/upload_test_capture.py',
     '--base-url', BACKEND, '--frame', frame, '--image', image, RUN_ID],
    { cwd: REPO, encoding: 'utf8' })
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
  // ---- 阶段 A：首页打开，暂无观测 ----
  await page.goto(`${FRONTEND}/#/atlas`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2500)
  check('homepage-loads', await page.getByText('火情反馈').first().isVisible().catch(() => false))
  check('no-alert-before-upload', (await page.locator('.fire-card').count()) === 0)
  check('fire-fetch-200', state.fireFetches.some((s) => s === 200), state.fireFetches.join(','))
  await page.screenshot({ path: `${OUT}/a-no-observation.png`, fullPage: true })

  // ---- 阶段 B：上传正样本（有火焰），页面保持打开 ----
  const up1 = upload('1', POSITIVE)
  const cap1 = up1.match(/cap-[0-9a-f-]+f001/)?.[0] ?? ''
  check('positive-upload-accepted', /HTTP (202|200)/.test(up1) && cap1 !== '', `capture_id=${cap1}`)
  await page.locator('.fire-card').first().waitFor({ timeout: 30000 })
  const fireCard = page.locator('.fire-card')
  check('fire-card-auto-lit', (await fireCard.count()) === 1)
  check('yolo-label', await fireCard.getByText('仿真影像 · YOLO 检测').first().isVisible().catch(() => false))
  const cardText = await fireCard.innerText().catch(() => '')
  check('yolo-source', cardText.includes('yolo'))
  check('yolo-detection-count', /1 框 · 置信度阈值 0\.25/.test(cardText), cardText.split('\n').find((l) => l.includes('框')) ?? '')
  check('yolo-model-ref', cardText.includes('best.pt#69b1f5c11edc'))
  check('yolo-run-traceable', cardText.includes(RUN_ID.slice(0, 8)) || cardText.includes(RUN_ID))
  check('no-fake-geometry-label', !cardText.includes('三维火区'))
  await page.screenshot({ path: `${OUT}/b-positive-fire-lit.png`, fullPage: true })

  // ---- 阶段 C：上传更晚的负样本（已核对无火焰），页面保持打开 ----
  const up2 = upload('2', NEGATIVE)
  const cap2 = up2.match(/cap-[0-9a-f-]+f002/)?.[0] ?? ''
  check('negative-upload-accepted', /HTTP (202|200)/.test(up2) && cap2 !== '', `capture_id=${cap2}`)
  await page.locator('.no-detect-card').first().waitFor({ timeout: 30000 })
  check('fire-highlight-cleared', (await page.locator('.fire-card').count()) === 0)
  const noDetect = page.locator('.no-detect-card')
  check('no-detection-shown', (await noDetect.count()) === 1)
  const noText = await noDetect.innerText().catch(() => '')
  check('no-detection-wording-only', noText.includes('本次未检出') && !noText.includes('无火') && !noText.includes('已熄灭'), noText.replace(/\n/g, ' | '))
  check('bottomline-no-detection', await page.getByText('火情监测已接入 · 本次未检出').first().isVisible().catch(() => false))
  await page.screenshot({ path: `${OUT}/c-negative-no-detection.png`, fullPage: true })

  writeFileSync(`${OUT}/captures.json`, JSON.stringify({ run_id: RUN_ID, positive: cap1, negative: cap2 }, null, 2))
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
    run_id: RUN_ID, mode: 'yolo',
    checks: results, checks_passed: results.filter((r) => r.ok).length, checks_total: results.length,
    app_console_errors: appConsoleErrors, page_errors: state.pageErrors, failed_requests: state.failedRequests,
    fire_status_fetches: state.fireFetches, exit_status: exitCode,
  }, null, 2))
  await browser.close()
}
console.log(`\nRESULT: ${results.filter((r) => r.ok).length}/${results.length} checks passed, ${failures} failures`)
process.exit(failures === 0 ? 0 : 1)
