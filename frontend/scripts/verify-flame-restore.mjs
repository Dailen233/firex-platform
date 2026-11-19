// 补测：跟随服务端期间隐藏实时单视角火焰剖面，退出后恢复。
// 用「橙色火焰像素计数」判定火焰网格的显示/隐藏/恢复（渲染抖动不影响判定）。
import { chromium } from 'playwright'
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs'

const FRONTEND = 'http://127.0.0.1:4175'
const RUN_ID = process.env.RUN_ID || ''
const OUT = process.env.EVIDENCE_DIR || 'evidence/flame-restore'
mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`) }
let failures = 0

// 统计截图中的橙色火焰像素数（火焰剖面为大片橙色；UI 徽标占比极小）。
async function countOrange(pngPath) {
  const b64 = readFileSync(pngPath).toString('base64')
  return page.evaluate(async (src) => {
    const img = new Image()
    img.src = `data:image/png;base64,${src}`
    await new Promise((res, rej) => { img.onload = res; img.onerror = rej })
    const canvas = document.createElement('canvas')
    canvas.width = img.width
    canvas.height = img.height
    const ctx = canvas.getContext('2d')
    ctx.drawImage(img, 0, 0)
    const data = ctx.getImageData(0, 0, img.width, img.height).data
    let count = 0
    for (let i = 0; i < data.length; i += 4) {
      const r = data[i], g = data[i + 1], b = data[i + 2]
      if (r > 180 && g > 60 && g < 200 && b < 100 && r - b > 80) count++
    }
    return count
  }, b64)
}

try {
  await page.goto(`${FRONTEND}/#/scene/sjk_hydropower_sim_v0_1?run_id=${RUN_ID}`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.viewer-toolbar', { timeout: 30000 })
  await page.waitForSelector('.loaded-status', { timeout: 30000 })
  await page.waitForTimeout(3500) // 等火焰观测 + 剖面加载与自动聚焦

  check('flame-badge-visible', await page.getByText('单视角火焰剖面').first().isVisible().catch(() => false))
  await page.getByRole('button', { name: '聚焦火焰' }).click().catch(() => {})
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${OUT}/fire-on.png` })
  const on = await countOrange(`${OUT}/fire-on.png`)
  check('flame-shown-before-follow', on > 2000, `橙色像素=${on}`)

  // 开启跟随（该 run 无重建结果，但 followActive 应隐藏火焰剖面）
  await page.getByRole('button', { name: '开始跟随' }).click()
  await page.waitForTimeout(1500)
  check('follow-active-state', await page.getByRole('button', { name: '停止跟随' }).isVisible().catch(() => false))
  await page.screenshot({ path: `${OUT}/fire-off.png` })
  const off = await countOrange(`${OUT}/fire-off.png`)
  check('flame-hidden-during-follow', off < on * 0.3, `橙色像素=${off}（跟随前 ${on}）`)

  // 退出跟随
  await page.getByRole('button', { name: '停止跟随' }).click()
  await page.waitForTimeout(1500)
  await page.screenshot({ path: `${OUT}/fire-back.png` })
  const back = await countOrange(`${OUT}/fire-back.png`)
  check('flame-restored-after-exit', back > 2000 && back > on * 0.5, `橙色像素=${back}（跟随前 ${on}）`)
} catch (e) {
  failures++
  console.error('FATAL:', e instanceof Error ? e.message : String(e))
  await page.screenshot({ path: `${OUT}/error.png` }).catch(() => {})
} finally {
  const appFail = results.filter((r) => !r.ok).length
  failures += appFail
  writeFileSync(`${OUT}/result.json`, JSON.stringify({ run_id: RUN_ID, checks: results, exit_status: failures === 0 ? 0 : 1 }, null, 2))
  await browser.close()
}
console.log(`\nRESULT: ${results.length - results.filter((r) => !r.ok).length}/${results.length} checks passed`)
process.exit(failures === 0 ? 0 : 1)
