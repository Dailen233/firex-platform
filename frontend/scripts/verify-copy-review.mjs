// 前端文案优化复核：地图首页（无数据状态）→ 电厂详情 → 三维场景。
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'

const FRONTEND = process.env.FIREX_FRONTEND || 'http://127.0.0.1:4173'
const OUT = process.env.EVIDENCE_DIR || 'evidence/copy-review'
mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1400, height: 950 } })
const errors = []
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
page.on('pageerror', (e) => errors.push(String(e)))

try {
  // 1) 地图首页（当前后端 no_observation → 无数据/等待数据状态）
  await page.goto(`${FRONTEND}/#/atlas`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.map-bottomline', { timeout: 20000 })
  await page.waitForTimeout(1200)
  const bottomline = (await page.locator('.map-bottomline').innerText()).replace(/\s+/g, ' ')
  console.log('[地图] bottomline:', bottomline)
  const sectionHeading = (await page.locator('.fire-feedback .section-heading').innerText()).replace(/\s+/g, ' ')
  console.log('[地图] 火情反馈说明:', sectionHeading)
  await page.screenshot({ path: `${OUT}/1-atlas-home.png`, fullPage: true })

  // 2) 电厂详情（织金 GEM_COAL_ZHIJIN）
  await page.goto(`${FRONTEND}/#/atlas?plant=GEM_COAL_ZHIJIN`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.plant-detail', { timeout: 15000 })
  await page.waitForTimeout(600)
  const detailFacts = (await page.locator('.plant-detail .facts').first().innerText()).replace(/\s+/g, ' ')
  console.log('[详情] 火情状态:', detailFacts)
  await page.screenshot({ path: `${OUT}/2-plant-detail.png`, fullPage: true })

  // 3) 三维场景（织金 zhijin_pilot，验证「当前场景暂不支持显示火区」）
  await page.getByRole('link', { name: /进入三维场景/ }).click()
  await page.waitForSelector('.demo-panel', { timeout: 20000 })
  await page.waitForTimeout(1500)
  const demoPanel = (await page.locator('.demo-panel').innerText()).replace(/\s+/g, ' ')
  console.log('[三维] demo-panel:', demoPanel)
  const badges = (await page.locator('.viewer-badges').innerText()).replace(/\s+/g, ' ')
  console.log('[三维] viewer-badges:', badges)
  await page.screenshot({ path: `${OUT}/3-zhijin-scene.png`, fullPage: true })

  console.log('console/page errors:', errors.length)
  if (errors.length) console.log(errors.join('\n'))
} catch (e) {
  console.error('FATAL:', e instanceof Error ? e.message : String(e))
  await page.screenshot({ path: `${OUT}/error.png`, fullPage: true }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
