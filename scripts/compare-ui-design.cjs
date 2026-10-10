// Present the supplied reference alongside actual before/after browser captures.
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('C:/Users/USER/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright')
const root = path.resolve('artifacts/ui-design')
const image = file => 'data:image/png;base64,' + fs.readFileSync(file).toString('base64')
;(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1800, height: 1050 } })
    for (const [name, reference, shot] of [
      ['home', '스크린샷 2026-10-10 040205.png', 'default-home-1440.png'],
      ['editor', '스크린샷 2026-10-10 040229.png', 'default-editor-1440.png'],
    ]) {
      const files = [path.join(root, 'before/after', shot), path.resolve('Ui 참고 자료', reference), path.join(root, 'after', shot)]
      const labels = ['A · 수정 전', 'B · 사용자가 제공한 목표 UI', 'C · 수정 후']
      const html = '<!doctype html><meta charset="utf-8"><style>body{margin:0;padding:24px;background:#edf0ea;font-family:system-ui}main{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}h2{font-size:20px}img{width:100%;display:block;border:1px solid #bbc6b9}p{font-size:14px;line-height:1.8}</style><main>' + files.map((f,i) => `<section><h2>${labels[i]}</h2><img src="${image(f)}"></section>`).join('') + '</main><p>차이: 기본 테마의 책 표지 목록을 흰색 글 카드로 변경. 연녹색 메뉴와 녹색 버튼, 넓은 연속 편집기 비율 복원. 기존 검색·문단 탐색·API 오류 처리는 유지.</p>'
      fs.writeFileSync(path.join(root, name + '-comparison.html'), html)
      await page.setContent(html)
      await page.screenshot({ path: path.join(root, name + '-comparison.png'), fullPage: true })
    }
  } finally { await browser.close() }
  console.log('PASS: before/reference/after comparisons rendered')
})().catch(e => { console.error(e); process.exitCode = 1 })
