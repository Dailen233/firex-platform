// A3 单轮实测：驱动 demo-a3.sh setup/fire/clear，浏览器观察
// 暂无观测 → YOLO 检出点亮（「仿真影像 · YOLO 检测」）→ 未检出解除高亮。
// 每轮由 setup 新建 run；首页全程不刷新、不输入 run_id。
import { chromium } from 'playwright'
import { execFileSync } from 'node:child_process'
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs'

const REPO = process.env.FIREX_REPO || '/home/dailen/projects/firex-platform'
const FRONTEND = 'http://127.0.0.1:4173'
const ROUND = process.env.FIREX_ROUND || '1'
const OUT = process.env.EVIDENCE_DIR || 'evidence/a3-demo'
const ROUND_OUT = `${OUT}/round-${ROUND}`
mkdirSync(ROUND_OUT, { recursive: true })
const STATE_PATH = '/tmp/firex-a3-demo/state.env'

function demo(args) {
  return execFileSync('bash', ['scripts/demo-a3.sh', ...args], { cwd: REPO, encoding: 'utf8' })
}
function readState() {
  const m = {}
  for (const line of readFileSync(STATE_PATH, 'utf8').split('\n')) {
    const i = line.indexOf('=')
    if (i > 0) m[line.slice(0, i)] = line.slice(i + 1)
  }
  return m
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
const start = Date.now()

try {
  console.log('\n=== setup ===\n' + demo(['setup']))
  const st = readState()
  const runId = st.RUN_ID
  check('setup-new-run-id', !!runId, runId)

  await page.goto(`${FRONTEND}/#/atlas`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2500)
  check('no-alert-before-fire', (await page.locator('.fire-card').count()) === 0)

  console.log('\n=== fire ===\n' + demo(['fire']))
  await page.locator('.fire-card').first().waitFor({ timeout: 30000 })
  check('fire-card-lit', (await page.locator('.fire-card').count()) === 1)
  check('yolo-label', await page.locator('.fire-card').getByText('仿真影像 · YOLO 检测').first().isVisible().catch(() => false))
  await page.screenshot({ path: `${ROUND_OUT}/fire-lit.png`, fullPage: true })

  console.log('\n=== clear ===\n' + demo(['clear']))
  await page.locator('.no-detect-card').first().waitFor({ timeout: 30000 })
  check('fire-cleared', (await page.locator('.fire-card').count()) === 0)
  check('no-detection-shown', (await page.locator('.no-detect-card').count()) === 1)
  check('no-detection-wording', (await page.locator('.no-detect-card').innerText()).includes('本次未检出'))
  await page.screenshot({ path: `${ROUND_OUT}/no-detection.png`, fullPage: true })

  writeFileSync(`${ROUND_OUT}/round.json`, JSON.stringify({ round: ROUND, run_id: runId }, null, 2))
} catch (e) {
  failures++
  console.error('FATAL:', e?.message ?? String(e))
  await page.screenshot({ path: `${ROUND_OUT}/error.png`, fullPage: true }).catch(() => {})
} finally {
  const appConsoleErrors = state.consoleErrors.filter((e) => !e.startsWith('Failed to load resource:'))
  failures += results.filter((r) => !r.ok).length + appConsoleErrors.length + state.pageErrors.length + state.failedRequests.length
  writeFileSync(`${ROUND_OUT}/result.json`, JSON.stringify({
    executed_at: new Date().toISOString(), elapsed_ms: Date.now() - start, round: ROUND,
    checks: results, checks_passed: results.filter((r) => r.ok).length, checks_total: results.length,
    app_console_errors: appConsoleErrors, page_errors: state.pageErrors, failed_requests: state.failedRequests,
    exit_status: failures === 0 ? 0 : 1,
  }, null, 2))
  await browser.close()
}
console.log(`\nRESULT round-${ROUND}: ${results.filter((r) => r.ok).length}/${results.length} passed`)
process.exit(failures === 0 ? 0 : 1)
