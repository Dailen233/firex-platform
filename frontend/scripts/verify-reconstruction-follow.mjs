// 端到端验收：跟随服务端重建结果。
// 浏览器保持打开、不选文件、不刷新，验证点数 33,599 -> 43,005 自动切换，
// 重复 revision 不重复下载 PLY、GLB 不重载，旧帧/损坏文件不覆盖有效结果。
import { chromium } from 'playwright'
import { execSync } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'

const FRONTEND = process.env.FIREX_FRONTEND || 'http://127.0.0.1:4174'
const REPO = '/home/dailen/projects/firex-platform'
const DATA_DIR = `${REPO}/runtime-data/e2e-reconstruction-follow`
const RESULTS_DIR = `${REPO}/runtime-data/sjk-local-ab.gIen7N/terrain-clip`
const RUN_ID = process.env.RUN_ID || ''
const OUT = process.env.EVIDENCE_DIR || 'evidence/reconstruction-follow'
mkdirSync(OUT, { recursive: true })

let plyRequests = 0
let glbRequests = 0
let summaryRequests = 0

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
page.on('request', (r) => {
  const url = r.url()
  if (url.endsWith('/ply')) plyRequests++
  else if (url.endsWith('.glb')) glbRequests++
  else if (url.includes('/reconstruction')) summaryRequests++
})

function publish(groupId, resultsDir = RESULTS_DIR) {
  try {
    const out = execSync(
      `cd ${REPO}/backend && .venv/bin/python scripts/publish_reconstruction.py --run-id ${RUN_ID} --results-dir ${resultsDir} --group-id ${groupId} --data-dir ${DATA_DIR}`,
      { encoding: 'utf8' },
    )
    return { ok: true, out: out.trim() }
  } catch (e) {
    return { ok: false, out: (e.stderr || e.stdout || String(e)).trim() }
  }
}

function writeBadPly(count) {
  const header = `ply\nformat binary_little_endian 1.0\nelement vertex ${count}\nproperty float x\nproperty float y\nproperty float z\nend_header\n`
  const body = Buffer.alloc(count * 12)
  return Buffer.concat([Buffer.from(header, 'ascii'), body])
}

const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`) }
let failures = 0
const followInfo = () => page.locator('.follow-info').innerText().catch(() => '')

try {
  await page.goto(`${FRONTEND}/#/scene/sjk_hydropower_sim_v0_1?run_id=${RUN_ID}`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.viewer-toolbar', { timeout: 30000 })
  await page.waitForSelector('.loaded-status', { timeout: 30000 })
  await page.waitForTimeout(3000) // 等 run 连接 + 场景加载完成
  const glbAfterLoad = glbRequests
  check('scene-loaded-with-glb', glbAfterLoad >= 1, `glb requests=${glbAfterLoad}`)
  check('follow-button-present', await page.getByRole('button', { name: '开始跟随' }).isVisible().catch(() => false))

  // 开启跟随（1800s 已在验收前发布为 revision 1）
  await page.getByRole('button', { name: '开始跟随' }).click()
  await page.waitForTimeout(3000)
  const i1800 = await followInfo()
  check('follow-badge-historical', await page.getByText('历史采集 · 候选体素').first().isVisible().catch(() => false))
  check('follow-1800-33599', i1800.includes('33,599'), i1800.replace(/\s+/g, ' ').trim())
  check('ply-downloaded-once', plyRequests === 1, `ply requests=${plyRequests}`)
  await page.screenshot({ path: `${OUT}/follow-1800.png` })

  // 同一 revision 轮询不重复下载 PLY
  await page.waitForTimeout(3500)
  check('duplicate-revision-no-redownload', plyRequests === 1, `ply requests after wait=${plyRequests}`)

  // 发布 3600s（group_02），浏览器应自动切到 43,005
  const pub3600 = publish('group_02')
  check('publish-3600-ok', pub3600.ok, pub3600.out)
  await page.waitForTimeout(3500)
  const i3600 = await followInfo()
  check('follow-3600-43005', i3600.includes('43,005'), i3600.replace(/\s+/g, ' ').trim())
  check('ply-redownloaded-new-revision', plyRequests === 2, `ply requests=${plyRequests}`)
  check('glb-not-reloaded', glbRequests === glbAfterLoad, `glb before=${glbAfterLoad} after=${glbRequests}`)
  await page.screenshot({ path: `${OUT}/follow-3600.png` })

  // 旧时间帧不能覆盖
  const pubOld = publish('group_01')
  check('old-frame-rejected', !pubOld.ok && pubOld.out.includes('旧时间帧'), pubOld.out)
  await page.waitForTimeout(2500)
  const afterOld = await followInfo()
  check('old-frame-not-overwrite', afterOld.includes('43,005'), afterOld.replace(/\s+/g, ' ').trim())

  // 损坏文件不能覆盖：构造一个 t=7200 但 PLY 点数错误的坏结果
  const badDir = '/tmp/e2e-bad-recon'
  mkdirSync(badDir, { recursive: true })
  writeFileSync(`${badDir}/summary.json`, JSON.stringify({
    scene_id: 'sjk_hydropower_sim_v0_1',
    asset_version: 'hydro-sim-v0.1-local',
    coordinate_frame_id: 'SJK_TEAM_FBX_FILE_METRE_UNREGISTERED_v1',
    voxel_size_m: 4.0,
    groups: [{
      group_id: 'group_01', simulation_time_s: 7200.0, source_camera_count: 2,
      candidate_voxel_count: 33599,
      terrain_clip: { glb_sha256: '722b8514a17715f3c109b1cbaa8259dc958c8f212af71cd1c0ae75608566fb91' },
    }],
  }))
  writeFileSync(`${badDir}/group_01-voxels.ply`, writeBadPly(10))
  const pubBad = publish('group_01', badDir)
  check('bad-frame-rejected', !pubBad.ok && pubBad.out.includes('点数'), pubBad.out)
  await page.waitForTimeout(2500)
  const afterBad = await followInfo()
  check('bad-frame-not-overwrite', afterBad.includes('43,005'), afterBad.replace(/\s+/g, ' ').trim())

  // 退出跟随：清空体素图层（徽标消失）
  await page.getByRole('button', { name: '停止跟随' }).click()
  await page.waitForTimeout(500)
  check('exit-clears-follow', !(await page.getByText('历史采集 · 候选体素').first().isVisible().catch(() => false)))
} catch (e) {
  failures++
  console.error('FATAL:', e instanceof Error ? e.message : String(e))
  await page.screenshot({ path: `${OUT}/error.png` }).catch(() => {})
} finally {
  const appChecksFail = results.filter((r) => !r.ok).length
  failures += appChecksFail
  writeFileSync(`${OUT}/result.json`, JSON.stringify({
    run_id: RUN_ID, checks: results,
    checks_passed: results.length - appChecksFail, checks_total: results.length,
    ply_requests: plyRequests, glb_requests: glbRequests, summary_requests: summaryRequests,
    exit_status: failures === 0 ? 0 : 1,
  }, null, 2))
  await browser.close()
}
console.log(`\nRESULT: ${results.length - results.filter((r) => !r.ok).length}/${results.length} checks passed`)
process.exit(failures === 0 ? 0 : 1)
