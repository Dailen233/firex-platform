// 双江口模拟水电厂 v0.1 接入验收：从双江口详情打开新场景，检查贴图地形、厂区取景、
// 对象点选（厂房/主变区/地形贴图文案），并回归织金、参考底座与两份 E1 草案。
// 截图与结果写入 evidence/sjk-hydropower-sim/。
import { chromium } from 'playwright'
import { mkdirSync, writeFileSync } from 'node:fs'

const FRONTEND = process.env.FIREX_FRONTEND || 'http://127.0.0.1:4173'
const OUT = process.env.EVIDENCE_DIR || 'evidence/sjk-hydropower-sim'
mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
const state = { consoleErrors: [], pageErrors: [], failedRequests: [], glbFetches: [] }
page.on('console', (m) => { if (m.type() === 'error') state.consoleErrors.push(m.text()) })
page.on('pageerror', (e) => state.pageErrors.push(String(e)))
page.on('requestfailed', (r) => { const e = r.failure()?.errorText ?? ''; if (e !== 'net::ERR_ABORTED') state.failedRequests.push(`${r.method()} ${r.url()} ${e}`) })
page.on('response', (r) => { const u = r.url(); if (u.includes('.glb')) state.glbFetches.push(u.split('/').pop()) })

const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`) }
let fatalCount = 0
let failures = 0
const startTime = Date.now()

async function openScene(sceneId) {
  await page.goto(`${FRONTEND}/#/scene/${sceneId}`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.viewer-toolbar', { timeout: 30000 })
  await page.waitForTimeout(700)
}

try {
  // 1) 双江口详情：新入口出现，旧入口保留
  await page.goto(`${FRONTEND}/#/atlas?plant=GEM_HYDRO_SHUANGJIANGKOU`, { waitUntil: 'domcontentloaded' })
  await page.getByText('双江口模拟水电厂').first().waitFor({ timeout: 15000 })
  check('atlas-sim-entry', await page.getByText('双江口模拟水电厂').first().isVisible().catch(() => false))
  check('atlas-reference-preserved', await page.getByText('浏览山地参考底座').first().isVisible().catch(() => false))
  check('atlas-draft-terrain-preserved', await page.getByText('双江口队友地形草案').first().isVisible().catch(() => false))
  check('atlas-draft-concept-preserved', await page.getByText('双江口枢纽构件草案').first().isVisible().catch(() => false))
  await page.screenshot({ path: `${OUT}/atlas-sjk-detail.png` })

  // 2) 从详情点击进入新场景
  const simCard = page.locator('.scene-card.prototype').filter({ hasText: '双江口模拟水电厂' })
  check('sim-card-link-present', (await simCard.locator('a').count()) === 1)
  await simCard.locator('a').click()
  await page.waitForSelector('.viewer-toolbar', { timeout: 30000 })
  await page.waitForTimeout(1000)

  // 3) 场景加载与文案
  const loaded = await page.locator('.loaded-status').innerText().catch(() => '')
  check('sim-scene-loads', loaded.includes('双江口模拟水电厂'), loaded.trim())
  check('sim-badge-unregistered', await page.getByText('模拟厂区 · 未配准').first().isVisible().catch(() => false))
  check('sim-no-elevation-badge', !(await page.getByText('高程示意色 · 非植被或火险').first().isVisible().catch(() => false)))
  check('sim-fetches-own-glb', state.glbFetches.includes('sjk_hydropower_sim_v0_1.glb'), state.glbFetches.slice(-2).join(','))
  check('sim-no-fire-overlay', (await page.getByRole('button', { name: '聚焦火区' }).count()) === 0)
  check('sim-plant-camera-button', await page.getByRole('button', { name: '厂区取景' }).first().isVisible().catch(() => false))
  check('sim-whole-terrain-button', await page.getByRole('button', { name: '全域地形' }).first().isVisible().catch(() => false))
  const simAxis = await page.locator('.axis-label').innerText().catch(() => '')
  check('sim-axis-unverified', simAxis.includes('文件米制轴') && simAxis.includes('地理方向待核实'), simAxis.trim())
  await page.screenshot({ path: `${OUT}/sim-default.png` })

  // 4) 厂区取景 / 全域地形
  await page.getByRole('button', { name: '厂区取景' }).first().click()
  await page.waitForTimeout(600)
  await page.screenshot({ path: `${OUT}/sim-plant-camera.png` })
  await page.getByRole('button', { name: '全域地形' }).first().click()
  await page.waitForTimeout(600)
  await page.screenshot({ path: `${OUT}/sim-whole-terrain.png` })

  // 5) 对象点选：厂房 + 主变区 + 地形（贴图文案）
  await page.selectOption('#object-select', 'powerhouse')
  await page.waitForTimeout(300)
  const title1 = await page.locator('.object-detail h2').innerText().catch(() => '')
  check('select-powerhouse', title1.includes('发电厂房'), title1.trim())
  check('facility-simulated-tag', await page.getByText('模拟设施 · 演示设计').first().isVisible().catch(() => false))
  await page.screenshot({ path: `${OUT}/sim-select-powerhouse.png` })

  await page.selectOption('#object-select', 'transformer_yard')
  await page.waitForTimeout(300)
  const title2 = await page.locator('.object-detail h2').innerText().catch(() => '')
  check('select-transformer-yard', title2.includes('主变及出线区'), title2.trim())
  await page.screenshot({ path: `${OUT}/sim-select-transformer-yard.png` })

  await page.selectOption('#object-select', 'terrain')
  await page.waitForTimeout(300)
  const hasTextureNotice = await page.getByText('贴图地形（队友影像原字节保留）', { exact: false }).first().isVisible().catch(() => false)
  const hasNoTextureNotice = await page.getByText('无卫星贴图', { exact: false }).first().isVisible().catch(() => false)
  check('terrain-textured-notice', hasTextureNotice && !hasNoTextureNotice)

  // 6) 回归：织金 + 参考底座 + E1 草案
  await openScene('zhijin_pilot')
  check('regression-zhijin', (await page.locator('.loaded-status').innerText().catch(() => '')).includes('织金'))
  await page.screenshot({ path: `${OUT}/regression-zhijin.png` })

  await openScene('shuangjiangkou_reference_terrain')
  check('regression-reference', (await page.locator('.loaded-status').innerText().catch(() => '')).includes('参考底座'))
  await page.screenshot({ path: `${OUT}/regression-reference.png` })

  await openScene('sjk_team_terrain_draft_v0_1')
  check('regression-draft-terrain', (await page.locator('.loaded-status').innerText().catch(() => '')).includes('地形草案'))
  await openScene('sjk_facility_concept_v0_1')
  check('regression-draft-concept', (await page.locator('.loaded-status').innerText().catch(() => '')).includes('枢纽构件草案'))

  console.log('\n--- glb fetches ---\n' + state.glbFetches.join(', '))
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
    executed_at: new Date().toISOString(),
    elapsed_ms: elapsedMs,
    checks: results,
    checks_passed: results.filter((r) => r.ok).length,
    checks_total: results.length,
    app_console_errors: appConsoleErrors,
    page_errors: state.pageErrors,
    failed_requests: state.failedRequests,
    fatal_count: fatalCount,
    exit_status: exitCode,
    glb_fetches: state.glbFetches,
  }, null, 2))
  await browser.close()
}

console.log(`\nRESULT: ${results.filter((r) => r.ok).length}/${results.length} checks passed, ${failures} failures`)
process.exit(failures === 0 ? 0 : 1)
