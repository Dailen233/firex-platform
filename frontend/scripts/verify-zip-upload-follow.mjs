// 端到端验收：向 run 上传单组 ZIP -> 后端自动重建并发布 -> 已打开页面跟随自动更新。
// 浏览器不刷新、不选文件；ZIP 通过 HTTP 上传。验证 33599 -> 43005，缺机位 ZIP 报错且保留第二帧。
import { chromium } from 'playwright'
import { execSync } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'

const FRONTEND = 'http://127.0.0.1:4174'
const BACKEND = 'http://127.0.0.1:8021'
const REPO = '/home/dailen/projects/firex-platform'
const RUN_ID = process.env.RUN_ID || ''
const OUT = process.env.EVIDENCE_DIR || 'evidence/zip-upload-follow'
mkdirSync(OUT, { recursive: true })

let plyRequests = 0
let glbRequests = 0

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
page.on('request', (r) => {
  const url = r.url()
  if (url.endsWith('/ply')) plyRequests++
  else if (url.endsWith('.glb')) glbRequests++
})

function curlUpload(name) {
  const t0 = Date.now()
  const out = execSync(
    `curl -s -X POST "${BACKEND}/api/v1/runs/${RUN_ID}/reconstruction-jobs" -F "file=@${REPO}/runtime-data/e2e-zip-upload/${name};type=application/zip"`,
    { encoding: 'utf8' },
  )
  return { job: JSON.parse(out), uploadMs: Date.now() - t0 }
}

function pollJob(jobId, timeoutMs = 180000) {
  const t0 = Date.now()
  while (Date.now() - t0 < timeoutMs) {
    const j = JSON.parse(execSync(`curl -s "${BACKEND}/api/v1/runs/${RUN_ID}/reconstruction-jobs/${jobId}"`, { encoding: 'utf8' }))
    if (j.status === 'completed' || j.status === 'failed') return { job: j, pollMs: Date.now() - t0 }
    execSync('sleep 1')
  }
  throw new Error(`job ${jobId} timeout`)
}

const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`) }
let failures = 0
const followInfo = () => page.locator('.follow-info').innerText().catch(() => '')

try {
  await page.goto(`${FRONTEND}/#/scene/sjk_hydropower_sim_v0_1?run_id=${RUN_ID}`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.viewer-toolbar', { timeout: 30000 })
  await page.waitForSelector('.loaded-status', { timeout: 30000 })
  await page.waitForTimeout(3000) // 等 run 连接 + 场景加载
  const glbAfterLoad = glbRequests
  check('scene-loaded', glbAfterLoad >= 1, `glb=${glbAfterLoad}`)

  // 开启跟随（1800s 已在验收前上传发布为 revision 1）
  await page.getByRole('button', { name: '开始跟随' }).click()
  await page.waitForTimeout(3000)
  const i1800 = await followInfo()
  check('follow-badge-rgb-proxy', await page.getByText('历史采集 · 颜色代理掩膜').first().isVisible().catch(() => false))
  check('follow-1800-33599', i1800.includes('33,599'), i1800.replace(/\s+/g, ' ').trim())
  check('ply-downloaded-once', plyRequests === 1, `ply=${plyRequests}`)
  await page.screenshot({ path: `${OUT}/follow-1800.png` })

  // 上传 3600s 单组 ZIP（浏览器不刷新，跟随自动更新）
  const up3600 = curlUpload('zip_3600.zip')
  check('upload-3600-202', up3600.job.status === 'queued', `upload ${up3600.uploadMs}ms`)
  const done3600 = pollJob(up3600.job.job_id)
  const reconMs = (Date.parse(done3600.job.finished_at) - Date.parse(done3600.job.started_at)) / 1000
  check('job-3600-completed', done3600.job.status === 'completed', `voxels=${done3600.job.voxel_count} revision=${done3600.job.revision} 重建=${reconMs.toFixed(2)}s`)
  check('job-3600-mask-rgb', done3600.job.mask_source === 'rgb_proxy')

  // 等待跟随轮询并检测 43,005（记录上传到网页可见耗时）
  const tUploadDone = Date.now()
  let seen3600 = false
  let visibleMs = 0
  for (let i = 0; i < 40 && !seen3600; i++) {
    await page.waitForTimeout(500)
    const info = await followInfo()
    if (info.includes('43,005')) { seen3600 = true; visibleMs = Date.now() - tUploadDone }
  }
  check('follow-3600-43005', seen3600, `上传到可见 ${visibleMs}ms`)
  check('ply-redownloaded-new-revision', plyRequests === 2, `ply=${plyRequests}`)
  check('glb-not-reloaded', glbRequests === glbAfterLoad, `glb=${glbRequests}`)
  await page.screenshot({ path: `${OUT}/follow-3600.png` })

  // 上传缺机位 ZIP -> 任务报错，页面保留第二帧
  const upBad = curlUpload('zip_bad.zip')
  check('upload-bad-202', upBad.job.status === 'queued')
  const doneBad = pollJob(upBad.job.job_id)
  check('job-bad-failed', doneBad.job.status === 'failed', (doneBad.job.error || '').slice(0, 120))
  check('job-bad-error-reason', /expected 2\+1 or 3\+1/.test(doneBad.job.error || ''))

  await page.waitForTimeout(3000)
  const afterBad = await followInfo()
  check('bad-frame-not-overwrite', afterBad.includes('43,005'), afterBad.replace(/\s+/g, ' ').trim())
  check('ply-not-redownloaded-on-fail', plyRequests === 2, `ply=${plyRequests}`)
  await page.screenshot({ path: `${OUT}/follow-after-bad.png` })
} catch (e) {
  failures++
  console.error('FATAL:', e instanceof Error ? e.message : String(e))
  await page.screenshot({ path: `${OUT}/error.png` }).catch(() => {})
} finally {
  const appFail = results.filter((r) => !r.ok).length
  failures += appFail
  writeFileSync(`${OUT}/result.json`, JSON.stringify({ run_id: RUN_ID, checks: results, ply_requests: plyRequests, glb_requests: glbRequests, exit_status: failures === 0 ? 0 : 1 }, null, 2))
  await browser.close()
}
console.log(`\nRESULT: ${results.length - results.filter((r) => !r.ok).length}/${results.length} checks passed`)
process.exit(failures === 0 ? 0 : 1)
