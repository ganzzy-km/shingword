// Actual isolated API + Chrome touch emulation. Physical iPad/phone gestures are not asserted.
const {chromium}=require('C:/Users/USER/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const base='https://localhost:8768',dir=path.resolve('artifacts/mobile');fs.mkdirSync(dir,{recursive:true});
const source=JSON.parse(fs.readFileSync('artifacts/argument-links/kiwi-fixture.json','utf8')).analysis.sourceVersion.content;
const text=Array.from(source).slice(0,30000).join('');assert.equal(Array.from(text).length,30000);
const sizes=[{width:1024,height:768,name:'tablet-landscape'},{width:820,height:1180,name:'tablet-portrait'},{width:768,height:1024,name:'tablet-small'},
 {width:390,height:844,name:'phone'},{width:320,height:640,name:'phone-small'},{width:844,height:390,name:'phone-landscape'}];
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true}),checks=[],errors=[],screenshots=[];let active;
 try{
 for(const theme of ['default','bookshelf'])for(const size of sizes){
  const context=await browser.newContext({ignoreHTTPSErrors:true,viewport:{width:size.width,height:size.height},hasTouch:true,isMobile:true,deviceScaleFactor:1,acceptDownloads:true});
  await context.request.get(base+'/__qa__/session/load-02');
  const auth=(await(await context.request.get(base+'/api/auth/session')).json()).data,headers={'X-CSRF-Token':auth.csrfToken};
  const api=async(method,url,data)=>{const response=await context.request.fetch(base+'/api'+url,{method,headers,data});assert.ok(response.ok(),method+' '+url+' '+response.status());return (await response.json()).data};
  await api('PATCH','/settings',{theme,pageAnimation:false});
  const writing=await api('POST','/writings',{title:`반응형 가상 글 ${theme} ${size.name} ${Date.now()}`,content:text,inquiryQuestion:'작품에서 드러나는 사랑과 희생의 의미는 무엇인가?'});
  const run=await api('POST','/analyses',{writingId:writing.id,content:text,revisionNumber:writing.revisionNumber});
  for(let i=0;i<100;i++){const job=await api('GET','/analysis-jobs/'+run.jobId);if(job.status==='completed')break;assert.notEqual(job.status,'failed');await new Promise(r=>setTimeout(r,200))}
  const analysis=await api('GET','/analyses/'+run.analysisId);assert.equal(analysis.status,'completed');assert.equal(analysis.sourceVersion.content,text);
  const page=await context.newPage();active=page;page.on('pageerror',e=>errors.push(e.message));
  const shot=async(stage)=>{const name=`${theme}-${size.width}x${size.height}-${stage}.png`;await page.screenshot({path:path.join(dir,name)});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,name+' overflow');screenshots.push(name)};
  await page.goto(base);await page.evaluate(()=>document.fonts.ready);await page.getByRole('button',{name:new RegExp(writing.title)}).first().waitFor();await shot('home');
  await page.getByRole('button',{name:new RegExp(writing.title)}).first().tap();if(theme==='bookshelf')await page.getByRole('button',{name:'편집하기',exact:true}).tap();
  const editor=page.getByRole('textbox',{name:'에세이 본문'});await editor.waitFor();assert.equal(await editor.inputValue(),text);
  const bodyColumn=await page.locator('.document-column').boundingBox();assert.ok(bodyColumn.width>=size.width-110,'tablet editor uses full available width');
  const dock=page.getByRole('navigation',{name:'글 작업 바로 이동'});await dock.waitFor();
  const dockButtons=await dock.getByRole('button').evaluateAll(nodes=>nodes.map(n=>({width:n.getBoundingClientRect().width,height:n.getBoundingClientRect().height})));
  assert.ok(dockButtons.every(b=>b.width>=44 && b.height>=44));
  if(size.width<=820){assert.ok(await page.locator('.essay-fields input').evaluateAll(nodes=>nodes.every(n=>parseFloat(getComputedStyle(n).fontSize)>=16)));}
  await editor.focus();await page.keyboard.press('Control+Home');await page.keyboard.press('Shift+ArrowRight');await page.keyboard.press('Shift+ArrowRight');
  await page.getByRole('button',{name:'주석 추가',exact:true}).tap();const noteInput=page.getByRole('textbox',{name:'주석 내용',exact:true});await noteInput.fill('모바일에서 직접 작성한 주석');
  const created=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/annotations'));await page.getByRole('button',{name:'주석 저장',exact:true}).tap();assert.equal((await created).status(),201);
  const notes=await api('GET','/writings/'+writing.id+'/annotations');assert.equal(notes.length,1);assert.deepEqual(notes[0].span,{start:0,end:2});
  const panel=page.getByRole('region',{name:'내 주석',exact:true});
  await dock.getByRole('button',{name:/본문/}).tap();await editor.waitFor();await shot('editor');
  await dock.getByRole('button',{name:/분석 결과/}).tap();await page.getByRole('complementary',{name:'분석 결과와 내 주석'}).waitFor();
  const panelBox=await page.locator('.feedback-panel').boundingBox();assert.ok(panelBox.y>=50 && panelBox.y<size.height-90,'result shortcut exposes content below header');
  await dock.getByRole('button',{name:/내 주석/}).tap();assert.equal(await noteInput.inputValue(),'모바일에서 직접 작성한 주석');await shot('notes');
  await noteInput.fill('태블릿과 휴대폰에서 수정한 주석');const edited=page.waitForResponse(r=>r.request().method()==='PATCH'&&r.url().endsWith('/annotations/'+notes[0].id));await panel.getByRole('button',{name:'주석 저장',exact:true}).tap();assert.equal((await edited).status(),200);
  await page.getByRole('button',{name:'책으로 읽기',exact:true}).tap();const book=page.getByLabel('책 본문. 좌우 방향키로 페이지 이동');await book.waitFor();
  await book.evaluate(n=>n.scrollIntoView({block:'start'}));await page.waitForTimeout(60);
  const count=await page.locator('.reading-page').count();assert.equal(count,size.width<=820?1:2);
  const evidence=analysis.argumentCandidates.find(c=>c.roles.includes('EVIDENCE_CANDIDATE'));
  const otherNote=await api('POST','/writings/'+writing.id+'/annotations',{essayVersionId:analysis.sourceVersion.id,span:evidence.span,quote:evidence.quote,content:'근거 위치의 가상 주석'});
  // Refresh proves note persistence; the same version/run and real API are retained.
  await page.reload();await page.getByRole('button',{name:new RegExp(writing.title)}).first().tap();if(theme==='default')await page.getByRole('button',{name:'책으로 읽기',exact:true}).tap();
  await dock.getByRole('button',{name:/내 주석/}).tap();await panel.locator('.annotation-list-item').filter({hasText:'근거 위치의 가상 주석'}).tap();
  await dock.getByRole('button',{name:/본문/}).tap();await page.locator('.annotation-book-layer .annotation-icon').first().tap();
  await dock.getByRole('button',{name:/본문/}).tap();await page.locator('.page-body .argument-link').first().tap();
  await page.locator('.page-body .argument-focused').first().waitFor();assert.equal(Number(await page.locator('.reading-page').first().getAttribute('data-start')),0);
  await book.evaluate(n=>n.scrollIntoView({block:'start'}));await shot('book');
  const next=page.getByRole('button',{name:'다음 페이지',exact:true});await next.tap();await page.getByRole('button',{name:'이전 페이지',exact:true}).tap();
  assert.equal(Number(await page.locator('.reading-page').first().getAttribute('data-start')),0);
  if(theme==='bookshelf'&&[820,390].includes(size.width)){let reconstructed='',pageCount=0;for(;;){reconstructed+=await page.locator('.page-body .argument-fragment').evaluateAll(nodes=>nodes.map(n=>n.textContent).join(''));pageCount++;assert.ok(await page.locator('.page-body').evaluateAll(nodes=>nodes.every(n=>n.scrollHeight<=n.clientHeight+1)));if(await next.isDisabled())break;await next.click()};assert.equal(reconstructed,text);checks.push({theme,size:size.name,paginationPages:pageCount,codePoints:30000});}
  await page.getByRole('button',{name:'화면 설정',exact:true}).first().tap();const modal=page.getByRole('dialog',{name:'설정'});await modal.waitFor();assert.equal(await page.locator('.mobile-work-nav').evaluate(n=>n.inert),true);await shot('settings');await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'메뉴 펼치기',exact:true}).tap();await page.getByRole('dialog',{name:'글빛 메뉴'}).waitFor();assert.equal(await page.locator('.mobile-work-nav').evaluate(n=>n.inert),true);await shot('menu');await page.keyboard.press('Escape');assert.equal(await page.getByRole('button',{name:'메뉴 펼치기',exact:true}).getAttribute('aria-expanded'),'false');assert.equal(await dock.evaluate(n=>n.inert),false);
  await dock.getByRole('button',{name:/내 주석/}).tap();await panel.getByRole('button',{name:'주석 삭제',exact:true}).tap();const removed=page.waitForResponse(r=>r.request().method()==='DELETE'&&r.url().endsWith('/annotations/'+otherNote.id));await panel.getByRole('button',{name:'삭제 확인',exact:true}).tap();assert.equal((await removed).status(),200);
  const latest=await api('GET','/writings/'+writing.id);assert.equal(latest.content,text);assert.equal(latest.analysisRuns.length,1);assert.equal(latest.expiresAt,writing.expiresAt);
  checks.push({theme,size:size.name,width:size.width,height:size.height,actualApi:true,touchEmulation:true,bodyPreserved:true,annotationCrud:true,arrowJump:true,shortcuts:true,dockTargets44:true,settingsAndDrawer:true,singlePagePortrait:size.width<=820});await context.close();
 }
 assert.deepEqual(errors,[]);fs.writeFileSync(path.join(dir,'responsive-results.json'),JSON.stringify({status:'PASS',mode:'ACTUAL_ISOLATED_HTTP_API_CHROME_TOUCH_EMULATION',flows:12,checks,screenshots,errors,physicalMobile:'UNVERIFIED',physicalSoftKeyboard:'UNVERIFIED'},null,2));console.log(JSON.stringify({status:'PASS',flows:12,screenshots:screenshots.length,errors:errors.length}));
 }catch(e){if(active&&!active.isClosed()){await active.screenshot({path:path.join(dir,'failure.png')});fs.writeFileSync(path.join(dir,'failure.json'),JSON.stringify({visibleErrors:await active.locator('.gb-error').allTextContents()},null,2))}throw e}finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
