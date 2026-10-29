// Chrome UI over actual isolated API/Kiwi fixtures; CRUD transport is simulated.
const {chromium}=require('C:/Users/USER/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const dir=path.resolve('artifacts/annotations'),fixture=JSON.parse(fs.readFileSync(dir+'/api-fixture.json','utf8')),base='http://127.0.0.1:8447';
(async()=>{const browser=await chromium.launch({channel:'chrome',headless:true});const checks=[],errors=[];
try{for(const theme of ['default','bookshelf'])for(const width of [1440,820,390]){
 const context=await browser.newContext({viewport:{width,height:1000},hasTouch:width===390});let data=structuredClone(fixture),failPatch=false,expirePatch=false,sequence=0;
 await context.route('**/*',async route=>{
  const r=route.request(),u=new URL(r.url());if(u.origin!==base)return route.abort();if(!u.pathname.startsWith('/api/'))return route.continue();
  const p=u.pathname;let value=[];
  if(p==='/api/auth/session')value={id:'synthetic-note-user',role:'USER',status:'ACTIVE',csrfToken:'synthetic-only'};
  else if(p==='/api/settings')value={theme,pageAnimation:false};
  else if(p==='/api/workspace')value={workspaceName:'주석 격리 검증'};
  else if(p==='/api/writings')value=[data.writing];
  else if(p==='/api/writings/'+data.writing.id){if(r.method()==='PATCH')data.writing={...data.writing,...r.postDataJSON(),revisionNumber:data.writing.revisionNumber+1};value=data.writing;}
  else if(p==='/api/analyses/'+data.analysis.id)value=data.analysis;
  else if(p.endsWith('/versions'))value=data.versions;
  else if(p.endsWith('/annotations')){
   if(r.method()==='POST'){const b=r.postDataJSON();value={...b,id:'note-'+(++sequence),writingId:data.writing.id,revisionNumber:1,createdAt:new Date().toISOString(),updatedAt:new Date().toISOString(),originalAnchor:{essayVersionId:b.essayVersionId,span:b.span,quote:b.quote}};data.annotations.push(value)}else value=data.annotations;
  }else if(p.startsWith('/api/annotations/')){
   const id=p.split('/').at(-1),n=data.annotations.find(x=>x.id===id);
   if(r.method()==='PATCH'){
    if(expirePatch){expirePatch=false;return route.fulfill({status:401,json:{error:{code:'ACCESS_DENIED',message:'인증 필요'}}})}
    if(failPatch){failPatch=false;return route.fulfill({status:503,json:{error:{code:'TEST_NETWORK_FAILURE',message:'저장 실패: 입력을 보존하세요.'}}})}
    Object.assign(n,r.postDataJSON(),{revisionNumber:n.revisionNumber+1});value=n;
   }else if(r.method()==='DELETE'){data.annotations=data.annotations.filter(x=>x.id!==id);value={deleted:true}}else value=n;
  }
  await route.fulfill({json:{data:value}});
 });
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 async function open(){await page.goto(base);await page.getByRole('button',{name:new RegExp(data.writing.title)}).first().click();await page.getByRole('region',{name:'내 주석',exact:true}).waitFor();await page.evaluate(()=>document.fonts.ready)}
 await open();const panel=page.getByRole('region',{name:'내 주석',exact:true});
 if(theme==='bookshelf')await page.getByRole('button',{name:'편집하기',exact:true}).click();
 const editor=page.getByRole('textbox',{name:'에세이 본문'});await editor.waitFor();
 await editor.focus();await page.keyboard.press('Control+Home');await page.keyboard.press('Shift+ArrowRight');await page.keyboard.press('Shift+ArrowRight');
 await page.getByRole('button',{name:'주석 추가',exact:true}).click();
 const input=page.getByRole('textbox',{name:'주석 내용',exact:true});await input.waitFor();assert.equal(await page.getByRole('button',{name:'주석 저장',exact:true}).isDisabled(),true);
 await input.fill('첫 주장에 대한 내 해석');await page.getByRole('button',{name:'주석 저장',exact:true}).click();
 await page.getByText('주석 저장 완료',{exact:true}).waitFor();assert.equal(data.annotations.length,2);assert.deepEqual(data.annotations[1].span,{start:0,end:2});assert.equal(data.annotations[1].quote,'😀 ');
 await input.fill('실패해도 남아 있는 메모');failPatch=true;await page.getByRole('button',{name:'주석 저장',exact:true}).click();await page.getByText('저장 실패: 입력을 보존하세요.',{exact:true}).waitFor();assert.equal(await input.inputValue(),'실패해도 남아 있는 메모');
 await page.getByRole('button',{name:'주석 저장',exact:true}).click();await page.getByText('주석 저장 완료',{exact:true}).waitFor();
 expirePatch=true;await input.fill('세션 만료에도 입력 보존');await page.getByRole('button',{name:'주석 저장',exact:true}).click();await page.getByText('로그인 세션이 만료되었습니다. 입력을 보존했습니다.',{exact:true}).waitFor();assert.equal(await input.inputValue(),'세션 만료에도 입력 보존');await input.fill('실패해도 남아 있는 메모');await page.getByRole('button',{name:'주석 저장',exact:true}).click();await page.getByText('주석 저장 완료',{exact:true}).waitFor();
 await page.screenshot({path:dir+`/${theme}-${width}-editor.png`});
 await open();if(theme==='bookshelf')await page.getByRole('button',{name:'편집하기',exact:true}).click();
 assert.equal(await panel.locator('.annotation-list-item').count(),2);
 await panel.locator('.annotation-list-item').last().click();assert.equal(await input.inputValue(),'실패해도 남아 있는 메모');
 await page.getByRole('button',{name:'주석 삭제',exact:true}).click();await page.getByRole('button',{name:'삭제 확인',exact:true}).click();assert.equal(data.annotations.length,1);
 // Prefix edit maps the unchanged target; overlap edit must hide it.
 const before=data.writing.content;await editor.focus();await page.keyboard.press('Control+Home');await page.keyboard.insertText('앞에 추가. ');
 assert.ok(await panel.getByText('정상 연결',{exact:true}).count());
 await editor.fill('대상 구절을 모두 수정했습니다.');await panel.getByText('현재 본문에서 위치 확인 필요',{exact:true}).waitFor();assert.equal(await page.locator('.argument-editor-controls .annotation-icon').count(),0);
 await page.screenshot({path:dir+`/${theme}-${width}-stale.png`});data.writing.content=before;
 await open();if(theme==='default')await page.getByRole('button',{name:'책으로 읽기',exact:true}).click();
 const original=data.annotations[0];await panel.locator('.annotation-list-item').first().click();
 assert.ok(await page.locator('.reading-page').evaluateAll((es,target)=>es.some(e=>Number(e.dataset.start)<=target && Number(e.dataset.end)>=target),original.span.end));
 const icon=page.locator('.annotation-book-layer .annotation-icon').first();await icon.waitFor();if(width===390)await icon.tap();else{await icon.focus();await page.keyboard.press('Enter')}
 await input.waitFor();assert.equal(await input.inputValue(),original.content);
 assert.ok(await page.locator('.page-body .argument-evidence').count()>0);assert.ok(await page.locator('.page-body .argument-link').count()>0);
 await page.screenshot({path:dir+`/${theme}-${width}-book.png`});
 // Navigate first page and select text by DOM offsets (not text matching).
 const prev=page.getByRole('button',{name:'이전 페이지',exact:true});for(let n=0;n<30 && !await prev.isDisabled();n++)await prev.click();
 await page.evaluate(()=>{const f=document.querySelector('.page-body .argument-fragment'),t=f.firstChild,r=document.createRange();r.setStart(t,0);r.setEnd(t,Math.min(2,t.length));const s=getSelection();s.removeAllRanges();s.addRange(r);document.querySelector('.reading-book').dispatchEvent(new MouseEvent('mouseup',{bubbles:true}))});
 await page.getByRole('button',{name:'주석 추가',exact:true}).click();await input.fill('책에서도 같은 원문에 작성');await page.getByRole('button',{name:'주석 저장',exact:true}).click();await page.getByText('주석 저장 완료',{exact:true}).waitFor();
 assert.equal(data.annotations.length,2);assert.equal(data.annotations[1].essayVersionId,data.analysis.sourceVersion.id);
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
 assert.equal(data.writing.content,fixture.writing.content);
 if(theme==='bookshelf' && width===390){
  let reconstructed='',pages=0;const next=page.getByRole('button',{name:'다음 페이지',exact:true});
  for(;;){reconstructed+=await page.locator('.page-body .argument-fragment').evaluateAll(es=>es.map(e=>e.textContent).join(''));pages++;assert.ok(await page.locator('.page-body').evaluateAll(es=>es.every(e=>e.scrollHeight<=e.clientHeight+1)));if(await next.isDisabled())break;await next.click()}
  assert.equal(reconstructed,fixture.writing.content);fs.writeFileSync(dir+'/long-book-results.json',JSON.stringify({status:'PASS',pages,codePoints:Array.from(reconstructed).length,mode:'BOOK_WITH_ANNOTATION_MARKS_EXACT_RECONSTRUCTION'},null,2));
 }
 checks.push({theme,width,selectionExactUnicode:true,crud:true,refresh:true,failureDraftPreserved:true,stale:true,prefixMapped:true,bookSelection:true,otherPageJump:true,keyboardOrTouch:true,claimEvidenceCoexist:true,overflow:false,bodyCodePoints:Array.from(data.writing.content).length});
 if(theme==='default' && width===1440){
  const origin=structuredClone(data.annotations[0].originalAnchor);
  Object.assign(data,structuredClone(fixture.relinkScenario));await open();await panel.locator('.annotation-list-item').first().click();
  await editor.focus();await page.keyboard.press('Control+Home');for(let i=0;i<3;i++)await page.keyboard.press('Shift+ArrowRight');
  await page.getByRole('button',{name:'선택 구절에 다시 연결',exact:true}).click();await page.getByText('주석 저장 완료',{exact:true}).waitFor();
  assert.equal(data.annotations[0].essayVersionId,data.analysis.sourceVersion.id);assert.deepEqual(data.annotations[0].originalAnchor,origin);
  await panel.getByText('정상 연결',{exact:true}).first().waitFor();checks.at(-1).explicitRelinkPreservesOrigin=true;
 }
 await context.close();
 }
 assert.deepEqual(errors,[]);fs.writeFileSync(dir+'/browser-results.json',JSON.stringify({status:'PASS',mode:'ACTUAL_ISOLATED_API_KIWI_FIXTURE_WITH_SIMULATED_CRUD_TRANSPORT',checks,errors},null,2));console.log(JSON.stringify({status:'PASS',cases:checks.length,errors:errors.length}));
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
