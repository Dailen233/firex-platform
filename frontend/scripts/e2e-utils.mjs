// Shared harness for the Fire-X B4 browser verification scripts.
// Any unexpected exception, failed check, console error, page error, or
// unexpected failed request makes the process exit non-zero. A graceful
// in-flight abort (net::ERR_ABORTED) is the normal cancellation mechanism and
// is therefore excluded from "unexpected failed requests".
import { chromium } from 'playwright'

export const FRONTEND = process.env.FIREX_FRONTEND || 'http://127.0.0.1:4173'
export const BACKEND = process.env.FIREX_BACKEND || 'http://127.0.0.1:8002'
export const SCENE_URL = `${FRONTEND}/#/scene/shuangjiangkou_reference_terrain`

// Verify the target is actually the firex-backend BEFORE any write request.
export async function verifyService(base = BACKEND) {
  const res = await fetch(`${base}/health`)
  if (!res.ok) throw new Error(`health HTTP ${res.status}`)
  const h = await res.json()
  if (h.service !== 'firex-backend') throw new Error(`目标服务不是 firex-backend（service=${h.service}）`)
  return h
}

export async function launchPage() {
  const browser = await chromium.launch({ channel: 'chrome', headless: true })
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
  const state = { consoleErrors: [], pageErrors: [], failedRequests: [], glbFetches: 0 }
  page.on('console', (m) => { if (m.type() === 'error') state.consoleErrors.push(m.text()) })
  page.on('pageerror', (e) => state.pageErrors.push(String(e)))
  page.on('requestfailed', (r) => {
    const err = r.failure()?.errorText ?? ''
    if (err !== 'net::ERR_ABORTED') state.failedRequests.push(`${r.method()} ${r.url()} ${err}`)
  })
  page.on('response', (r) => { if (r.url().includes('terrain_reference.glb')) state.glbFetches++ })
  return { browser, page, state }
}

export function makeChecks() {
  const results = []
  let fatal = null
  return {
    results,
    check(name, ok, detail = '') {
      results.push({ name, ok, detail })
      console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`)
    },
    fail(e) {
      fatal = e
      console.error('FATAL:', e instanceof Error ? e.message : String(e))
    },
    get fatalError() { return fatal },
    get failedCount() { return results.filter((r) => !r.ok).length + (fatal ? 1 : 0) },
  }
}

/** Wait for text (exact or substring) with a deadline; throws with a diagnostic on timeout. */
export async function waitForText(page, text, { exact = false, timeout = 10000, label } = {}) {
  try {
    await page.getByText(text, { exact }).first().waitFor({ timeout })
  } catch {
    const body = await page.locator('body').innerText().catch(() => '(unavailable)')
    throw new Error(`等待文本超时「${label ?? text}」。当前页面文本：\n${body.slice(0, 800)}`)
  }
}

export async function finish(browser, checks, state, extraFailures = 0) {
  console.log('\n--- console errors ---')
  console.log(state.consoleErrors.length ? state.consoleErrors.join('\n') : '(none)')
  console.log('--- page errors ---')
  console.log(state.pageErrors.length ? state.pageErrors.join('\n') : '(none)')
  console.log('--- unexpected failed requests ---')
  console.log(state.failedRequests.length ? state.failedRequests.join('\n') : '(none)')
  await browser.close()
  const failures = checks.failedCount + state.consoleErrors.length + state.pageErrors.length + state.failedRequests.length + extraFailures
  const passed = checks.results.filter((r) => r.ok).length
  const total = checks.results.length
  console.log(`\nRESULT: ${passed}/${total} checks passed, ${failures} failures`)
  return failures
}
