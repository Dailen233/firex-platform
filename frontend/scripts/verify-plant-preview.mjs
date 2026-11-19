// 端到端验收：厂区近景预览层。
// 固定斜视/俯视各一组改前改后对比，复查两帧火焰体素与塔线在预览层开关下仍显示。
import { chromium } from 'playwright'
import { mkdirSync, writeFileSync } from 'node:fs'

const FRONTEND = 'http://127.0.0.1:4174'
const OUT = process.env.EVIDENCE_DIR || 'evidence/plant-preview'
mkdirSync(OUT, { recursive: true })
const RUN_ID = process.env.RUN_ID || '144923cf-0983-4f3c-a15d-77cb79f917df'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })

const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`) }
let failures = 0

const followInfo = () => page.locator('.follow-info').innerText().catch(() => '')
const shot = (name) => page.screenshot({ path: `${OUT}/${name}.png` })

try {
  await page.goto(`${FRONTEND}/#/scene/sjk_hydropower_sim_v0_1?run_id=${RUN_ID}`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.viewer-toolbar', { timeout: 30000 })
  await page.waitForSelector('.loaded-status', { timeout: 30000 })
  await page.waitForTimeout(3000)

  // 开启跟随 -> 最新 3600s / 43,005
  await page.getByRole('button', { name: '开始跟随' }).click()
  await page.waitForTimeout(2500)
  const i3600 = await followInfo()
  check('follow-shows-43005', i3600.includes('43,005'), i3600.replace(/\s+/g, ' ').trim())

  // 显示塔线
  await page.getByRole('button', { name: '显示仿真塔线' }).click()
  await page.waitForTimeout(800)
  check('grid-visible', await page.getByRole('button', { name: '隐藏仿真塔线' }).isVisible().catch(() => false))

  // 复查：预览层关闭时，体素 + 塔线基线
  await shot('00-voxels-grid-baseline')

  // 斜视对比（关闭预览层）
  await page.getByRole('button', { name: '斜视' }).click()
  await page.waitForTimeout(600)
  await shot('10-before-oblique')
  // 开启预览层
  await page.getByRole('button', { name: '开启预览层' }).click()
  await page.waitForTimeout(600)
  check('preview-label-shown', await page.getByText('参考公开资料的仿真布局', { exact: false }).first().isVisible().catch(() => false))
  await page.getByRole('button', { name: '斜视' }).click()
  await page.waitForTimeout(600)
  await shot('11-after-oblique')

  // 俯视对比
  await page.getByRole('button', { name: '关闭预览层' }).click()
  await page.waitForTimeout(600)
  await page.getByRole('button', { name: '俯视' }).click()
  await page.waitForTimeout(600)
  await shot('20-before-top')
  await page.getByRole('button', { name: '开启预览层' }).click()
  await page.waitForTimeout(600)
  await page.getByRole('button', { name: '俯视' }).click()
  await page.waitForTimeout(600)
  await shot('21-after-top')

  // 复查：预览层开启时，体素 + 塔线仍显示
  const iStill = await followInfo()
  check('voxels-still-shown-with-preview', iStill.includes('43,005'), iStill.replace(/\s+/g, ' ').trim())
  check('grid-still-shown-with-preview', await page.getByRole('button', { name: '隐藏仿真塔线' }).isVisible().catch(() => false))
  await shot('30-preview-with-voxels-grid')

  // 历史两帧切换（复查两帧体素）
  await page.locator('.history-item', { hasText: '1800' }).click()
  await page.waitForTimeout(1200)
  const i1800 = await followInfo()
  check('history-frame-1800-33599', i1800.includes('33,599'), i1800.replace(/\s+/g, ' ').trim())
  await page.getByRole('button', { name: '回到最新' }).click()
  await page.waitForTimeout(1500)
  const iBack = await followInfo()
  check('back-to-3600-43005', iBack.includes('43,005'), iBack.replace(/\s+/g, ' ').trim())

  // 关闭预览层 -> 恢复原场景（主厂房/主变重新可见，预览层标注消失）
  await page.getByRole('button', { name: '关闭预览层' }).click()
  await page.waitForTimeout(600)
  check('preview-closed-restores', await page.getByRole('button', { name: '开启预览层' }).isVisible().catch(() => false))
  await shot('40-after-close')
} catch (e) {
  failures++
  console.error('FATAL:', e instanceof Error ? e.message : String(e))
  await shot('error').catch(() => {})
} finally {
  failures += results.filter((r) => !r.ok).length
  writeFileSync(`${OUT}/result.json`, JSON.stringify({ run_id: RUN_ID, checks: results, exit_status: failures === 0 ? 0 : 1 }, null, 2))
  await browser.close()
}
console.log(`\nRESULT: ${results.length - results.filter((r) => !r.ok).length}/${results.length} checks passed`)
process.exit(failures === 0 ? 0 : 1)
