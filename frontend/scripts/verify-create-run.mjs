// 端到端验收：从无 run_id 的三维页新建重建运行 -> 网页上传 -> revision 1/33,599；
// 刷新回到同一次运行；再新建第二个运行历史为空；原链接仍能打开第一帧。
// 全程不用终端创建 run。
import { chromium } from 'playwright'
import { mkdirSync, writeFileSync } from 'node:fs'

const FRONTEND = 'http://127.0.0.1:4174'
const REPO = '/home/dailen/projects/firex-platform'
const ZIP = `${REPO}/runtime-data/e2e-zip-upload/zip_1800.zip`
const OUT = process.env.EVIDENCE_DIR || 'evidence/create-run'
mkdirSync(OUT, { recursive: true })

const SCENE_URL = `${FRONTEND}/#/scene/sjk_hydropower_sim_v0_1`

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })

const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`) }
let failures = 0

// run_id 在 hash 路由的 query 里（#/scene/x?run_id=…），需从 hash 解析。
const urlRunId = () => page.evaluate(() => {
  const hash = location.hash
  const idx = hash.indexOf('?')
  if (idx < 0) return ''
  return new URLSearchParams(hash.slice(idx + 1)).get('run_id') || ''
})
const followInfo = () => page.locator('.follow-info').innerText().catch(() => '')

async function waitLoaded() {
  await page.waitForSelector('.viewer-toolbar', { timeout: 30000 })
  await page.waitForSelector('.loaded-status', { timeout: 30000 })
  await page.waitForTimeout(2500)
}

async function startFollow() {
  await page.getByRole('button', { name: '开始跟随' }).click()
  await page.waitForTimeout(2500)
}

try {
  // 1. 从无 run_id 开始
  await page.goto(SCENE_URL, { waitUntil: 'domcontentloaded' })
  await waitLoaded()
  check('start-without-run-id', (await urlRunId()) === '', await page.url())

  // 2. 点击新建 -> URL 带 run_id 并自动连接
  await page.getByRole('button', { name: '新建重建运行' }).click()
  await page.waitForFunction(() => {
    const h = location.hash
    const i = h.indexOf('?')
    return i >= 0 ? new URLSearchParams(h.slice(i + 1)).get('run_id') : null
  }, null, { timeout: 10000 })
  const run1 = await urlRunId()
  check('create-writes-run-id', run1.length > 0, run1)
  await page.waitForTimeout(2000)
  // 连接详情在折叠的 <details> 里，用 textContent 检查连接状态。
  const detailText = await page.locator('.connection-details').textContent().catch(() => '')
  check('auto-connected', (detailText || '').includes('已连接'), (detailText || '').slice(0, 60))

  // 3. 网页上传 zip_1800 -> revision 1 / 33,599
  await page.setInputFiles('input[type="file"][accept=".zip"]', ZIP)
  let seen33599 = false
  let info1 = ''
  for (let i = 0; i < 120 && !seen33599; i++) {
    await page.waitForTimeout(500)
    info1 = await followInfo()
    if (info1.includes('33,599')) seen33599 = true
  }
  check('upload-shows-revision1-33599', seen33599, info1.replace(/\s+/g, ' ').trim())
  await page.screenshot({ path: `${OUT}/run1-33599.png` })

  // 4. 刷新 -> 同一次运行仍能看到结果
  await page.reload({ waitUntil: 'domcontentloaded' })
  await waitLoaded()
  check('reload-keeps-run-id', (await urlRunId()) === run1, await page.url())
  await startFollow()
  const infoReload = await followInfo()
  check('reload-still-33599', infoReload.includes('33,599'), infoReload.replace(/\s+/g, ' ').trim())
  await page.screenshot({ path: `${OUT}/reload-run1.png` })

  // 5. 新建第二个运行 -> 历史为空
  await page.getByRole('button', { name: '新建重建运行' }).click()
  await page.waitForFunction((prev) => {
    const h = location.hash
    const i = h.indexOf('?')
    const id = i >= 0 ? new URLSearchParams(h.slice(i + 1)).get('run_id') : null
    return id && id !== prev
  }, run1, { timeout: 10000 })
  const run2 = await urlRunId()
  check('second-run-new-id', run2.length > 0 && run2 !== run1, run2)
  await page.waitForTimeout(2000)
  await startFollow()
  const err2 = await page.locator('.follow-error').innerText().catch(() => '')
  const histBlock = await page.locator('.history-block').count()
  check('second-run-empty-history', err2.includes('暂无重建结果') && histBlock === 0, `err="${err2}" history=${histBlock}`)
  await page.screenshot({ path: `${OUT}/run2-empty.png` })

  // 6. 原链接打开第一帧
  await page.goto(`${SCENE_URL}?run_id=${run1}`, { waitUntil: 'domcontentloaded' })
  await waitLoaded()
  await startFollow()
  const infoOld = await followInfo()
  check('old-link-shows-run1-33599', infoOld.includes('33,599'), infoOld.replace(/\s+/g, ' ').trim())
  await page.screenshot({ path: `${OUT}/old-link-run1.png` })
} catch (e) {
  failures++
  console.error('FATAL:', e instanceof Error ? e.message : String(e))
  await page.screenshot({ path: `${OUT}/error.png` }).catch(() => {})
} finally {
  failures += results.filter((r) => !r.ok).length
  writeFileSync(`${OUT}/result.json`, JSON.stringify({ checks: results, run1: await urlRunId().catch(() => ''), exit_status: failures === 0 ? 0 : 1 }, null, 2))
  await browser.close()
}
console.log(`\nRESULT: ${results.length - results.filter((r) => !r.ok).length}/${results.length} checks passed`)
process.exit(failures === 0 ? 0 : 1)
