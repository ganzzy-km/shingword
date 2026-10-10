// Browser-only synthetic fixtures: never reaches a DB or production API.
const { chromium } = require(process.env.PLAYWRIGHT_PACKAGE || 'C:/Users/USER/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright')
const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')
const mode = process.argv[2] || 'after'
const base = process.env.UI_PREVIEW_URL || 'http://127.0.0.1:8443'
const dir = path.resolve(process.env.UI_ARTIFACT_ROOT || 'artifacts/ui-recovery', mode)
fs.mkdirSync(dir, { recursive: true })
const paragraph = '문학은 삶을 비추는 거울이다. 🐧 인물은 몇일 동안 자신의 선택을 설명한다. 직접 인용 뒤에는 연결 설명을 확인한다. '
const content = Array.from(Array.from({ length: 100 }, (_, i) => `${i + 1}. ${paragraph.repeat(5)}`).join('\n\n')).slice(0, 30000).join('')
const offset = Array.from(content.slice(0, content.indexOf('몇일'))).length
const finding = { id: 'f1', title: '표기 확인', type: 'spelling', current: '몇일', reason: '가상 검증 피드백', rule: '검증 fixture', status: '확인 필요', startOffset: offset, endOffset: offset + 2 }
let runningBrowser
;(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  runningBrowser = browser
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  let prefs = { theme: 'default', pageAnimation: false, bookTexture: true }
  let writing = { id: 'synthetic-essay', title: 'UI 복구 검증용 긴 에세이', work: '가상 작품', content, inquiryQuestion: '선택과 책임은 어떻게 연결되는가?', status: '임시 저장', updatedAt: '2026-10-10T00:00:00Z', revisionNumber: 1, characterCount: 30000, latestAnalysisId: 'a1', analysisRuns: [{ id: 'a1', status: 'completed', createdAt: '2026-10-10T00:00:00Z' }] }
  let reject = false
  const unknown = []
  await context.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url())
    if (url.origin !== new URL(base).origin) return route.abort()
    if (!url.pathname.startsWith('/api/')) return route.continue()
    let data, status = 200
    const endpoint = url.pathname.slice(4), method = req.method()
    if (reject) return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'AUTHENTICATION_NOT_IMPLEMENTED', message: '검증용 API 차단 상태' } }) })
    if (endpoint === '/workspace') data = { userName: '', workspaceName: '가상 검증 공간' }
    else if (endpoint === '/settings') { if (method === 'PATCH') prefs = { ...prefs, ...req.postDataJSON() }; data = prefs }
    else if (endpoint === '/writings' || endpoint === '/records') data = [writing]
    else if (endpoint === '/writings/synthetic-essay') data = writing
    else if (endpoint === '/writings/synthetic-essay/autosave') { const body = req.postDataJSON(); writing = { ...writing, ...body, revisionNumber: writing.revisionNumber + 1 }; data = writing }
    else if (endpoint === '/analyses/a1') data = { id: 'a1', writingId: writing.id, findings: [finding], disclaimer: '가상 데이터로 UI만 검증합니다.' }
    else if (endpoint === '/analyses') { data = { analysisId: 'a1', jobId: 'j1' }; status = 202 }
    else if (endpoint === '/analysis-jobs/j1') data = { status: 'completed', progress: 100, currentStep: '완료', analysisId: 'a1' }
    else if (['/rules', '/rubrics', '/sources', '/quotes', '/source-documents', '/quote-cards', '/backups'].includes(endpoint)) data = []
    else if (endpoint === '/dictionary/status') data = { available: false, status: 'not_configured' }
    else { unknown.push(method + ' ' + endpoint); return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { message: '지원하지 않는 검증 fixture' } }) }) }
    return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ data, pagination: { total: 1 } }) })
  })
  const page = await context.newPage(), errors = []
  page.on('pageerror', e => errors.push(e.message))
  const shots = []
  const shot = async name => {
    await page.screenshot({ path: path.join(dir, name + '.png'), fullPage: true })
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)
    if (mode === 'after') assert.equal(overflow, false, name + ' overflow')
    shots.push({ name, overflow, visibleShells: await page.locator('.gb:visible').count() })
  }
  for (const width of [1440, 820, 390]) {
    prefs.theme = 'default'
    await page.setViewportSize({ width, height: 1000 })
    await page.goto(base)
    await page.getByRole('heading', { name: writing.title, exact: true }).first().waitFor()
    await shot('default-home-' + width)
    if (mode === 'before') {
      await page.goto(base + '/new-analysis')
      await page.getByText('기본 정보 입력', { exact: true }).waitFor()
      await shot('legacy-new-analysis-' + width)
      await page.goto(base + '/history')
      await page.waitForTimeout(300)
      await shot('legacy-history-' + width)
      continue
    }
    await page.getByRole('button', { name: new RegExp(writing.title) }).first().click()
    await page.getByRole('textbox', { name: '에세이 본문' }).waitFor()
    assert.ok(await page.locator('.paragraph-nav button').count() > 1)
    await shot('default-editor-' + width)
    await page.getByRole('button', { name: '분석하기', exact: true }).click()
    await page.getByRole('button', { name: '분석하기', exact: true }).waitFor()
    await page.getByText('가상 검증 피드백', { exact: true }).first().waitFor()
    await shot('default-feedback-' + width)
    await page.getByRole('button', { name: /원문으로 이동/ }).first().click()
    assert.equal(await page.getByRole('textbox', { name: '에세이 본문' }).evaluate(e => e.value.slice(e.selectionStart, e.selectionEnd)), '몇일')
    await page.getByPlaceholder('본문에서 찾기').fill('몇일')
    if (width === 1440) {
      const draft = '2' + writing.content.slice(1)
      await page.getByRole('textbox', { name: '에세이 본문' }).fill(draft)
      await page.getByRole('button', { name: '분석 규칙', exact: true }).click()
      await page.locator('.gb-auxiliary').waitFor()
      await page.getByRole('button', { name: '← 작성 중인 글로 돌아가기', exact: true }).click()
      assert.equal(await page.getByRole('textbox', { name: '에세이 본문' }).inputValue(), draft)
    }
    await page.getByRole('button', { name: '화면 설정', exact: true }).first().click()
    await shot('settings-' + width)
    await page.getByRole('button', { name: /책장 테마/ }).click()
    await page.getByRole('button', { name: '닫기', exact: true }).click()
    await page.getByRole('button', { name: '← 서재로 돌아가기', exact: true }).click()
    await shot('bookshelf-' + width)
    await page.getByRole('button', { name: new RegExp(writing.title) }).first().click()
    await page.getByLabel('책 본문. 좌우 방향키로 페이지 이동').waitFor()
    await shot('book-open-' + width)
    await page.getByRole('button', { name: '다음 페이지', exact: true }).click()
    await shot('book-turn-' + width)
    let reconstructed = ''
    await page.getByRole('button', { name: '이전 페이지', exact: true }).click()
    for (;;) {
      reconstructed += await page.locator('.page-body').evaluateAll(nodes => nodes.map(e => e.textContent).join(''))
      const next = page.getByRole('button', { name: '다음 페이지', exact: true })
      if (await next.isDisabled()) break
      await next.click()
    }
    assert.equal(reconstructed, writing.content)
    await page.getByRole('button', { name: '분석하기', exact: true }).click()
    await page.getByRole('button', { name: '분석하기', exact: true }).waitFor()
    await page.getByText('가상 검증 피드백', { exact: true }).first().waitFor()
    await page.getByRole('button', { name: /원문으로 이동/ }).first().click()
    assert.equal(await page.locator('.page-body mark').first().textContent(), '몇일')
    await shot('book-feedback-' + width)
    // Direct former-Figma deep links must now use the same current shell.
    for (const route of ['/history', '/new-analysis', '/analysis-results?analysis=a1', '/rules', '/settings', '/criteria', '/works']) {
      await page.goto(base + route)
      await page.locator('.gb:visible').waitFor()
      await page.waitForTimeout(150)
      assert.equal(await page.locator('.gb-sidebar:visible').count(), width > 1100 ? 1 : 0)
      assert.equal(await page.locator('.gb:visible').count(), 1)
      assert.equal(await page.getByText('기본 정보 입력', { exact: true }).count(), 0)
      await shot(route.split('?')[0].slice(1) + '-route-' + width)
    }
    console.log(JSON.stringify({ width, codePoints: Array.from(writing.content).length, reconstructedExactly: true }))
  }
  reject = true
  await page.goto(base)
  await page.getByRole('alert').filter({ hasText: '검증용 API 차단 상태' }).waitFor()
  assert.equal(await page.getByText(writing.title, { exact: true }).count(), 0)
  await shot('blocked-api-no-fallback')
  if (mode === 'after') { assert.deepEqual(errors, []); assert.deepEqual(unknown, []) }
  fs.writeFileSync(path.join(dir, 'results.json'), JSON.stringify({ mode, shots, errors, unknown, codePoints: 30000, fixtureOnly: true }, null, 2))
  await browser.close()
  console.log(JSON.stringify({ mode, screenshots: shots.length, errors, fixtureOnly: true }))
})().catch(async e => { console.error(e); if (runningBrowser) await runningBrowser.close(); process.exitCode = 1 })
