// Browser transport fixtures contain actual isolated Flask/Kiwi output.
// No operating DB, real account or external AI is accessed by this test.
const { chromium }=require(process.env.PLAYWRIGHT_PACKAGE || 'C:/Users/USER/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const smoke=process.env.ARGUMENT_SMOKE_ONLY==='1';
const dir=path.resolve('artifacts/argument-links'),base=process.env.UI_PREVIEW_URL || 'http://127.0.0.1:8447';
const actual=JSON.parse(fs.readFileSync(dir+'/kiwi-fixture.json','utf8')),empty=JSON.parse(fs.readFileSync(dir+'/empty-fixture.json','utf8'));
(async()=>{const browser=await chromium.launch({channel:'chrome',headless:true});const checks=[],errors=[];let pagesChecked=0;
try{for(const theme of ['default','bookshelf'])for(const width of (process.env.ARGUMENT_VERIFY_WIDTHS || '1440,820,390').split(',').map(Number)){
 const context=await browser.newContext({viewport:{width,height:1000},hasTouch:width===390});let data=structuredClone(actual);
 await context.route('**/*',async route=>{
  const req=route.request(),url=new URL(req.url());if(url.origin!==new URL(base).origin)return route.abort();
  if(!url.pathname.startsWith('/api/'))return route.continue();
  const p=url.pathname;let value=[];
  if(p==='/api/auth/session')value={id:'synthetic-user',role:'USER',status:'ACTIVE',csrfToken:'synthetic-only'};
  else if(p==='/api/settings')value={theme,pageAnimation:false};
  else if(p==='/api/workspace')value={userName:'',workspaceName:'가상 구조 검증'};
  else if(p==='/api/writings')value=[data.writing];
  else if(p==='/api/writings/'+data.writing.id){if(req.method()==='PATCH')data.writing={...data.writing,...req.postDataJSON(),revisionNumber:data.writing.revisionNumber+1};value=data.writing;}
  else if(p==='/api/analyses/'+data.analysis.id)value=data.analysis;
  await route.fulfill({json:{data:value}});
 });
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));await page.goto(base);
 await page.getByRole('button',{name:new RegExp(data.writing.title)}).first().click();
 const claim=actual.analysis.argumentCandidates.find(c=>c.roles.includes('CLAIM_CANDIDATE'));
 const evidence=actual.analysis.argumentCandidates.find(c=>c.roles.includes('EVIDENCE_CANDIDATE'));
 if(theme==='bookshelf')await page.getByRole('button',{name:'편집하기',exact:true}).click();
 const editor=page.getByRole('textbox',{name:'에세이 본문'});
 await editor.waitFor();assert.equal(await editor.inputValue(),actual.analysis.sourceVersion.content);
 await page.evaluate(()=>document.fonts.ready);
 const mirror=page.locator('.argument-editor-mirror');assert.equal(await mirror.locator('.argument-claim').count(),1);assert.equal(await mirror.locator('.argument-evidence').count(),1);
 assert.deepEqual(await page.evaluate(()=>{const n=document.querySelector('textarea[aria-label="에세이 본문"]'),m=document.querySelector('.argument-editor-mirror'),a=getComputedStyle(n),b=getComputedStyle(m);return [a.font===b.font,a.padding===b.padding,n.clientWidth===m.clientWidth]}),[true,true,true]);
 await editor.evaluate(node=>{const arrow=document.querySelector('.argument-editor-mirror [data-argument-relation]');const y=arrow.getBoundingClientRect().top-node.getBoundingClientRect().top+node.scrollTop;node.scrollTop=Math.max(0,y-100)});
 const editorArrow=page.locator('.argument-editor-controls .argument-link');await editorArrow.waitFor({state:'visible'});
 await page.screenshot({path:dir+`/${theme}-${width}-editor.png`});
 if(width===390)await editorArrow.tap();else {await editorArrow.focus();await page.keyboard.press('Enter')}
 await page.getByRole('region',{name:'주장과 근거 연결'}).waitFor();
 assert.equal(await editor.evaluate(n=>n.value.slice(n.selectionStart,n.selectionEnd)),claim.quote);
 await mirror.locator('.argument-focused').waitFor();
 assert.ok(await editor.evaluate(n=>n.scrollTop)<100);
 await page.screenshot({path:dir+`/${theme}-${width}-claim-editor.png`});
 const work=page.getByPlaceholder('작품명 (선택)',{exact:true}),question=page.getByPlaceholder('이 글에서 탐구하고 싶은 질문',{exact:true});
 await work.fill('다른 작품');assert.equal(await page.locator('.argument-editor-controls .argument-link').count(),0);await work.fill(actual.writing.work);
 await question.fill('다른 탐구 문맥');assert.equal(await page.locator('.argument-editor-controls .argument-link').count(),0);await question.fill(actual.writing.inquiryQuestion);
 // Modified semantic context hides all roles, not only the edited endpoint.
 await editor.fill(actual.writing.content.replace('사랑과 희생','자유와 선택'));
 assert.equal(await mirror.locator('.argument-claim,.argument-evidence,.argument-link').count(),0);
 await page.getByText('본문 또는 문맥이 바뀌어 주장·근거 표시를 숨겼습니다. 재분석하면 새 관계를 표시합니다.',{exact:true}).waitFor();
 await editor.fill(actual.writing.content);
 await mirror.locator('.argument-claim').waitFor();
 await editor.fill(actual.writing.content.replace('꽃을 지킨다','잎을 버린다'));
 assert.equal(await page.locator('.argument-editor-controls .argument-link').count(),0);
 await page.screenshot({path:dir+`/${theme}-${width}-stale.png`,fullPage:true});
 await editor.fill(actual.writing.content);
 await page.getByRole('button',{name:'책으로 읽기',exact:true}).click();
 const next=page.getByRole('button',{name:'다음 페이지',exact:true});
 let steps=0;while(!await page.locator('.page-body .argument-link').count()) {assert.ok(++steps<30);assert.equal(await next.isDisabled(),false);await next.click()}
 assert.ok(Number(await page.locator('.reading-page').first().getAttribute('data-start'))>claim.span.start);
 await page.screenshot({path:dir+`/${theme}-${width}-evidence-page.png`,fullPage:true});
 const bookArrow=page.locator('.page-body .argument-link').first();
 if(width===390)await bookArrow.tap();else {await bookArrow.focus();await page.keyboard.press('Enter')}
 assert.equal(Number(await page.locator('.reading-page').first().getAttribute('data-start')),0);
 await page.locator('.page-body .argument-focused').waitFor();
 assert.equal(await page.locator('.page-body .argument-focused').evaluate(e=>e===document.activeElement),true);
 await page.screenshot({path:dir+`/${theme}-${width}-claim-page.png`,fullPage:true});
 // Exact full-body reconstruction also checks page cuts through annotations.
 let reconstructed='';if(!smoke)for(;;){
  reconstructed+=await page.locator('.page-body .argument-fragment').evaluateAll(es=>es.map(e=>e.textContent).join(''));
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
  assert.ok(await page.locator('.page-body').evaluateAll(es=>es.every(e=>e.scrollHeight<=e.clientHeight+1)));
  pagesChecked++;if(await next.isDisabled())break;await next.click();
 }
 if(!smoke){assert.equal(reconstructed,actual.analysis.sourceVersion.content);assert.equal(Array.from(reconstructed).length,30000);}
 checks.push({theme,width,actualKiwiFixture:true,claimHighlight:true,evidenceUnderline:true,linkedArrowsOnly:true,editorCursorPreserved:true,previousPageClaimJump:true,keyboardOrTouch:true,staleClaimEvidence:true,bodyCodePoints:30000,overflow:false});
 data=structuredClone(empty);await page.goto(base);await page.getByRole('button',{name:new RegExp(data.writing.title)}).first().click();
 assert.equal(await page.locator('.argument-claim,.argument-evidence,.argument-link').count(),0);
 await context.close();
 }
 assert.deepEqual(errors,[]);fs.writeFileSync(dir+(smoke?'/browser-final-results.json':'/browser-results.json'),JSON.stringify({status:'PASS',mode:'ACTUAL_ISOLATED_KIWI_RESULT_BROWSER_TRANSPORT_FIXTURE',checks,errors,pagesChecked,fullReconstruction:!smoke},null,2));console.log(JSON.stringify({status:'PASS',cases:checks.length,pagesChecked,errors:errors.length}));
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
