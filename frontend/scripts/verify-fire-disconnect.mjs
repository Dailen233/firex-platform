// A1 断开/恢复验收：后端停止后首页在一个轮询周期内标出「断开」并保留最近数据
//（不解释成已熄灭）；后端恢复并送入新帧后能重新读取并点亮。
// 截图与结果写入 evidence/fire-status/。
import { chromium } from 'playwright'
import { execFileSync, execSync } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'

const FRONTEND = process.env.FIREX_FRONTEND || 'http://127.0.0.1:4173'
const BACKEND = process.env.FIREX_BACKEND || 'http://127.0.0.1:8002'
const REPO = process.env.FIREX_REPO || '/home/dailen/projects/firex-platform'
const RUN_ID = process.env.FIREX_RUN_ID ?? ''
const FRAME = process.env.FIREX_FRAME ?? '4'
const OUT = process.env.EVIDENCE_DIR || 'evidence/fire-status'
mkdirSync(OUT, { recursive: true })
if (!RUN_ID) { console.error('需要 FIREX_RUN_ID'); process.exit(2) }

function upload(frame) {
  return execFileSync('uv',
    ['--directory', 'backend', 'run', '--locked', 'python', 'scripts/upload_test_capture.py', '--base-url', BACKEND, '--frame', frame, RUN_ID],
    { cwd: REPO, encoding: 'utf8' })
}
function stopBackend() { execSync('pkill -f "uvicorn app.main:app"', { shell: '/bin/bash' }) }
function startBackend() {
  execSync(
    `FIREX_BACKEND_DATA_DIR=/tmp/firex-a1-backend FIREX_PROCESSING_MODE=fixture FIREX_MONITORED_RUN_IDS=${RUN_ID} ` +
    `nohup uv --directory backend run --locked uvicorn app.main:app --host 127.0.0.1 --port 8002 > /tmp/firex-a1-backend.log 2>&1 &`,
    { cwd: REPO, shell: '/bin/bash' })
}

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
const state = { consoleErrors: [], pageErrors: [], failedRequests: [] }
page.on('console', (m) => { if (m.type() === 'error') state.consoleErrors.push(m.text()) })
page.on('pageerror', (e) => state.pageErrors.push(String(e)))
page.on('requestfailed', (r) => { const e = r.failure()?.errorText ?? ''; if (e !== 'net::ERR_ABORTED') state.failedRequests.push(`${r.method()} ${r.url()} ${e}`) })

const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`) }
let failures = 0
const startTime = Date.now()

try {
  // 阶段 1：打开首页，送入新帧建立新鲜基线
  await page.goto(`${FRONTEND}/#/atlas`, { waitUntil: 'domcontentloaded' })
  check('upload-baseline', /HTTP (202|200)/.test(upload(FRAME)), `frame ${FRAME}`)
  await page.locator('.fire-card').first().waitFor({ timeout: 15000 })
  check('baseline-fire-lit', (await page.locator('.fire-card').count()) >= 1)
  await page.screenshot({ path: `${OUT}/dc-1-baseline.png`, fullPage: true })

  // 阶段 2：停止后端 -> 一个轮询周期内标出断开，保留最近数据（不清空、不解释成已熄灭）
  stopBackend()
  await page.getByText('火情监测后端断开').first().waitFor({ timeout: 15000 })
  check('disconnect-shown', await page.getByText('火情监测后端断开').first().isVisible().catch(() => false))
  check('last-data-kept', (await page.locator('.fire-card').count()) >= 1)
  await page.screenshot({ path: `${OUT}/dc-2-disconnected.png`, fullPage: true })

  // 阶段 3：恢复后端并送入新帧 -> 重新读取并点亮
  startBackend()
  await page.waitForTimeout(4000) // 等端口就绪
  check('upload-after-recover', /HTTP (202|200)/.test(upload(String(Number(FRAME) + 1))), `frame ${Number(FRAME) + 1}`)
  await page.locator('.fire-card').first().waitFor({ timeout: 15000 })
  check('reconnect-no-disconnect-label', !(await page.getByText('火情监测后端断开').first().isVisible().catch(() => false)))
  check('reconnect-fire-lit', (await page.locator('.fire-card').count()) >= 1)
  await page.screenshot({ path: `${OUT}/dc-3-recovered.png`, fullPage: true })
} catch (e) {
  failures++
  console.error('FATAL:', e instanceof Error ? e.message : String(e))
  // 尽力恢复后端，避免留下停着的服务
  try { startBackend() } catch { /* ignore */ }
  await page.screenshot({ path: `${OUT}/error.png`, fullPage: true }).catch(() => {})
} finally {
  const appConsoleErrors = state.consoleErrors.filter((e) => !e.startsWith('Failed to load resource:'))
  failures += results.filter((r) => !r.ok).length + appConsoleErrors.length + state.pageErrors.length + state.failedRequests.length
  const exitCode = failures === 0 ? 0 : 1
  console.log('\n--- app console errors ---'); console.log(appConsoleErrors.length ? appConsoleErrors.join('\n') : '(none)')
  console.log('--- page errors ---'); console.log(state.pageErrors.length ? state.pageErrors.join('\n') : '(none)')
  console.log('--- failed requests ---'); console.log(state.failedRequests.length ? state.failedRequests.join('\n') : '(none)')
  writeFileSync(`${OUT}/disconnect-result.json`, JSON.stringify({
    executed_at: new Date().toISOString(), elapsed_ms: Date.now() - startTime,
    run_id: RUN_ID, frame: FRAME,
    checks: results, checks_passed: results.filter((r) => r.ok).length, checks_total: results.length,
    app_console_errors: appConsoleErrors, page_errors: state.pageErrors, failed_requests: state.failedRequests,
    exit_status: exitCode,
  }, null, 2))
  await browser.close()
}
console.log(`\nRESULT: ${results.filter((r) => r.ok).length}/${results.length} checks passed, ${failures} failures`)
process.exit(failures === 0 ? 0 : 1)
