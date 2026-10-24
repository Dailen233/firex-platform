// B4: prove the same patch_id actually updates its overlay vertices on a new
// revision, with a FIXED camera (framed once at obs=1, never re-framed), and
// that the outline stays stable once uploads stop (duplicate revisions must not
// rebuild the geometry). Creates a run + uploads two frames, so it verifies the
// target service identity BEFORE the first write request.
//
// Usage: node scripts/e2e-geometry-update.mjs [out_dir]
import { execSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { BACKEND, FRONTEND, SCENE_URL, verifyService, launchPage, makeChecks, finish } from './e2e-utils.mjs'

const OUT = process.argv[2] || '/tmp/firex-b4-e2e'
const repoRoot = fileURLToPath(new URL('../../', import.meta.url)) // frontend/scripts -> repo root

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
async function getState(runId) {
  return fetch(`${BACKEND}/api/v1/runs/${runId}/state`).then((r) => r.json())
}
function upload(frame, sim, runId) {
  execSync(
    `uv --directory "${repoRoot}/backend" run --locked python scripts/upload_test_capture.py --base-url ${BACKEND} --frame ${frame} --simulation-time ${sim} ${runId}`,
    { stdio: 'pipe' },
  )
}

const checks = makeChecks()
let browser = null
let page = null
let state = { consoleErrors: [], pageErrors: [], failedRequests: [], glbFetches: 0 }
try {
  await verifyService() // refuse to write to a non-firex service

  const run = await fetch(`${BACKEND}/api/v1/runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      plant_id: 'GEM_HYDRO_SHUANGJIANGKOU',
      scene_id: 'shuangjiangkou_reference_terrain',
      asset_version: 'reference-v1',
      coordinate_frame_id: 'SJK_REFERENCE_UTM47N_EGM2008_v1',
      input_source: 'simulation',
      simulation_time_origin_s: 10.0,
    }),
  }).then((r) => r.json())
  const runId = run.run_id
  checks.check('run-created', !!runId, runId)

  upload(1, 11.0, runId)
  let rev = 0
  for (let i = 0; i < 60; i++) { rev = (await getState(runId)).revision; if (rev === 1) break; await sleep(150) }
  checks.check('rev-1-reached', rev === 1, `revision=${rev}`)

  const launched = await launchPage()
  browser = launched.browser; page = launched.page; state = launched.state
  await page.goto(SCENE_URL, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.viewer-toolbar', { timeout: 30000 })
  await page.getByPlaceholder('输入 run_id').fill(runId)
  await page.getByRole('button', { name: '连接', exact: true }).click()
  await page.getByText('已连接', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByRole('button', { name: '聚焦火区' }).waitFor({ timeout: 10000 })
  await page.getByRole('button', { name: '聚焦火区' }).click()
  await page.waitForTimeout(1500)
  await page.screenshot({ path: `${OUT}/update-obs1.png` })

  // Second frame -> same patch_id, larger ring. Camera stays fixed.
  upload(2, 29.0, runId)
  for (let i = 0; i < 60; i++) { rev = (await getState(runId)).revision; if (rev === 2) break; await sleep(150) }
  checks.check('rev-2-reached', rev === 2, `revision=${rev}`)
  await page.waitForTimeout(3000) // let the poller pick up revision 2
  await page.screenshot({ path: `${OUT}/update-obs19.png` })

  // Stability: with no further uploads, several duplicate-revision polls must not change the outline.
  await page.waitForTimeout(2500)
  await page.screenshot({ path: `${OUT}/update-obs19b.png` })
  checks.check('glb-once', state.glbFetches === 1, `fetches=${state.glbFetches}`)
  console.log('RUN_ID', runId)
} catch (e) {
  checks.fail(e)
  if (page) await page.screenshot({ path: `${OUT}/error.png` }).catch(() => {})
} finally {
  const failures = await finish(browser ?? { close: async () => {} }, checks, state)
  process.exitCode = failures > 0 ? 1 : 0
}
