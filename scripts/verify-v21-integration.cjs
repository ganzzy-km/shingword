// Actual loopback HTTPS -> Waitress -> Flask -> isolated SQLite/Kiwi. No API mocks.
const {chromium}=require('C:/Users/USER/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const base='https://localhost:8768',dir=path.resolve(process.env.V21_ARTIFACT_ROOT || 'artifacts/v21');fs.mkdirSync(dir,{recursive:true});
const old=JSON.parse(fs.readFileSync('artifacts/argument-links/kiwi-fixture.json','utf8'));
const text=Array.from(old.analysis.sourceVersion.content.replace('독자는 천천히 낱말을 읽고 문장을 살핀다.','곰곰 생각한다. 곰곰이 생각한다. 곰곰히 생각한다. 번번히 실패한다. 학생으로써 책임을 진다.')).slice(0,30000).join('');
(async()=>{const browser=await chromium.launch({channel:'chrome',headless:true});const checks=[],errors=[],metrics=[],diagnostics=[];let activePage;
try{for(const theme of ['default','bookshelf'])for(const width of (process.env.V21_WIDTHS || '1440,820,390').split(',').map(Number)){
 const context=await browser.newContext({ignoreHTTPSErrors:true,viewport:{width,height:1000},hasTouch:width===390,acceptDownloads:true});
 await context.request.get(base+'/__qa__/session/load-00');
 const session=(await(await context.request.get(base+'/api/auth/session')).json()).data,headers={'X-CSRF-Token':session.csrfToken};
 async function api(method,p,data){const r=await context.request.fetch(base+'/api'+p,{method,headers,data});assert.ok(r.ok(),method+' '+p+' '+r.status());return (await r.json()).data}
 await api('PATCH','/settings',{theme,pageAnimation:false});
 const t0=Date.now(),writing=await api('POST','/writings',{title:`V2.1 ${theme} ${width} ${Date.now()}`,content:text,inquiryQuestion:'뿌리가 드러내는 사랑과 희생의 의미는 무엇인가?'});
 assert.ok(writing.expiresAt);metrics.push({theme,width,saveMs:Date.now()-t0});
 const page=await context.newPage();activePage=page;page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.status()>=400 && r.url().startsWith(base+'/api/'))diagnostics.push({path:new URL(r.url()).pathname,status:r.status()})});
 async function open(){await page.goto(base);await page.getByRole('button',{name:new RegExp(writing.title)}).first().click();if(theme==='bookshelf')await page.getByRole('button',{name:'편집하기',exact:true}).click();await page.getByRole('textbox',{name:'에세이 본문'}).waitFor();await page.evaluate(()=>document.fonts.ready)}
 async function analyze(){const response=page.waitForResponse(r=>r.url()===base+'/api/analyses' && r.request().method()==='POST');const start=Date.now();await page.getByRole('button',{name:'분석하기',exact:true}).click();const r=await response;assert.equal(r.status(),202);const ids=(await r.json()).data;for(let n=0;n<120;n++){const job=await api('GET','/analysis-jobs/'+ids.jobId);if(job.status==='completed')break;assert.notEqual(job.status,'failed');await new Promise(r=>setTimeout(r,250))}await page.waitForFunction(id=>document.querySelector('.version-select select')?.value===id,ids.analysisId);metrics.push({theme,width,analysisMs:Date.now()-start});return await api('GET','/analyses/'+ids.analysisId)}
 await open();const editor=page.getByRole('textbox',{name:'에세이 본문'}),first=await analyze();assert.equal(first.sourceVersion.content,text);assert.ok(first.argumentLinks.length>0);
 const spelling=first.findings.filter(f=>f.type==='spelling');assert.ok(spelling.some(f=>f.current==='곰곰히' && f.suggestion==='곰곰이'));assert.ok(!spelling.some(f=>f.current==='곰곰' || f.current==='곰곰이'));
 assert.ok(spelling.some(f=>f.current==='번번히' && !f.suggestion && f.severity==='info'));
 const selectEmoji=async()=>{await editor.focus();await page.keyboard.press('Control+Home');await page.keyboard.press('Shift+ArrowRight');await page.keyboard.press('Shift+ArrowRight')};
 await selectEmoji();await page.getByRole('button',{name:'주석 추가',exact:true}).click();const input=page.getByRole('textbox',{name:'주석 내용',exact:true});await input.fill('주장의 표현을 다시 살펴볼 계획');
 const created=page.waitForResponse(r=>r.url().endsWith('/annotations') && r.request().method()==='POST');await page.getByRole('button',{name:'주석 저장',exact:true}).click();assert.equal((await created).status(),201);
 let notes=await api('GET','/writings/'+writing.id+'/annotations');assert.equal(notes.length,1);const origin=structuredClone(notes[0].originalAnchor);assert.deepEqual(notes[0].span,{start:0,end:2});assert.equal(notes[0].quote,'😀 ');
 await input.fill('직접 수정한 주석');const edited=page.waitForResponse(r=>r.url().endsWith('/annotations/'+notes[0].id) && r.request().method()==='PATCH');await page.getByRole('button',{name:'주석 저장',exact:true}).click();assert.equal((await edited).status(),200);
 const unchanged=await api('GET','/writings/'+writing.id);assert.equal(unchanged.content,text);assert.equal(unchanged.analysisRuns.length,1);assert.equal(unchanged.expiresAt,writing.expiresAt);
 const evidence=first.argumentCandidates.find(c=>c.roles.includes('EVIDENCE_CANDIDATE'));
 const evidenceNote=await api('POST','/writings/'+writing.id+'/annotations',{essayVersionId:first.sourceVersion.id,span:evidence.span,quote:evidence.quote,content:'근거와 앞 주장 연결을 확인'});
 await open();const panel=page.getByRole('region',{name:'내 주석',exact:true});await panel.locator('.annotation-list-item').first().click();assert.equal(await input.inputValue(),'직접 수정한 주석');
 if(theme==='default' && width===1440){
  await input.fill('아직 저장하지 않은 개인 주석');page.once('dialog',d=>d.dismiss());await panel.locator('.annotation-list-item').last().click();assert.equal(await input.inputValue(),'아직 저장하지 않은 개인 주석');
  await input.fill('직접 수정한 주석');const saved=page.waitForResponse(r=>r.url().endsWith('/annotations/'+notes[0].id) && r.request().method()==='PATCH');await page.getByRole('button',{name:'주석 저장',exact:true}).click();assert.equal((await saved).status(),200);
 }
 await page.screenshot({path:dir+`/${theme}-${width}-editor.png`});
 await page.getByRole('button',{name:'책으로 읽기',exact:true}).click();await panel.locator('.annotation-list-item').filter({hasText:'근거와 앞 주장 연결을 확인'}).click();
 const icon=page.locator('.annotation-book-layer .annotation-icon').first();await icon.waitFor();if(width===390)await icon.tap();else{await icon.focus();await page.keyboard.press('Enter')}
 const arrow=page.locator('.page-body .argument-link').first();await arrow.waitFor();await page.screenshot({path:dir+`/${theme}-${width}-book.png`});if(width===390)await arrow.tap();else{await arrow.focus();await page.keyboard.press('Enter')}
 assert.equal(Number(await page.locator('.reading-page').first().getAttribute('data-start')),0);await page.locator('.page-body .argument-focused').first().waitFor();
 if(theme==='bookshelf' && width===390){let rebuilt='',pages=0;const next=page.getByRole('button',{name:'다음 페이지',exact:true});for(;;){rebuilt+=await page.locator('.page-body .argument-fragment').evaluateAll(es=>es.map(e=>e.textContent).join(''));pages++;assert.ok(await page.locator('.page-body').evaluateAll(es=>es.every(e=>e.scrollHeight<=e.clientHeight+1)));if(await next.isDisabled())break;await next.click()}assert.equal(rebuilt,text);metrics.push({longBookPages:pages,codePoints:Array.from(rebuilt).length})}
 await page.getByRole('button',{name:'편집하기',exact:true}).click();await editor.focus();await page.keyboard.press('Control+Home');await page.keyboard.press('Delete');await page.keyboard.insertText('🙂');
 const changed=await editor.inputValue();assert.notEqual(changed,text);assert.equal(Array.from(changed).length,30000);assert.equal(await page.locator('.argument-editor-controls .argument-link').count(),0);await panel.getByText('현재 본문에서 위치 확인 필요',{exact:true}).first().waitFor();
 const second=await analyze();assert.notEqual(second.sourceVersion.id,first.sourceVersion.id);assert.equal(second.sourceVersion.content,changed);assert.equal((await api('GET','/analyses/'+first.id)).sourceVersion.content,text);
 notes=await api('GET','/writings/'+writing.id+'/annotations');assert.equal(notes[0].essayVersionId,first.sourceVersion.id);
 await panel.locator('.annotation-list-item').filter({hasText:'직접 수정한 주석'}).click();await selectEmoji();const relink=page.waitForResponse(r=>r.url().endsWith('/annotations/'+notes[0].id) && r.request().method()==='PATCH');await page.getByRole('button',{name:'선택 구절에 다시 연결',exact:true}).click();assert.equal((await relink).status(),200);
 const linked=await api('GET','/annotations/'+notes[0].id);assert.equal(linked.essayVersionId,second.sourceVersion.id);assert.equal(linked.quote,'🙂 ');assert.deepEqual(linked.originalAnchor,origin);
 await page.waitForFunction(quote=>document.querySelector('.annotation-form blockquote')?.textContent===quote,linked.quote);
 await page.screenshot({path:dir+`/${theme}-${width}-reanalyzed.png`});
 const stale=await context.request.patch(base+'/api/annotations/'+notes[0].id,{headers,data:{revisionNumber:1,content:'옛 요청'}});assert.equal(stale.status(),409);assert.equal((await api('GET','/annotations/'+notes[0].id)).content,'직접 수정한 주석');
 await page.locator('.writing-more > summary').click();const pdfStart=Date.now(),downloadPromise=page.waitForEvent('download');await page.getByRole('button',{name:'PDF 저장',exact:true}).click();const download=await downloadPromise;const pdf=dir+`/${theme}-${width}-report.pdf`;await download.saveAs(pdf);assert.equal(fs.readFileSync(pdf).subarray(0,5).toString(),'%PDF-');metrics.push({theme,width,pdfMs:Date.now()-pdfStart});
 const other=await browser.newContext({ignoreHTTPSErrors:true});await other.request.get(base+'/__qa__/session/admin');assert.equal((await other.request.get(base+'/api/annotations/'+notes[0].id)).status(),404);assert.equal((await other.request.get(base+'/api/writings/'+writing.id)).status(),404);assert.equal((await other.request.get(base+'/api/analyses/'+second.id+'/pdf')).status(),404);await other.close();
 assert.equal((await context.request.patch(base+'/api/annotations/'+notes[0].id,{data:{revisionNumber:linked.revisionNumber,content:'CSRF 없는 요청'}})).status(),401);
 await page.getByRole('button',{name:'주석 삭제',exact:true}).click();const deleted=page.waitForResponse(r=>r.url().endsWith('/annotations/'+notes[0].id) && r.request().method()==='DELETE');await page.getByRole('button',{name:'삭제 확인',exact:true}).click();assert.equal((await deleted).status(),200);assert.equal((await api('GET','/writings/'+writing.id+'/annotations')).length,1);
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
 checks.push({theme,width,actualHttpApi:true,actualKiwi:true,syntheticSession:true,analysisAnnotationEditReanalysisPdf:true,unicode:true,stale:true,relinkOriginPreserved:true,annotationRetentionUnchanged:true,themeSameIds:true,ownerAdminDenied:true,csrfDenied:true,arrowsAndNotes:true,keyboardOrTouch:true});
 if(theme==='default' && width===1440){
  const otherWriting=await api('POST','/writings',{title:'늦은 주석 응답 격리 '+Date.now(),inquiryQuestion:'인물의 선택을 어떻게 해석할 수 있는가?',content:'따라서 인물의 선택이 의미한다고 생각한다.\n\n인물이 “떠나겠다.”라고 말했다. 이는 선택의 의미를 보여 준다.'});
  await panel.locator('.annotation-list-item').first().click();await input.fill('늦게 도착한 원래 글의 주석');
  let resume,entered;const queued=new Promise(r=>entered=r);
  await context.route('**/api/annotations/'+evidenceNote.id,async route=>{if(route.request().method()==='PATCH'){entered();await new Promise(r=>resume=r)}await route.continue()});
  const delayed=page.waitForResponse(r=>r.url().endsWith('/annotations/'+evidenceNote.id) && r.request().method()==='PATCH');await page.getByRole('button',{name:'주석 저장',exact:true}).click();await queued;
  await page.getByRole('button',{name:'← 서재로 돌아가기',exact:true}).click();await page.getByRole('button',{name:new RegExp(otherWriting.title)}).first().click();await editor.waitFor();assert.equal(await editor.inputValue(),otherWriting.content);
  resume();assert.equal((await delayed).status(),200);await page.waitForTimeout(100);
  assert.equal(await editor.inputValue(),otherWriting.content);
  assert.equal(await page.getByRole('region',{name:'내 주석',exact:true}).count(),0);assert.equal((await api('GET','/writings/'+otherWriting.id+'/annotations')).length,0);assert.equal((await api('GET','/annotations/'+evidenceNote.id)).content,'늦게 도착한 원래 글의 주석');
  checks.at(-1).unsavedNoteSwitchGuard=true;checks.at(-1).delayedResponseEssayIsolation=true;
  const explained=await analyze();assert.equal(explained.structureVersion,'geulbit.structure/3');assert.ok(explained.argumentLinks.some(l=>l.signals.includes('FOLLOWING_QUOTE_EXPLANATION') && l.explanationText==='이는 선택의 의미를 보여 준다.'));
  await page.locator('.argument-editor-controls .argument-link').first().click();await page.getByText('인용 뒤 연결 설명',{exact:true}).waitFor();checks.at(-1).followingExplanationTrace=true;
 }
 await api('POST','/auth/logout');assert.equal((await context.request.get(base+'/api/writings/'+writing.id)).status(),401);await context.close();
 }
 assert.deepEqual(errors,[]);fs.writeFileSync(dir+'/integration-results.json',JSON.stringify({status:'PASS',mode:'ACTUAL_WAITRESS_HTTPS_FLASK_SQLITE_KIWI_SYNTHETIC_AUTH_NO_API_MOCKS',checks,metrics,errors,mobilePhysicalDevice:'UNVERIFIED'},null,2));console.log(JSON.stringify({status:'PASS',cases:checks.length,errors:0,metrics}));
}catch(error){if(activePage && !activePage.isClosed()){await activePage.screenshot({path:dir+'/integration-failure.png'});fs.writeFileSync(dir+'/failure-diagnostics.json',JSON.stringify({diagnostics,visibleErrors:await activePage.locator('.gb-error').allTextContents()},null,2))}throw error}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
