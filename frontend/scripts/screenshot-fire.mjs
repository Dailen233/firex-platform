// Capture a 3D screenshot of the fire overlay for a connected run.
// Usage: node scripts/screenshot-fire.mjs <run_id> <out.png> [base]
import { chromium } from 'playwright'

const RUN_ID = process.argv[2]
const OUT = process.argv[3]
const BASE = process.argv[4] || 'http://127.0.0.1:4173'
if (!RUN_ID || !OUT) {
  console.error('usage: node scripts/screenshot-fire.mjs <run_id> <out.png> [base]')
  process.exit(2)
}

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
try {
  await page.goto(`${BASE}/#/scene/shuangjiangkou_reference_terrain`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.viewer-toolbar', { timeout: 30000 })
  await page.getByPlaceholder('输入 run_id').fill(RUN_ID)
  await page.getByRole('button', { name: '连接', exact: true }).click()
  await page.getByText('已连接', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByRole('button', { name: '聚焦火区' }).waitFor({ timeout: 10000 })
  await page.getByRole('button', { name: '聚焦火区' }).click()
  await page.waitForTimeout(1200)
  await page.screenshot({ path: OUT })
  console.log('saved', OUT)
} finally {
  await browser.close()
}
