// Actual HTTPS Flask API + isolated SQLite; no intercepted or simulated API responses.
const {chromium}=require(process.env.PLAYWRIGHT_PACKAGE || 'C:/Users/USER/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const base=process.env.V2_QA_URL || 'https://localhost:8768';
const dir=path.resolve(process.env.V2_ARTIFACT_ROOT || 'artifacts/ui-v2');fs.mkdirSync(dir,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});
 try {
 assert.ok(/^https:\/\/(?:127\.0\.0\.1|localhost):(8766|8768)$/.test(base),'synthetic loopback QA only');
 const reset=await browser.newContext({ignoreHTTPSErrors:true});await reset.request.get(base+'/__qa__/session/admin');const as=(await(await reset.request.get(base+'/api/auth/session')).json()).data;for(const u of (await(await reset.request.get(base+'/api/admin/users')).json()).data){if(u.status==='INACTIVE')await reset.request.patch(base+'/api/admin/users/'+u.id,{headers:{'X-CSRF-Token':as.csrfToken},data:{status:'ACTIVE'}});}await reset.close();
 const ctx=await browser.newContext({ignoreHTTPSErrors:true,viewport:{width:1440,height:1000},acceptDownloads:true});
 await ctx.request.get(base+'/__qa__/session/student');
 const session=(await (await ctx.request.get(base+'/api/auth/session')).json()).data;const headers={'X-CSRF-Token':session.csrfToken};
 const metrics=[],shots=[],errors=[];
 const api=async(method,url,data)=>{const r=await ctx.request.fetch(base+'/api'+url,{method,headers,data});assert.ok(r.ok(),method+' '+url+' '+r.status()+' '+await r.text());return (await r.json()).data};
 const document=await ctx.request.post(base+'/api/source-documents',{headers,multipart:{file:{name:'synthetic-source.txt',mimeType:'text/plain',buffer:Buffer.from('달빛은 숲을 비춘다.')}}});assert.ok(document.ok());const source=(await document.json()).data;
 const body=Array.from(('나는 몇일 동안 의미가 있다고 생각했다. 😀 漢字 “달빛은 숲을 비춘다.” 라는 구절을 골랐다.\n\n'+Array.from({length:90},(_,i)=>`${i+1}. 가상의 인물은 숲을 걸으며 나무와 하늘을 보았다. 풍경의 색과 소리를 천천히 기록하며 자신의 선택을 돌아보았다.\n\n`.repeat(7)).join(''))).slice(0,30000).join('');
 const w=await api('POST','/writings',{title:'API 통합 · 30,000자 · '+Date.now(),content:body,inquiryQuestion:'가상의 인물의 선택은 어떤 의미가 있는가?'});
 await api('POST','/writings/'+w.id+'/documents',{revisionId:source.latestRevisionId});
 const t0=Date.now();const ids=await api('POST','/analyses',{writingId:w.id,content:body,revisionNumber:w.revisionNumber});
 for(let i=0;i<120;i++){const job=await api('GET','/analysis-jobs/'+ids.jobId);if(job.status==='completed')break;assert.notEqual(job.status,'failed');await new Promise(r=>setTimeout(r,250));}
 metrics.push({name:'analysis30000',ms:Date.now()-t0,codePoints:Array.from(body).length});
 const result=await api('GET','/analyses/'+ids.analysisId);assert.equal(result.sourceVersion.content,body);assert.equal(result.status,'completed');
 let currentAnalysisId=ids.analysisId;let runCount=1;
 const page=await ctx.newPage();page.on('pageerror',e=>errors.push(e.message));
 const shot=async name=>{await page.screenshot({path:path.join(dir,name+'.png')});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,name+' horizontal overflow');shots.push(name);};
 for(const width of [1440,1024,820,390,320]){
   await api('PATCH','/settings',{theme:'default',pageAnimation:false});await page.setViewportSize({width,height:1000});await page.goto(base);
   const card=page.getByRole('button',{name:new RegExp(w.title)}).first();await card.waitFor();await shot('default-home-'+width);await card.click();
   const editor=page.getByRole('textbox',{name:'에세이 본문'});await editor.waitFor();assert.equal(await editor.inputValue(),body);await shot('default-editor-'+width);
   if(width===1440){const started=page.waitForResponse(r=>r.url().endsWith('/api/analyses') && r.request().method()==='POST');await page.getByRole('button',{name:'분석하기',exact:true}).click();const response=await started;assert.equal(response.status(),202);const next=(await response.json()).data;currentAnalysisId=next.analysisId;runCount++;assert.equal(next.essayVersionId,ids.essayVersionId);await page.getByRole('button',{name:'분석하기',exact:true}).waitFor();await page.waitForFunction(id=>document.querySelector('.version-select select')?.value===id,currentAnalysisId);}
   await page.locator('.writing-more > summary').click();
   await page.getByLabel('자료 판본 연결').selectOption(source.latestRevisionId);
   await page.locator('.writing-more > summary').click();
   const quote=page.getByText('선택한 판본에서 일치 구간 발견',{exact:true}).first();await quote.waitFor();await quote.locator('..').getByRole('button',{name:/원문으로 이동/}).click();assert.equal(await editor.evaluate(e=>e.value.slice(e.selectionStart,e.selectionEnd)),'달빛은 숲을 비춘다.');
   await page.getByRole('button',{name:/원문으로 이동/}).first().click();assert.equal(await editor.evaluate(e=>e.value.slice(e.selectionStart,e.selectionEnd)),'몇일');await shot('default-feedback-'+width);
   await page.getByPlaceholder('본문에서 찾기').fill('풍경');
   await page.getByRole('button',{name:'화면 설정',exact:true}).first().click();await shot('settings-'+width);await page.getByRole('button',{name:/책장 테마/}).click();await page.getByRole('button',{name:'닫기',exact:true}).click();
   await page.getByRole('button',{name:'← 서재로 돌아가기',exact:true}).click();await shot('bookshelf-'+width);await page.getByRole('button',{name:new RegExp(w.title)}).first().click();await page.getByLabel('책 본문. 좌우 방향키로 페이지 이동').waitFor();await shot('book-open-'+width);
   await page.getByRole('button',{name:'다음 페이지',exact:true}).click();await shot('book-turn-'+width);
   await page.getByRole('button',{name:/원문으로 이동/}).first().click();assert.equal(await page.locator('.page-body mark').first().textContent(),'몇일');await shot('book-feedback-'+width);
   assert.equal((await api('GET','/writings/'+w.id)).id,w.id);assert.equal((await api('GET','/writings/'+w.id)).analysisRuns.length,runCount);
   // Traverse every spread; complete source text must survive actual backend+book pagination.
   let rebuilt='';for(;;){rebuilt+=await page.locator('.page-body').evaluateAll(es=>es.map(e=>e.textContent).join(''));const next=page.getByRole('button',{name:'다음 페이지',exact:true});if(await next.isDisabled())break;await next.click();}
   assert.equal(rebuilt,body,'complete 30000 code points at '+width);
 }
 await page.setViewportSize({width:1440,height:1000});
 await page.locator('.writing-more > summary').click();
 const downloadPromise=page.waitForEvent('download');await page.getByRole('button',{name:'PDF 저장',exact:true}).click();const download=await downloadPromise;await download.saveAs(path.join(dir,'synthetic-report.pdf'));
 assert.ok(fs.readFileSync(path.join(dir,'synthetic-report.pdf')).subarray(0,5).equals(Buffer.from('%PDF-')));
 await page.getByRole('button',{name:'← 서재로 돌아가기',exact:true}).click();await page.getByRole('button',{name:'PDF 가져오기',exact:true}).first().click();await page.locator('input[type=file]').setInputFiles(path.join(dir,'synthetic-report.pdf'));await page.getByRole('button',{name:'본문 추출',exact:true}).click();await page.getByRole('textbox',{name:'추출한 본문'}).waitFor();assert.equal(await page.getByRole('textbox',{name:'추출한 본문'}).inputValue(),body);await shot('pdf-import-preview');await page.getByRole('button',{name:'확인한 본문으로 새 책 만들기',exact:true}).click();await page.getByLabel('책 본문. 좌우 방향키로 페이지 이동').waitFor();
 const list=await api('GET','/writings');const imported=list.find(x=>x.id!==w.id && x.title===w.title);assert.ok(imported);assert.equal(imported.analysisRuns.length,0);
 const conflict=await ctx.request.patch(base+'/api/writings/'+w.id,{headers,data:{content:'stale overwrite forbidden',revisionNumber:0}});assert.equal(conflict.status(),409);assert.equal((await api('GET','/writings/'+w.id)).content,body);
 const anonymous=await browser.newContext({ignoreHTTPSErrors:true});const loginPage=await anonymous.newPage();await loginPage.goto(base);await loginPage.getByRole('link',{name:'Google 로그인'}).waitFor();assert.equal((await anonymous.request.get(base+'/api/auth/login')).status(),503);await loginPage.screenshot({path:path.join(dir,'login-external-pending.png')});await anonymous.close();
 const other=await browser.newContext({ignoreHTTPSErrors:true});await other.request.get(base+'/__qa__/session/admin');assert.equal((await other.request.get(base+'/api/analyses/'+ids.analysisId)).status(),404);
 const adminSession=(await(await other.request.get(base+'/api/auth/session')).json()).data;
 await page.getByRole('button',{name:'편집하기',exact:true}).click();const draftEditor=page.getByRole('textbox',{name:'에세이 본문'});await draftEditor.waitFor();
 const disabled=await other.request.patch(base+'/api/admin/users/'+session.id,{headers:{'X-CSRF-Token':adminSession.csrfToken},data:{status:'INACTIVE'}});assert.ok(disabled.ok());
 const retained='저장 실패 시 유지할 합성 초안\n'+body;await draftEditor.fill(retained);await page.locator('.writing-more > summary').click();await page.getByRole('button',{name:'저장',exact:true}).click();await page.getByRole('link',{name:'Google 로그인',exact:true}).waitFor();assert.equal(await page.locator('textarea[aria-label="에세이 본문"]').inputValue(),retained);assert.equal((await ctx.request.get(base+'/api/writings/'+w.id)).status(),401);await shot('revoked-session-draft-retained');
 const active=await other.request.patch(base+'/api/admin/users/'+session.id,{headers:{'X-CSRF-Token':adminSession.csrfToken},data:{status:'ACTIVE'}});assert.ok(active.ok());
 await ctx.request.get(base+'/__qa__/session/student');await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await page.getByRole('link',{name:'Google 로그인',exact:true}).waitFor({state:'hidden'});assert.equal(await draftEditor.inputValue(),retained);await other.close();
 await ctx.request.get(base+'/__qa__/session/other');await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await page.waitForFunction(()=>!document.querySelector('textarea[aria-label="에세이 본문"]'));await page.locator('.shelves.empty').waitFor();assert.equal(await page.getByRole('button',{name:new RegExp(w.title)}).count(),0);await shot('switched-user-library-isolated');
 assert.deepEqual(errors,[]);
 fs.writeFileSync(path.join(dir,'evidence.json'),JSON.stringify({actualApi:true,isolated:true,widths:[1440,1024,820,390,320],screenshots:shots,metrics,errors,essayId:w.id,analysisId:currentAnalysisId,importedId:imported.id},null,2));
 console.log(JSON.stringify({status:'PASS',screenshots:shots.length,metrics,errors:0}));
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
