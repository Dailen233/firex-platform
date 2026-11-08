// E3.1 本地落点核验：打开双江口模拟水电厂场景，触发开发态「核验 P5 / P6 落点」，
// 校验 unity_world_to_glb 转换点、地形射线命中点、残差，以及 P6 的 X 轴反向（glb X=+2500）。
import { chromium } from 'playwright'
import { mkdirSync, writeFileSync } from 'node:fs'

const FRONTEND = process.env.FIREX_FRONTEND || 'http://127.0.0.1:4173'
const OUT = process.env.EVIDENCE_DIR || 'evidence/sjk-local-registration'
mkdirSync(OUT, { recursive: true })

// 真值来自 sjk_local_registration_v1.json 的 glb_local_xyz_m。
const GT = {
  P5: [0.0, 34.89508819580078, 0.0],
  P6: [2500.0, 644.41162109375, 2500.0],
}
const TOL = 1e-3 // 显示保留 3 位小数；残差为指数形式，允许 1 mm 内

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1360, height: 900 } })
const state = { consoleErrors: [], pageErrors: [], failedRequests: [] }
page.on('console', (m) => { if (m.type() === 'error') state.consoleErrors.push(m.text()) })
page.on('pageerror', (e) => state.pageErrors.push(String(e)))
page.on('requestfailed', (r) => { const e = r.failure()?.errorText ?? ''; if (e !== 'net::ERR_ABORTED') state.failedRequests.push(`${r.method()} ${r.url()} ${e}`) })

const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`) }
let failures = 0
const start = Date.now()

const num = (s) => Number(s.trim())
const near = (a, b, tol = TOL) => a.every((v, i) => Math.abs(v - b[i]) < tol)

async function readPoint(pid) {
  const item = page.locator(`.check-item[data-point-id="${pid}"]`)
  const cv = (await item.locator('.cv').innerText()).split(',').map(num)
  const hitRaw = (await item.locator('.hit').innerText()).trim()
  const hit = hitRaw === '未命中' ? null : hitRaw.split(',').map(num)
  const mres = num(await item.locator('.mres').innerText())
  const rres = num(await item.locator('.rres').innerText())
  return { cv, hit, mres, rres }
}

try {
  await page.goto(`${FRONTEND}/#/scene/sjk_hydropower_sim_v0_1`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.viewer-toolbar', { timeout: 30000 })
  await page.waitForTimeout(800)

  check('dev-entry-visible', await page.locator('.dev-panel').isVisible().catch(() => false))
  await page.getByRole('button', { name: '核验 P5 / P6 落点' }).click()
  await page.locator('.check-item[data-point-id="P6"]').waitFor({ timeout: 10000 })
  await page.waitForTimeout(300)

  const p5 = await readPoint('P5')
  const p6 = await readPoint('P6')

  check('P5-converted', p5.cv.length === 3 && near(p5.cv, GT.P5), p5.cv.join(', '))
  check('P5-hit', !!p5.hit && near(p5.hit, GT.P5), p5.hit?.join(', ') ?? '未命中')
  check('P5-matrix-residual-0', p5.mres < TOL, String(p5.mres))
  check('P5-raycast-residual-0', p5.rres < TOL, String(p5.rres))

  check('P6-converted', p6.cv.length === 3 && near(p6.cv, GT.P6), p6.cv.join(', '))
  check('P6-x-+2500', Math.abs(p6.cv[0] - 2500) < TOL, `glb_x=${p6.cv[0]}`)
  check('P6-hit', !!p6.hit && near(p6.hit, GT.P6), p6.hit?.join(', ') ?? '未命中')
  check('P6-matrix-residual-0', p6.mres < TOL, String(p6.mres))
  check('P6-raycast-residual-0', p6.rres < TOL, String(p6.rres))
  check('P6-x-axis-reversed', await page.locator('.check-item[data-point-id="P6"] .check-pass').isVisible().catch(() => false))

  await page.screenshot({ path: `${OUT}/sjk-local-registration-check.png`, fullPage: true })

  writeFileSync(`${OUT}/points.json`, JSON.stringify({ P5: p5, P6: p6 }, null, 2))
} catch (e) {
  failures++
  console.error('FATAL:', e instanceof Error ? e.message : String(e))
  await page.screenshot({ path: `${OUT}/error.png`, fullPage: true }).catch(() => {})
} finally {
  const appConsoleErrors = state.consoleErrors.filter((e) => !e.startsWith('Failed to load resource:'))
  failures += results.filter((r) => !r.ok).length + appConsoleErrors.length + state.pageErrors.length + state.failedRequests.length
  writeFileSync(`${OUT}/result.json`, JSON.stringify({
    executed_at: new Date().toISOString(), elapsed_ms: Date.now() - start,
    checks: results, checks_passed: results.filter((r) => r.ok).length, checks_total: results.length,
    app_console_errors: appConsoleErrors, page_errors: state.pageErrors, failed_requests: state.failedRequests,
    exit_status: failures === 0 ? 0 : 1,
  }, null, 2))
  console.log('\n--- app console errors ---'); console.log(appConsoleErrors.length ? appConsoleErrors.join('\n') : '(none)')
  console.log('--- page errors ---'); console.log(state.pageErrors.length ? state.pageErrors.join('\n') : '(none)')
  console.log('--- failed requests ---'); console.log(state.failedRequests.length ? state.failedRequests.join('\n') : '(none)')
  await browser.close()
}
console.log(`\nRESULT: ${results.filter((r) => r.ok).length}/${results.length} passed`)
process.exit(failures === 0 ? 0 : 1)
