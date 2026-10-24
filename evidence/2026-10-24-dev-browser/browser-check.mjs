import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'

const BASE = 'http://localhost:4173'
const OUT = '/home/dailen/projects/firex-platform/evidence/2026-10-24-dev-browser'
mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({
  channel: 'chrome',
  headless: true,
  args: ['--enable-unsafe-swiftshader', '--use-gl=angle', '--use-angle=swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })

const consoleErrors = []
const failedRequests = []
page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()) })
page.on('requestfailed', (r) => failedRequests.push(`FAILED ${r.method()} ${r.url()} :: ${r.failure()?.errorText}`))
page.on('response', (r) => { if (r.status() >= 400) failedRequests.push(`HTTP ${r.status()} ${r.url()}`) })

const log = (...a) => console.log(...a)
const shot = (name) => page.screenshot({ path: `${OUT}/${name}.png`, fullPage: false })

async function webglOk() {
  return page.evaluate(() => {
    const c = document.querySelector('canvas')
    if (!c || c.width < 2 || c.height < 2) return { ok: false, reason: 'no canvas or zero-size' }
    const gl = c.getContext('webgl2') || c.getContext('webgl')
    return gl ? { ok: true, size: `${c.width}x${c.height}` } : { ok: false, reason: 'no webgl context' }
  })
}

async function interact(label) {
  const c = page.locator('canvas').first()
  const box = await c.boundingBox()
  if (!box) { log(`  ${label} interact: no canvas box`); return }
  const cx = box.x + box.width / 2, cy = box.y + box.height / 2
  await page.mouse.move(cx, cy)
  await page.mouse.down()
  await page.mouse.move(cx + 130, cy + 45, { steps: 12 })
  await page.mouse.up()
  await page.mouse.wheel(0, -500) // zoom in
  await page.waitForTimeout(900)
  log(`  ${label} interact (rotate+zoom) done, webgl still:`, JSON.stringify(await webglOk()))
}

try {
  // 1. atlas
  log('--- 1. atlas ---')
  await page.goto(`${BASE}/#/atlas`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(2500)
  const plantCount = await page.locator('.plant-item').count()
  log('plant items:', plantCount)
  log('title:', await page.title())
  await shot('01-atlas')

  // 2. 织金 detail
  log('--- 2. zhijin detail ---')
  await page.locator('.plant-item', { hasText: '国能织金电厂' }).first().click()
  await page.waitForTimeout(800)
  const hasEnterScene = await page.getByText('进入三维场景').count()
  log('织金 detail shows 进入三维场景:', hasEnterScene > 0)
  await shot('02-zhijin-detail')

  // 3. 织金 scene
  log('--- 3. zhijin scene ---')
  await page.getByText('进入三维场景').first().click()
  await page.waitForTimeout(1500)
  await page.waitForSelector('canvas', { timeout: 30000 })
  // wait for loader to disappear (model loaded)
  await page.waitForSelector('[role="status"]', { state: 'detached', timeout: 60000 }).catch(() => {})
  await page.waitForTimeout(2000)
  log('zhijin webgl:', JSON.stringify(await webglOk()))
  log('zhijin scene h1:', await page.locator('header h1').first().innerText().catch(() => '(none)'))
  await shot('03-zhijin-scene')
  await interact('zhijin')

  // 4. back to detail / atlas
  log('--- 4. back ---')
  await page.getByText('返回电厂详情').first().click()
  await page.waitForTimeout(800)
  log('back to atlas/detail, plant items (filtered):', await page.locator('.plant-item').count())

  // 4b. reset to national view
  await page.goto(`${BASE}/#/atlas`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(2000)
  log('reset to national, plant items:', await page.locator('.plant-item').count())

  // 5. 双江口 detail
  log('--- 5. shuangjiangkou detail ---')
  await page.locator('.plant-item', { hasText: '双江口水电站' }).first().click()
  await page.waitForTimeout(800)
  const hasReference = await page.getByText('浏览山地参考底座').count()
  log('双江口 detail shows 浏览山地参考底座:', hasReference > 0)
  await shot('05-shuangjiangkou-detail')

  // 6. 双江口 reference scene
  log('--- 6. shuangjiangkou reference scene ---')
  await page.getByText('浏览山地参考底座').first().click()
  await page.waitForTimeout(1500)
  await page.waitForSelector('canvas', { timeout: 30000 })
  await page.waitForSelector('[role="status"]', { state: 'detached', timeout: 60000 }).catch(() => {})
  await page.waitForTimeout(2000)
  log('shuangjiangkou webgl:', JSON.stringify(await webglOk()))
  log('shuangjiangkou scene h1:', await page.locator('header h1').first().innerText().catch(() => '(none)'))
  await shot('06-shuangjiangkou-scene')
  await interact('shuangjiangkou')

  // 7. back
  await page.getByText('返回电厂详情').first().click()
  await page.waitForTimeout(800)
  log('back ok')
} catch (e) {
  log('SCRIPT ERROR:', e.message)
  await shot('99-error')
}

log('--- console errors ---')
consoleErrors.length ? consoleErrors.forEach((e) => log('  [console.error]', e)) : log('  (none)')
log('--- failed requests / HTTP >= 400 ---')
failedRequests.length ? failedRequests.forEach((r) => log('  ', r)) : log('  (none)')

await browser.close()
