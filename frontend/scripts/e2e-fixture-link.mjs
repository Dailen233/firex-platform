// B4 happy-path browser verification against a REAL fixture backend.
//
// Usage: node scripts/e2e-fixture-link.mjs <run_id> [out_dir]
//
// Exit code is non-zero on: any unexpected exception, any failed check, any
// console error, any page error, or any unexpected failed request. Steps are
// asserted to actually run; a navigation that never reaches the scene fails the
// run instead of reporting "0/0 checks passed".
//
// Disconnect evidence ordering (fixed camera, single mount): the map/detail
// round-trip happens FIRST, then the scene is re-entered and the fire is framed
// ONCE. disconnect-before.png and disconnect-after.png are taken in that same
// mount, so the only difference between them is the overlay being cleared
// (camera, canvas size and view are unchanged).
import { FRONTEND, SCENE_URL, verifyService, launchPage, makeChecks, waitForText, finish } from './e2e-utils.mjs'

const RUN_ID = process.argv[2]
const OUT = process.argv[3] || '/tmp/firex-b4-e2e'
if (!RUN_ID) {
  console.error('usage: node scripts/e2e-fixture-link.mjs <run_id> [out_dir]')
  process.exit(2)
}

const ATLAS_URL = `${FRONTEND}/#/atlas?plant=GEM_HYDRO_SHUANGJIANGKOU`

async function factValue(page, label) {
  return (await page.locator('.conn-facts > div', { has: page.getByText(label, { exact: true }) }).locator('dd').innerText()).trim()
}

const { browser, page, state } = await launchPage()
const checks = makeChecks()
let ran = 0
try {
  await verifyService() // refuse to drive a non-firex service

  // 1. Load the scene (must actually reach the viewer).
  await page.goto(SCENE_URL, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.viewer-toolbar', { timeout: 30000 })
  ran++; checks.check('scene-loaded', true)

  // 2. Connect the run.
  await page.getByPlaceholder('输入 run_id').fill(RUN_ID)
  await page.getByRole('button', { name: '连接', exact: true }).click()
  await waitForText(page, '已连接', { exact: true, label: '已连接状态' })
  ran++; checks.check('connected', true)

  // 3. Snapshot arrives; precise field assertions (not whole-panel includes()).
  await waitForText(page, '接口测试数据，不代表图像重建', { label: 'fixture 标注' })
  ran++; checks.check('fixture-label', true)
  checks.check('revision-2', (await factValue(page, 'revision')) === '2', await factValue(page, 'revision'))
  checks.check('obs-19', (await factValue(page, '观测时间')) === '19.0 s（相对仿真原点）', await factValue(page, '观测时间'))
  checks.check('origin-fixture', (await factValue(page, '来源')) === 'fixture', await factValue(page, '来源'))
  checks.check('provider-1.0', (await factValue(page, '提供者版本')) === '1.0', await factValue(page, '提供者版本'))

  // 4. Overlay mapped -> focus button appears.
  await page.getByRole('button', { name: '聚焦火区' }).waitFor({ timeout: 5000 })
  ran++; checks.check('overlay-mapped', true)

  // 5. GLB loaded exactly once during this scene mount (not re-fetched by polling).
  await page.waitForTimeout(3000)
  checks.check('glb-not-reloaded-by-polling', state.glbFetches === 1, `fetches=${state.glbFetches}`)

  // 6. Map sync (atlas -> plant detail shows the interface-test status).
  await page.goto(ATLAS_URL, { waitUntil: 'domcontentloaded' })
  await waitForText(page, '接口测试数据 · 不代表图像重建', { label: '地图接口测试标记' })
  ran++; checks.check('map-sync', true)
  const detailText = await page.locator('.plant-detail').innerText()
  checks.check('detail-sync', detailText.includes('接口测试数据，不代表图像重建') && detailText.includes('fixture'))
  await page.screenshot({ path: `${OUT}/atlas-detail.png` })

  // 7. Back to scene: connection survives navigation; same run/revision/overlay.
  await page.goto(SCENE_URL, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.viewer-toolbar', { timeout: 30000 })
  await waitForText(page, '已连接', { exact: true, label: '返回场景后仍连接' })
  await page.getByRole('button', { name: '聚焦火区' }).waitFor({ timeout: 10000 })
  checks.check('revision-still-2', (await factValue(page, 'revision')) === '2', await factValue(page, 'revision'))
  ran++; checks.check('connection-survives-navigation', true)

  // 8. Focus the fire ONCE, wait for the camera to fully settle, then screenshot.
  await page.getByRole('button', { name: '聚焦火区' }).click()
  await page.waitForTimeout(2000)
  await page.screenshot({ path: `${OUT}/disconnect-before.png` })
  ran++; checks.check('focus-screenshot', true)

  // 9. Disconnect in the SAME mount (camera / canvas / view unchanged), then screenshot.
  await page.getByRole('button', { name: '断开' }).click()
  await waitForText(page, '已连接', { exact: true, timeout: 5000, label: '断开后无已连接' }).catch(() => {})
  await page.waitForTimeout(1500) // allow the deferred render of the cleared overlay
  await page.screenshot({ path: `${OUT}/disconnect-after.png` })
  const focusGone = await page.getByRole('button', { name: '聚焦火区' }).count() === 0
  checks.check('disconnect-clears-ui', focusGone)
  ran++; checks.check('disconnect-render-captured', true)

  checks.check('steps-complete', ran === 8, `ran=${ran} expected=8`)
} catch (e) {
  checks.fail(e)
  await page.screenshot({ path: `${OUT}/error.png` }).catch(() => {})
} finally {
  const failures = await finish(browser, checks, state)
  if (checks.results.length === 0) {
    console.error('RESULT: 0/0 checks executed (navigation/connect never completed)')
    process.exitCode = 1
  } else {
    process.exitCode = failures > 0 ? 1 : 0
  }
}
