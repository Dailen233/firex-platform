// 端到端验收：新 run（无重建结果）-> 从网页依次上传 1800s/3600s 单组 ZIP ->
// 自动重建并显示 33,599 -> 43,005；缺机位包显示失败原因且保留第二帧。
// 全程不用 curl 提交，用 page.setInputFiles 网页上传；用浏览器时钟计时。
import { chromium } from 'playwright'
import { mkdirSync, writeFileSync } from 'node:fs'

const FRONTEND = 'http://127.0.0.1:4174'
const BACKEND = 'http://127.0.0.1:8021'
const REPO = '/home/dailen/projects/firex-platform'
const ZIP_DIR = `${REPO}/runtime-data/e2e-zip-upload`
const OUT = process.env.EVIDENCE_DIR || 'evidence/upload-ui'
mkdirSync(OUT, { recursive: true })

const RUN_ID = process.env.RUN_ID || ''
if (!RUN_ID) throw new Error('RUN_ID 未设置')

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })

const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`) }
let failures = 0

// 捕获上传返回的 job_id（网页上传，非 curl）。
let capturedJob = null
page.on('response', async (res) => {
  if (res.request().method() === 'POST' && res.url().includes('/reconstruction-jobs')) {
    try { const b = await res.json(); if (b && b.job_id) capturedJob = b } catch {}
  }
})

async function fetchJob(jobId) {
  const res = await fetch(`${BACKEND}/api/v1/runs/${RUN_ID}/reconstruction-jobs/${jobId}`)
  return res.json()
}

const browserNow = () => page.evaluate(() => Date.now())

// 上传一个 ZIP（网页），等待「已显示 revision N」且 follow-info 显示对应体素数。
async function uploadAndWait(zipName, revision, voxelText, timeoutMs = 180000) {
  capturedJob = null
  const t0 = await browserNow()
  await page.setInputFiles('input[type="file"][accept=".zip"]', `${ZIP_DIR}/${zipName}`)
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const done = await page.locator('.upload-status .done').innerText().catch(() => '')
    const info = await page.locator('.follow-info').innerText().catch(() => '')
    if (done.includes(`revision ${revision}`) && info.includes(voxelText)) {
      const t1 = await browserNow()
      return { e2eMs: t1 - t0, job: capturedJob }
    }
    await page.waitForTimeout(250)
  }
  throw new Error(`上传 ${zipName} 后未在 ${timeoutMs}ms 内显示 revision ${revision} ${voxelText}`)
}

try {
  await page.goto(`${FRONTEND}/#/scene/sjk_hydropower_sim_v0_1?run_id=${RUN_ID}`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.viewer-toolbar', { timeout: 30000 })
  await page.waitForSelector('.loaded-status', { timeout: 30000 })
  await page.waitForTimeout(3000)
  check('scene-loaded-and-run-connected', true)

  // 先开启跟随，确认初始为「暂无重建结果」。
  await page.getByRole('button', { name: '开始跟随' }).click()
  await page.waitForTimeout(2500)
  const err0 = await page.locator('.follow-error').innerText().catch(() => '')
  check('initial-no-result', err0.includes('暂无重建结果'), err0)

  // 上传 1800s。
  const r1 = await uploadAndWait('zip_1800.zip', 1, '33,599')
  check('upload-1800-shows-33599', true, `端到端 ${r1.e2eMs}ms`)
  const job1 = r1.job ? await fetchJob(r1.job.job_id) : null
  if (job1) {
    const calcMs = (Date.parse(job1.finished_at) - Date.parse(job1.started_at)) / 1000
    check('job-1800-completed', job1.status === 'completed', `revision=${job1.revision} voxels=${job1.voxel_count} mask=${job1.mask_source} 后端计算=${calcMs.toFixed(2)}s`)
  } else {
    check('job-1800-completed', false, '未捕获 job_id')
  }
  await page.screenshot({ path: `${OUT}/1800.png` })

  // 上传 3600s。
  const r2 = await uploadAndWait('zip_3600.zip', 2, '43,005')
  check('upload-3600-shows-43005', true, `端到端 ${r2.e2eMs}ms`)
  const job2 = r2.job ? await fetchJob(r2.job.job_id) : null
  if (job2) {
    const calcMs = (Date.parse(job2.finished_at) - Date.parse(job2.started_at)) / 1000
    check('job-3600-completed', job2.status === 'completed', `revision=${job2.revision} voxels=${job2.voxel_count} mask=${job2.mask_source} 后端计算=${calcMs.toFixed(2)}s`)
  } else {
    check('job-3600-completed', false, '未捕获 job_id')
  }
  await page.screenshot({ path: `${OUT}/3600.png` })

  // 上传缺机位包 -> 页面显示失败原因，保留 43,005。
  capturedJob = null
  await page.setInputFiles('input[type="file"][accept=".zip"]', `${ZIP_DIR}/zip_bad.zip`)
  let failReason = ''
  const failDeadline = Date.now() + 60000
  while (Date.now() < failDeadline) {
    failReason = await page.locator('.upload-error').innerText().catch(() => '')
    if (failReason) break
    await page.waitForTimeout(250)
  }
  check('bad-shows-failure-reason', /expected 2\+1 or 3\+1/.test(failReason), failReason.slice(0, 120))
  const infoAfter = await page.locator('.follow-info').innerText().catch(() => '')
  check('bad-frame-not-overwrite', infoAfter.includes('43,005'), infoAfter.replace(/\s+/g, ' ').trim())
  await page.screenshot({ path: `${OUT}/after-bad.png` })

  // 汇总计时
  writeFileSync(`${OUT}/timing.json`, JSON.stringify({
    run_id: RUN_ID,
    '1800_e2e_ms': r1.e2eMs, '1800_backend_calc_s': job1 ? (Date.parse(job1.finished_at) - Date.parse(job1.started_at)) / 1000 : null,
    '3600_e2e_ms': r2.e2eMs, '3600_backend_calc_s': job2 ? (Date.parse(job2.finished_at) - Date.parse(job2.started_at)) / 1000 : null,
  }, null, 2))
} catch (e) {
  failures++
  console.error('FATAL:', e instanceof Error ? e.message : String(e))
  await page.screenshot({ path: `${OUT}/error.png` }).catch(() => {})
} finally {
  failures += results.filter((r) => !r.ok).length
  writeFileSync(`${OUT}/result.json`, JSON.stringify({ run_id: RUN_ID, checks: results, exit_status: failures === 0 ? 0 : 1 }, null, 2))
  await browser.close()
}
console.log(`\nRESULT: ${results.length - results.filter((r) => !r.ok).length}/${results.length} checks passed`)
process.exit(failures === 0 ? 0 : 1)
