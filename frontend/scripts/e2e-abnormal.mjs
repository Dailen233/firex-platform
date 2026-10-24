// B4 abnormal-branch browser verification using response interception.
// Clearly separated from the real-fixture happy path (e2e-fixture-link.mjs):
// the happy path uses a real fixture backend; these branches intercept specific
// responses to exercise identity mismatch, binding mismatch, revision regression
// and late-response-after-switch. /health and the run endpoints are mocked so the
// tests are self-contained (no backend needed).
//
// Usage: node scripts/e2e-abnormal.mjs
import { chromium } from 'playwright'
import { SCENE_URL, makeChecks, waitForText, finish } from './e2e-utils.mjs'

const HEALTH = { status: 'ok', algorithm_mode: 'unconfigured', service: 'firex-backend', processing_mode: 'fixture' }
const RUN = { run_id: 'run-A', plant_id: 'GEM_HYDRO_SHUANGJIANGKOU', scene_id: 'shuangjiangkou_reference_terrain', asset_version: 'reference-v1', coordinate_frame_id: 'SJK_REFERENCE_UTM47N_EGM2008_v1', input_source: 'simulation', schema_version: '1.0', created_at: '2026-01-01T00:00:00Z', simulation_time_origin_s: 10.0, time_origin_utc: null }
const OBS = (revision, geometry, runId = 'run-A') => ({ run_id: runId, plant_id: 'GEM_HYDRO_SHUANGJIANGKOU', scene_id: 'shuangjiangkou_reference_terrain', asset_version: 'reference-v1', coordinate_frame_id: 'SJK_REFERENCE_UTM47N_EGM2008_v1', input_source: 'simulation', schema_version: '1.0', state_status: 'observation', revision, observation_time_s: 19.0, result_origin: 'fixture', provider_version: '1.0', evidence_capture_ids: ['cap-1'], patches: [{ patch_id: 'fixture-patch-1', geometry }], produced_at: '2026-01-01T00:00:05Z', time_basis: 'simulation_relative', simulation_time_origin_s: 10.0, time_origin_utc: null })
const GEOM_BIG = [[76, 176], [124, 176], [124, 224], [76, 224], [76, 176]]
const GEOM_SMALL = [[94, 194], [106, 194], [106, 206], [94, 206], [94, 194]]

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const state = { consoleErrors: [], pageErrors: [], failedRequests: [] }
const checks = makeChecks()

async function newPage(routes) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
  page.on('console', (m) => { if (m.type() === 'error') state.consoleErrors.push(m.text()) })
  page.on('pageerror', (e) => state.pageErrors.push(String(e)))
  page.on('requestfailed', (r) => { const e = r.failure()?.errorText ?? ''; if (e !== 'net::ERR_ABORTED') state.failedRequests.push(`${r.url()} ${e}`) })
  await page.route('**/health', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(HEALTH) }))
  if (routes) await routes(page)
  return page
}

async function gotoScene(page) {
  await page.goto(SCENE_URL, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.viewer-toolbar', { timeout: 30000 })
}

// 1. Identity mismatch: request run-A, backend returns run-B -> rejected.
{
  const page = await newPage((p) => p.route('**/api/v1/runs/run-A', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...RUN, run_id: 'run-B' }) })))
  try {
    await gotoScene(page)
    await page.getByPlaceholder('输入 run_id').fill('run-A')
    await page.getByRole('button', { name: '连接', exact: true }).click()
    await waitForText(page, '运行身份不符', { label: '身份不符错误' })
    checks.check('identity-mismatch-rejected', true)
    checks.check('identity-not-connected', (await page.getByText('已连接', { exact: true }).count()) === 0)
  } catch (e) { checks.fail(e) } finally { await page.close() }
}

// 2. Binding mismatch: snapshot plant differs from run plant -> rejected, no overlay.
{
  const page = await newPage(async (p) => {
    await p.route('**/api/v1/runs/run-A', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RUN) }))
    await p.route('**/api/v1/runs/run-A/state', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...OBS(1, GEOM_SMALL), plant_id: 'GEM_COAL_ZHIJIN' }) }))
  })
  try {
    await gotoScene(page)
    await page.getByPlaceholder('输入 run_id').fill('run-A')
    await page.getByRole('button', { name: '连接', exact: true }).click()
    await waitForText(page, 'plant_id', { label: 'plant_id 不符错误' })
    checks.check('binding-mismatch-rejected', true)
    checks.check('binding-no-overlay', (await page.getByRole('button', { name: '聚焦火区' }).count()) === 0)
  } catch (e) { checks.fail(e) } finally { await page.close() }
}

// 3. Revision regression: after revision 2, a revision 1 reply must not overwrite.
{
  let calls = 0
  const page = await newPage(async (p) => {
    await p.route('**/api/v1/runs/run-A', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RUN) }))
    await p.route('**/api/v1/runs/run-A/state', (r) => {
      calls++
      const body = calls === 1 ? OBS(2, GEOM_BIG) : OBS(1, GEOM_SMALL) // first poll rev 2, then regress to rev 1
      return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    })
  })
  try {
    await gotoScene(page)
    await page.getByPlaceholder('输入 run_id').fill('run-A')
    await page.getByRole('button', { name: '连接', exact: true }).click()
    await page.getByText('已连接', { exact: true }).waitFor({ timeout: 10000 })
    await page.waitForTimeout(2500) // allow the regression poll to arrive
    const revision = (await page.locator('.conn-facts > div', { has: page.getByText('revision', { exact: true }) }).locator('dd').innerText()).trim()
    checks.check('regression-keeps-revision-2', revision === '2', `revision=${revision}`)
    await waitForText(page, '旧 revision', { label: '回归错误提示' })
    checks.check('regression-flagged', true)
  } catch (e) { checks.fail(e) } finally { await page.close() }
}

// 4. Late response after switch must not pollute the new connection.
{
  const page = await newPage(async (p) => {
    await p.route('**/api/v1/runs/run-A', async (r) => { await new Promise((s) => setTimeout(s, 2500)); return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RUN) }) })
    await p.route('**/api/v1/runs/run-B', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...RUN, run_id: 'run-B' }) }))
    await p.route('**/api/v1/runs/run-B/state', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(OBS(1, GEOM_SMALL, 'run-B')) }))
  })
  try {
    await gotoScene(page)
    await page.getByPlaceholder('输入 run_id').fill('run-A')
    await page.getByRole('button', { name: '连接', exact: true }).click()
    await page.waitForTimeout(300) // run-A connect still in flight (delayed)
    await page.getByRole('button', { name: '断开' }).click() // cancel run-A connect
    await page.getByPlaceholder('输入 run_id').fill('run-B')
    await page.getByRole('button', { name: '连接', exact: true }).click()
    await page.getByText('已连接', { exact: true }).waitFor({ timeout: 10000 })
    await page.waitForTimeout(3000) // let the delayed run-A response land (or be aborted)
    const runIdShown = (await page.locator('.run-id').innerText()).trim()
    checks.check('late-response-isolated', runIdShown === 'run-B', `shown=${runIdShown}`)
  } catch (e) { checks.fail(e) } finally { await page.close() }
}

const failures = await finish(browser, checks, state)
process.exitCode = failures > 0 ? 1 : 0
