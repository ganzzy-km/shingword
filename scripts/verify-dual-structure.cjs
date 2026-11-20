const assert = require('node:assert/strict')
const fs = require('node:fs')
const { createHash } = require('node:crypto')
const path = require('node:path')
const { chromium } = require(process.env.PLAYWRIGHT_PACKAGE || 'C:/Users/USER/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright')
const base = 'https://localhost:8796'
const output = path.resolve(process.env.GEULBIT_DUAL_EVIDENCE || 'artifacts/dual-structure/evidence')
const action = process.argv[2] || 'initial'
const fixture = '😀 학교에 독서 시간이 필요하다고 생각한다. 실제로 친구들은 “하루 ‘십 분’부터 시작했다”고 말했다. 학교의 독서 시간을 늘릴 수 있다.'
const results = []
const delay = ms => new Promise(resolve => setTimeout(resolve, ms))

async function request(context, method, route, body, status = 200) {
  const headers = {}
  if (method !== 'GET') {
    const auth = await context.request.get(base + '/api/auth/session')
    assert.equal(auth.status(), 200)
    headers['X-CSRF-Token'] = (await auth.json()).data.csrfToken
  }
  const response = await context.request.fetch(base + route, { method, headers, data: body })
  assert.equal(response.status(), status, `${method} ${route} ${await response.text()}`)
  assert.equal(response.headers()['x-geulbit-profile'], 'STAGING')
  return response.json()
}

async function waitUntil(check, timeout = 15000) {
  const end = Date.now() + timeout
  while (Date.now() < end) {
    if (await check()) return
    await delay(120)
  }
  throw new Error('Expected condition did not appear')
}

async function check(name, task) {
  const started = performance.now()
  try {
    const info = await task()
    results.push({ name, status: 'PASS', ms: Math.round(performance.now() - started), ...(info || {}) })
    console.log(name + ' PASS')
  } catch (error) {
    results.push({ name, status: 'FAIL', error: error.message })
    throw error
  }
}

async function login(context, name) {
  await context.request.get(base + '/__staging__/session/' + name)
  await request(context, 'GET', '/api/auth/session')
}

async function openWriting(page, title) {
  await page.goto(base + '/')
  const button = page.getByRole('button').filter({ hasText: title }).first()
  await button.click()
  await page.getByRole('heading', { level: 1, name: title, exact: true }).waitFor()
}

async function theme(page, value) {
  await page.getByRole('button', { name: '화면 설정', exact: true }).last().click()
  const dialog = page.getByRole('dialog', { name: '화면 설정' })
  await dialog.getByRole('button', { name: value === 'default' ? /^기본 테마/ : /^책장 테마/ }).click()
  await page.locator('.gb.' + value).waitFor()
  await dialog.getByRole('button', { name: '닫기', exact: true }).click()
}

async function main() {
  fs.mkdirSync(output, { recursive: true })

  const browser = await chromium.launch({ channel: 'chrome', headless: true })
  const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 1000 } })
  const other = await browser.newContext({ ignoreHTTPSErrors: true })
  const pageErrors = []
  try {
    await context.route('**/*', route => {
      const url = new URL(route.request().url())
      return url.origin === base ? route.continue() : route.abort()
    })
    const health = await context.request.get(base + '/api/health')
    assert.equal(health.status(), 200)
    assert.equal(health.headers()['x-geulbit-profile'], 'STAGING')
    assert.equal((await health.json()).data.schema, '0006_dual_structure')
    await login(context, 'student-a')
    await login(other, 'student-b')
    const page = await context.newPage()
    page.on('pageerror', error => pageErrors.push(error.name + ': ' + error.message))
    const openAi = page.getByRole('button', { name: 'AI 구조 분석', exact: true })
    const openS4 = page.getByRole('button', { name: 'S4 분석', exact: true })
    const openComparison = page.getByRole('button', { name: '분석 비교', exact: true })
    const confirm = page.getByRole('dialog', { name: 'AI 전송 문장 확인' })
    const editor = page.getByRole('textbox', { name: '에세이 본문', exact: true })
    const caseFile = path.join(output, 'synthetic-case.json')
    if (action === 'legacy-ocr') {
      await check('saved_standard_ocr_job_reopens', async () => {
        const id = process.env.GEULBIT_STAGING_LEGACY_JOB
        assert.match(id || '', /^[a-f0-9-]{36}$/)
        const result = (await request(context, 'GET', '/api/ocr-jobs/' + id)).data
        assert.equal(result.ocrMode, 'standard')
        assert.ok(result.pages.length)
        return { mode: result.ocrMode, pages: result.pages.length, state: result.status }
      })
      return
    }
    if (action === 'ocr') {
      const images = process.env.GEULBIT_OCR_FIXTURES
      assert.ok(images, 'Set GEULBIT_OCR_FIXTURES to the existing synthetic fixture directory')
      const auth = (await request(context, 'GET', '/api/auth/session')).data
      const upload = (file, options) => context.request.post(base + '/api/source-documents', {
        headers: { 'X-CSRF-Token': auth.csrfToken }, multipart: {
          file: { name: path.basename(file), mimeType: 'application/pdf', buffer: fs.readFileSync(file) },
          title: 'Dual STAGING synthetic ' + Date.now(), rightsConfirmed: 'true', accessMode: 'DOWNLOAD', ...options,
        },
      })
      const scanned = path.join(images, 'PATCH-OCR-PRECISION-005/evaluation/new-prose.pdf')
      await check('legacy_standard_creation_boundary_and_native_pdf', async () => {
        const legacy = await upload(scanned, { ocrMode: 'standard' })
        assert.equal(legacy.status(), 400)
        assert.equal((await legacy.json()).error.code, 'OCR_MODE_RETIRED')
        const native = await upload(path.join(images, 'PATCH-OCR-PRECISION-002/evaluation/reg-native-1.pdf'), {})
        assert.equal(native.status(), 201)
        const source = (await native.json()).data
        assert.equal(source.ocr.status, 'not_required')
        assert.ok((await request(context, 'GET', '/api/source-documents/' + source.id)).data.content.trim())
      })
      await check('actual_local_precision_ocr_confirm_reload_and_ownership', async () => {
        const started = await upload(scanned, { ocrMode: 'precise', ocrProfile: 'prose' })
        assert.equal(started.status(), 201, await started.text())
        const source = (await started.json()).data
        const url = '/api/ocr-jobs/' + source.ocr.jobId
        let job
        await waitUntil(async () => {
          job = (await request(context, 'GET', url)).data
          assert.ok(!['FAILED', 'CANCELLED', 'EXPIRED'].includes(job.status), JSON.stringify({ status: job.status, error: job.error }))
          return job.status === 'REVIEW_READY'
        }, 240000)
        assert.equal(job.ocrMode, 'precise')
        assert.ok(job.pages[0].calls.includes('PP-StructureV3') && job.pages[0].calls.includes('tesseract_best'))
        assert.equal(job.pages[0].precision.policy.version, 'geulbit.ocr.precision/6')
        const confirmed = (await request(context, 'POST', url + '/confirm', {
          expectedDraftVersion: job.draftVersion, expectedRevisionId: source.latestRevisionId,
        }, 201)).data
        const full = (await request(context, 'GET', '/api/source-documents/' + source.id)).data
        assert.equal(full.latestRevisionId, confirmed.revisionId)
        assert.ok(full.content.trim())
        await request(other, 'GET', url, undefined, 404)
        return { precisionPolicy: job.pages[0].precision.policy.version, engines: job.pages[0].calls,
          peakWorkerBytes: job.peakWorkerBytes, ocrSeconds: job.seconds }
      })
      return
    }
    if (action === 'restart') {
      const evidence = JSON.parse(fs.readFileSync(caseFile, 'utf8'))
      await check('persisted_after_process_restart', async () => {
        const same = (await request(context, 'GET', evidence.route)).data
        assert.equal(same.ai.id, evidence.aiId)
        assert.equal(same.ai.status, 'COMPLETED')
        assert.equal(same.versionStatus, 'STALE')
        assert.ok(same.comparison.nodes.length)
        const edited = (await request(context, 'GET', evidence.newRoute)).data
        assert.equal(edited.versionStatus, 'CURRENT')
        assert.equal(edited.ai.id, evidence.newAiId)
        const metrics = await (await context.request.get(base + '/__staging__/dual/metrics')).json()
        assert.deepEqual(metrics, { providerCalls: 0, externalCalls: 0 })
        await openWriting(page, evidence.title)
        await openAi.click()
        await page.getByText('synthetic-staging · 2개 후보', { exact: true }).waitFor()
        assert.equal((await request(context, 'GET', evidence.newRoute)).data.ai.id, evidence.newAiId)
      })
      return
    }
    await check('exact_candidate_frontend_is_served', async () => {
      const dist = path.resolve('artifacts/dual-structure/build')
      const names = ['index.html', ...fs.readdirSync(path.join(dist, 'assets')).map(name => 'assets/' + name)]
      const hash = bytes => createHash('sha256').update(bytes).digest('hex')
      for (const name of names) {
        const result = await context.request.get(base + '/' + name)
        assert.equal(result.status(), 200)
        assert.equal(hash(await result.body()), hash(fs.readFileSync(path.join(dist, name))))
      }
      return { files: names.length }
    })
    await request(context, 'PATCH', '/api/settings', { theme: 'default', autosaveInterval: 30 })
    const prefs = (await request(context, 'GET', '/api/writing-tools/preferences')).data
    await request(context, 'PATCH', '/api/writing-tools/preferences', { revisionNumber: prefs.revisionNumber, data: { tutorial: 'SKIPPED', focus: false } })
    await page.goto(base + '/')
    const title = 'DUAL STAGING ' + Date.now()
    let s4, id, route, aiId, newRoute, newAiId
    await check('write_freeze_s4_quotes_default', async () => {
      await page.getByRole('button', { name: '새 글 작성', exact: true }).last().click()
      await page.getByLabel('제목', { exact: true }).fill(title)
      await page.getByLabel('탐구 질문', { exact: true }).fill('학교 독서 시간은 왜 필요한가?')
      await editor.fill(fixture)
      const analysisResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/analyses' && response.request().method() === 'POST')
      await page.getByRole('button', { name: '분석하기', exact: true }).click()
      const response = await analysisResponse
      assert.equal(response.status(), 202)
      s4 = (await response.json()).data
      const analysisUrl = '/api/analyses/' + s4.analysisId
      await waitUntil(async () => (await request(context, 'GET', analysisUrl)).data.status === 'completed')
      id = (await request(context, 'GET', analysisUrl)).data.writingId
      route = '/api/writing-versions/' + s4.essayVersionId + '/structure?analysisId=' + s4.analysisId
      const data = (await request(context, 'GET', route)).data
      assert.equal(data.versionStatus, 'CURRENT')
      assert.ok(data.s4.nodes.length)
      assert.equal(data.ai, null)
      assert.equal(await openS4.getAttribute('aria-pressed'), 'true')
      assert.equal(data.quotations.length, 2)
      assert.equal(data.quotations[1].parent_id, data.quotations[0].quote_id)
      assert.equal(Array.from(fixture).slice(data.quotations[1].start, data.quotations[1].end).join(''), '‘십 분’')
      await page.getByLabel('인용문 강조').waitFor()
    })
    await check('explicit_consent_escape_then_async_ai_and_comparison', async () => {
      await openAi.click()
      await page.getByRole('button', { name: 'AI 구조 분석 실행', exact: true }).click()
      await confirm.waitFor()
      assert.ok(await confirm.getByText(/비용이 발생할 수 있습니다/).isVisible())
      assert.ok(await confirm.getByRole('button', { name: '동의하고 분석 실행' }).isDisabled())
      await page.keyboard.press('Escape')
      await confirm.waitFor({ state: 'hidden' })
      assert.equal((await (await context.request.get(base + '/__staging__/dual/metrics')).json()).providerCalls, 0)
      await page.getByRole('button', { name: 'AI 구조 분석 실행', exact: true }).click()
      await confirm.waitFor()
      await confirm.getByRole('checkbox', { name: /선택한 문장과 비용 안내/ }).check()
      await confirm.getByRole('button', { name: '동의하고 분석 실행' }).click()
      await page.getByText(/AI 분석 대기 중|AI가 구조를 분석하고 있습니다/).waitFor()
      await openS4.click()
      await page.getByRole('heading', { name: '분석 피드백' }).waitFor()
      await openAi.click()
      await page.getByText('synthetic-staging · 2개 후보', { exact: true }).waitFor()
      await page.locator('.argument-editor-mirror .quotation-range.dual-ai-evidence').waitFor({ state: 'attached' })
      const mirror = page.locator('.argument-editor-mirror .argument-fragment')
      assert.equal((await mirror.allTextContents()).join(''), fixture)
      await page.getByLabel('인용문 강조').uncheck()
      assert.equal(await page.locator('.argument-editor-mirror .quotation-range').count(), 0)
      assert.ok(await page.locator('.argument-editor-mirror .dual-ai-evidence').count())
      await page.getByLabel('인용문 강조').check()
      await openComparison.click()
      await page.getByRole('heading', { name: '관계 불일치', exact: true }).waitFor()
      const data = (await request(context, 'GET', route)).data
      assert.equal(data.ai.status, 'COMPLETED')
      aiId = data.ai.id
      assert.ok(data.comparison.nodes.length && data.comparison.relations.length)
      await request(other, 'GET', route, undefined, 404)
      return { comparisons: data.comparison.nodes.length, relationDifferences: data.comparison.relations.length }
    })
    await check('responsive_comparison_in_both_themes', async () => {
      for (const variant of ['default', 'bookshelf']) {
        await page.setViewportSize({ width: 1440, height: 1000 })
        await theme(page, variant)
        for (const width of [1440, 390]) {
          await page.setViewportSize({ width, height: 900 })
          await openComparison.click()
          await page.getByRole('heading', { name: '관계 불일치', exact: true }).waitFor()
          assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1))
          const group = page.getByRole('group', { name: '분석 보기 선택' })
          const box = await group.boundingBox()
          assert.ok(box.width <= width && box.width > 0)
          await page.screenshot({ path: path.join(output, `${variant}-${width}.png`) })
        }
      }
      await page.setViewportSize({ width: 1440, height: 1000 })
      await theme(page, 'default')
      return { configurations: 4 }
    })
    await check('reader_and_focus_escape_preserve_working_draft', async () => {
      await page.getByRole('button', { name: '책으로 읽기', exact: true }).click()
      await page.getByLabel('책 본문. 좌우 방향키로 페이지 이동').waitFor()
      await page.getByRole('button', { name: '편집하기', exact: true }).click()
      await page.getByRole('button', { name: '집중 편집', exact: true }).click()
      await page.locator('.gb.is-focus').waitFor()
      await page.keyboard.press('Escape')
      await page.locator('.gb.is-focus').waitFor({ state: 'hidden' })
      assert.equal(await editor.inputValue(), fixture)
      await openComparison.waitFor()
    })
    await check('save_navigate_reopen_edit_stale_and_new_independent_ai', async () => {
      const editButton = page.getByRole('button', { name: '편집하기', exact: true })
      if (await editButton.isVisible()) await editButton.click()
      await editor.fill(fixture + ' 달라진 저장 판본입니다.')
      await openAi.click()
      await page.getByText('이전 판본의 구조 결과입니다.', { exact: true }).waitFor()
      await page.getByRole('button', { name: '현재 글 저장 후 판본 선택' }).click()
      await page.getByRole('button', { name: 'AI 구조 분석 실행', exact: true }).click()
      await confirm.waitFor()
      await confirm.getByRole('checkbox', { name: /선택한 문장과 비용 안내/ }).check()
      await confirm.getByRole('button', { name: '동의하고 분석 실행' }).click()
      await page.getByText('synthetic-staging · 2개 후보', { exact: true }).waitFor()
      const writing = (await request(context, 'GET', '/api/writings/' + id)).data
      newRoute = '/api/writing-versions/' + writing.currentVersionId + '/structure'
      const current = (await request(context, 'GET', newRoute)).data
      const old = (await request(context, 'GET', route)).data
      assert.equal(current.versionStatus, 'CURRENT')
      assert.equal(current.s4, null)
      assert.equal(old.versionStatus, 'STALE')
      assert.equal(old.ai.id, aiId)
      assert.notEqual(current.ai.id, aiId)
      newAiId = current.ai.id
      await openWriting(page, title)
      await openAi.click()
      await page.getByText('synthetic-staging · 2개 후보', { exact: true }).waitFor()
      await page.getByRole('button', { name: '외부 전송 동의 철회' }).click()
      await waitUntil(async () => !(await request(context, 'GET', newRoute)).data.consented)
      const metrics = await (await context.request.get(base + '/__staging__/dual/metrics')).json()
      assert.deepEqual(metrics, { providerCalls: 2, externalCalls: 0 })
      fs.writeFileSync(caseFile, JSON.stringify({ title, route, aiId, newRoute, newAiId }, null, 2))
    })
    assert.deepEqual(pageErrors, [])
  } finally {
    await browser.close()
    fs.writeFileSync(path.join(output, `browser-${action}.json`), JSON.stringify({ results, pageErrors }, null, 2))
  }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
