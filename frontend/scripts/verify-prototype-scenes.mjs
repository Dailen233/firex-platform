// E1/E2.0 验证：双江口两份模型草案（地形 + 概念构件）在真实浏览器中的显示与切换。
// 检查：场景加载、未配准徽标、高程示意色、无火区覆盖层、各自 GLB 无串加载、
//      旧参考底座回归、草案坐标轴文案、加载失败提示、以及故障注入（404/哈希）与精确分类。
// 截图与结果写入 evidence/sjk-prototype-e1/。
import { chromium } from 'playwright'
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const FRONTEND = process.env.FIREX_FRONTEND || 'http://127.0.0.1:4173'
const OUT = process.env.EVIDENCE_DIR || 'evidence/sjk-prototype-e1'
const terrainGlbPath = fileURLToPath(new URL('../public/models/sjk-prototype-v0.1/team_terrain_untextured_m.glb', import.meta.url))
mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
const state = { consoleErrors: [], pageErrors: [], failedRequests: [], httpFailures: [], glbFetches: [] }
let currentPhase = 'baseline'
page.on('console', (m) => { if (m.type() === 'error') state.consoleErrors.push(m.text()) })
page.on('pageerror', (e) => state.pageErrors.push(String(e)))
page.on('requestfailed', (r) => { const e = r.failure()?.errorText ?? ''; if (e !== 'net::ERR_ABORTED') state.failedRequests.push(`${r.method()} ${r.url()} ${e}`) })
// 精确记录 HTTP 失败（资源定位 + 状态 + 阶段）；浏览器网络日志不再作为白名单依据。
page.on('response', (r) => { const u = r.url(); if (u.includes('.glb')) state.glbFetches.push(u.split('/').pop()); if (r.status() >= 400) state.httpFailures.push({ method: r.request().method(), url: u, status: r.status(), phase: currentPhase }) })

const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`) }
let fatalCount = 0
let failures = 0
let appConsoleErrors = []
let httpClassification = { expected: [], unexpected: [] }
const startTime = Date.now()
// 预期注入的 HTTP 故障：仅豁免「URL 后缀 + 状态码 + 阶段」三者都匹配的条目（非全局 404 白名单）。
const injectedFaults = [
  { urlSuffix: '/models/sjk-prototype-v0.1/team_terrain_untextured_m.glb', status: 404, phase: 'fault-404' },
]
function classifyHttpFailures(failuresList, expected) {
  const expectedHits = []; const unexpected = []
  for (const f of failuresList) {
    if (expected.some((e) => f.url.endsWith(e.urlSuffix) && f.status === e.status && f.phase === e.phase)) expectedHits.push(f)
    else unexpected.push(f)
  }
  return { expected: expectedHits, unexpected }
}

async function openScene(sceneId) {
  await page.goto(`${FRONTEND}/#/scene/${sceneId}`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.viewer-toolbar', { timeout: 30000 })
  await page.waitForTimeout(700)
}

try {
  // 1) 地形草案
  await openScene('sjk_team_terrain_draft_v0_1')
  const terrainLoaded = await page.locator('.loaded-status').innerText().catch(() => '')
  check('terrain-scene-loads', terrainLoaded.includes('地形草案'), terrainLoaded.trim())
  check('terrain-fetches-own-glb', state.glbFetches.includes('team_terrain_untextured_m.glb'), state.glbFetches.slice(-2).join(','))
  check('terrain-badge-unregistered', await page.getByText('模型草案 · 未配准').first().isVisible().catch(() => false))
  check('terrain-elevation-color-badge', await page.getByText('高程示意色 · 非植被或火险').first().isVisible().catch(() => false))
  check('terrain-10km-stat', await page.getByText('约10km×10km').first().isVisible().catch(() => false))
  check('terrain-no-fire-overlay', (await page.getByRole('button', { name: '聚焦火区' }).count()) === 0)
  const terrainAxis = await page.locator('.axis-label').innerText().catch(() => '')
  check('terrain-axis-unverified', terrainAxis.includes('文件米制轴') && terrainAxis.includes('地理方向待核实'), terrainAxis.trim())
  await page.screenshot({ path: `${OUT}/terrain-draft.png` })
  await page.locator('.viewer-bottom').scrollIntoViewIfNeeded().catch(() => {})
  await page.locator('.viewer-bottom').screenshot({ path: `${OUT}/terrain-axis-label.png` }).catch(() => {})

  // 2) 概念草案（场景切换，须各自加载、无串加载）
  const glbBefore = state.glbFetches.length
  await openScene('sjk_facility_concept_v0_1')
  const conceptLoaded = await page.locator('.loaded-status').innerText().catch(() => '')
  check('concept-scene-loads', conceptLoaded.includes('枢纽构件草案'), conceptLoaded.trim())
  check('concept-fetches-own-glb', state.glbFetches.slice(glbBefore).includes('sjk_concept_layout.glb'), state.glbFetches.slice(glbBefore).join(','))
  check('concept-badge-unregistered', await page.getByText('模型草案 · 未配准').first().isVisible().catch(() => false))
  check('concept-no-elevation-badge', !(await page.getByText('高程示意色 · 非植被或火险').first().isVisible().catch(() => false)))
  check('concept-stat', await page.getByText('概念构件 · 未地理定位').first().isVisible().catch(() => false))
  check('concept-no-fire-overlay', (await page.getByRole('button', { name: '聚焦火区' }).count()) === 0)
  const conceptAxis = await page.locator('.axis-label').innerText().catch(() => '')
  check('concept-axis-unverified', conceptAxis.includes('文件米制轴') && conceptAxis.includes('地理方向待核实'), conceptAxis.trim())
  await page.screenshot({ path: `${OUT}/concept-draft.png` })

  // 3) 双江口详情：保留旧参考底座入口，且新增两份草案入口
  await page.goto(`${FRONTEND}/#/atlas?plant=GEM_HYDRO_SHUANGJIANGKOU`, { waitUntil: 'domcontentloaded' })
  await page.getByText('双江口队友地形草案').first().waitFor({ timeout: 15000 })
  check('atlas-terrain-entry', await page.getByText('双江口队友地形草案').first().isVisible().catch(() => false))
  check('atlas-concept-entry', await page.getByText('双江口枢纽构件草案').first().isVisible().catch(() => false))
  check('atlas-reference-preserved', await page.getByText('浏览山地参考底座').first().isVisible().catch(() => false))
  check('atlas-draft-status-text', await page.getByText('地形待贴图 · 尚未配准').first().isVisible().catch(() => false))
  await page.screenshot({ path: `${OUT}/atlas-sjk-detail.png` })
  const protoCard = page.locator('.scene-card.prototype').first()
  if (await protoCard.count()) await protoCard.screenshot({ path: `${OUT}/atlas-prototype-card.png` }).catch(() => {})

  // 4) 旧场景回归：织金正式场景 + 双江口参考底座仍可进入，且保留原坐标轴契约
  await openScene('zhijin_pilot')
  const zhijinLoaded = await page.locator('.loaded-status').innerText().catch(() => '')
  check('regression-zhijin-loads', zhijinLoaded.includes('织金'), zhijinLoaded.trim())
  await page.screenshot({ path: `${OUT}/regression-zhijin.png` })

  await openScene('shuangjiangkou_reference_terrain')
  const refLoaded = await page.locator('.loaded-status').innerText().catch(() => '')
  check('regression-reference-loads', refLoaded.includes('参考底座'), refLoaded.trim())
  check('regression-reference-fetches-own-glb', state.glbFetches.includes('terrain_reference.glb'))
  const refAxis = await page.locator('.axis-label').innerText().catch(() => '')
  check('old-scene-axis-preserved', refAxis.includes('X 东') && refAxis.includes('Z 南'), refAxis.trim())
  await page.screenshot({ path: `${OUT}/regression-reference.png` })

  // 5) 加载失败提示：不存在的场景必须给出明确错误，不静默
  await page.goto(`${FRONTEND}/#/scene/nonexistent_scene`, { waitUntil: 'domcontentloaded' })
  await page.getByText('场景不存在').first().waitFor({ timeout: 10000 })
  check('missing-scene-shows-error', true)
  await page.screenshot({ path: `${OUT}/missing-scene-error.png` })

  // 6) 故障注入：GLB 404 —— 明确失败提示，且无上一场景残留（先载入概念场景作基线）
  await openScene('sjk_facility_concept_v0_1')
  currentPhase = 'fault-404'
  await page.route('**/team_terrain_untextured_m.glb', (route) => route.fulfill({ status: 404, contentType: 'application/octet-stream', body: 'not found' }))
  await page.goto(`${FRONTEND}/#/scene/sjk_team_terrain_draft_v0_1`, { waitUntil: 'domcontentloaded' })
  await page.getByText('三维模型加载失败').first().waitFor({ timeout: 15000 })
  check('fault-404-shows-error', await page.getByText('三维模型加载失败').first().isVisible().catch(() => false))
  check('fault-404-specific-message', await page.getByText('模型读取失败（HTTP 404）').first().isVisible().catch(() => false))
  check('fault-404-no-previous-residue', !(await page.getByText('枢纽构件草案').first().isVisible().catch(() => false)))
  await page.screenshot({ path: `${OUT}/fault-404.png` })
  await page.unroute('**/team_terrain_untextured_m.glb')
  currentPhase = 'baseline'

  // 7) 故障注入：GLB 200 + 字节被改（触发哈希校验失败；长度不变，不触发大小检查）
  await openScene('sjk_facility_concept_v0_1')
  currentPhase = 'fault-hash'
  const glbBytes = readFileSync(terrainGlbPath)
  const jsonLen = glbBytes.readUInt32LE(12)
  const binStart = 20 + jsonLen + 8 // 20 字节头 + JSON chunk + BIN chunk 头
  const corrupted = Buffer.from(glbBytes)
  corrupted[binStart + 40] ^= 0xff // 改 POSITION 数据内一个字节，长度不变
  await page.route('**/team_terrain_untextured_m.glb', (route) => route.fulfill({ status: 200, contentType: 'model/gltf-binary', body: corrupted }))
  await page.goto(`${FRONTEND}/#/scene/sjk_team_terrain_draft_v0_1`, { waitUntil: 'domcontentloaded' })
  await page.getByText('三维模型加载失败').first().waitFor({ timeout: 15000 })
  check('fault-hash-shows-error', await page.getByText('三维模型加载失败').first().isVisible().catch(() => false))
  check('fault-hash-specific-message', await page.getByText('模型文件哈希与交接记录不一致').first().isVisible().catch(() => false))
  check('fault-hash-no-previous-residue', !(await page.getByText('枢纽构件草案').first().isVisible().catch(() => false)))
  await page.screenshot({ path: `${OUT}/fault-hash.png` })
  await page.unroute('**/team_terrain_untextured_m.glb')
  currentPhase = 'baseline'

  // 8) 恢复：解除拦截后地形草案仍可正常加载（先切到概念场景强制完整导航，再回地形，证明故障注入被隔离）
  await openScene('sjk_facility_concept_v0_1')
  await openScene('sjk_team_terrain_draft_v0_1')
  check('recover-terrain-after-fault', (await page.locator('.loaded-status').innerText().catch(() => '')).includes('地形草案'))

  // 9) 故障分类自检（F-03）：非目标资源 404 必须判为「意外」（会报失败），目标 404 被豁免
  const nontargetProbe = classifyHttpFailures(
    [{ method: 'GET', url: `${FRONTEND}/models/not-injected-resource.glb`, status: 404, phase: 'fault-404' }],
    injectedFaults,
  )
  check('fault-classifier-flags-nontarget-404', nontargetProbe.unexpected.length === 1 && nontargetProbe.expected.length === 0, JSON.stringify(nontargetProbe))
  const targetProbe = classifyHttpFailures(
    [{ method: 'GET', url: `${FRONTEND}/models/sjk-prototype-v0.1/team_terrain_untextured_m.glb`, status: 404, phase: 'fault-404' }],
    injectedFaults,
  )
  check('fault-classifier-exempts-target-404', targetProbe.expected.length === 1 && targetProbe.unexpected.length === 0, JSON.stringify(targetProbe))

  console.log('\n--- glb fetches ---\n' + state.glbFetches.join(', '))
} catch (e) {
  fatalCount++
  console.error('FATAL:', e instanceof Error ? e.message : String(e))
  await page.screenshot({ path: `${OUT}/error.png` }).catch(() => {})
} finally {
  const elapsedMs = Date.now() - startTime
  // 浏览器网络日志（"Failed to load resource: ..."）不是应用 console.error；HTTP 失败已由 httpFailures 精确记录。
  appConsoleErrors = state.consoleErrors.filter((e) => !e.startsWith('Failed to load resource:'))
  httpClassification = classifyHttpFailures(state.httpFailures, injectedFaults)
  failures = results.filter((r) => !r.ok).length + appConsoleErrors.length + state.pageErrors.length + state.failedRequests.length + httpClassification.unexpected.length + fatalCount
  const exitCode = failures === 0 ? 0 : 1
  console.log('\n--- app console errors ---'); console.log(appConsoleErrors.length ? appConsoleErrors.join('\n') : '(none)')
  console.log('--- page errors ---'); console.log(state.pageErrors.length ? state.pageErrors.join('\n') : '(none)')
  console.log('--- unexpected failed requests ---'); console.log(state.failedRequests.length ? state.failedRequests.join('\n') : '(none)')
  console.log(`--- http failures --- 预期注入 ${httpClassification.expected.length} 条，意外 ${httpClassification.unexpected.length} 条`)
  for (const f of httpClassification.unexpected) console.log(`UNEXPECTED HTTP ${f.status} ${f.url} [${f.phase}]`)
  writeFileSync(`${OUT}/result.json`, JSON.stringify({
    executed_at: new Date().toISOString(),
    elapsed_ms: elapsedMs,
    checks: results,
    checks_passed: results.filter((r) => r.ok).length,
    checks_total: results.length,
    expected_faults: httpClassification.expected,
    unexpected_errors: {
      app_console_errors: appConsoleErrors,
      page_errors: state.pageErrors,
      failed_requests: state.failedRequests,
      unexpected_http_failures: httpClassification.unexpected,
    },
    fatal_count: fatalCount,
    exit_status: exitCode,
    glb_fetches: state.glbFetches,
  }, null, 2))
  await browser.close()
}

console.log(`\nRESULT: ${results.filter((r) => r.ok).length}/${results.length} checks passed, ${failures} failures`)
process.exit(failures === 0 ? 0 : 1)
