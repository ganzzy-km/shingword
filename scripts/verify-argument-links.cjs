// Browser transport fixtures contain actual isolated Flask/Kiwi output.
// No operating DB, real account or external AI is accessed by this test.
const { chromium }=require(process.env.PLAYWRIGHT_PACKAGE || 'C:/Users/USER/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const smoke=process.env.ARGUMENT_SMOKE_ONLY==='1';
const inputDir=path.resolve(process.env.ARGUMENT_FIXTURE_ROOT || 'artifacts/argument-links');
const dir=path.resolve(process.env.ARGUMENT_ARTIFACT_ROOT || 'artifacts/argument-links'),base=process.env.UI_PREVIEW_URL || 'http://127.0.0.1:8447';

function validateEndpoint(body,endpoint) {
 const points=Array.from(body),span=endpoint?.span;
 assert.ok(span&&Number.isInteger(span.start)&&Number.isInteger(span.end)&&0<=span.start&&span.start<span.end&&span.end<=points.length,'invalid codepoint endpoint');
 assert.equal(points.slice(span.start,span.end).join(''),endpoint.quote,'endpoint quote mismatch');
 return points;
}
function approvedEndpoints(actual) {
 const analysis=actual.analysis,body=actual.writing.content;
 assert.equal(body,analysis.sourceVersion.content,'mutable and immutable bodies differ');
 assert.equal(actual.writing.currentVersionId,analysis.essayVersionId);
 assert.equal(analysis.sourceVersion.id,analysis.essayVersionId);
 assert.equal(actual.writing.latestAnalysisId,analysis.id);
 const link=analysis.argumentLinks.find(r=>r.assessment==='SUFFICIENT_SIGNALS');assert.ok(link,'no approved relation');
 const claim=analysis.argumentCandidates.find(c=>c.id===link.claimId),evidence=analysis.argumentCandidates.find(c=>c.id===link.evidenceId);
 assert.ok(claim&&evidence&&claim.id!==evidence.id,'missing or identical endpoints');
 assert.ok(claim.roles.includes('CLAIM_CANDIDATE')&&evidence.roles.includes('EVIDENCE_CANDIDATE'));
 for(const [name,node] of [['claim',claim],['evidence',evidence]]) {
  validateEndpoint(body,node);
  assert.equal(node.analysisRunId,analysis.id);assert.equal(node.essayVersionId,analysis.essayVersionId);
  assert.deepEqual(node.span,link[name+'Span']);assert.equal(node.quote,link[name+'Text']);
 }
 assert.equal(link.analysisRunId,analysis.id);assert.equal(link.essayVersionId,analysis.essayVersionId);
 return {claim,evidence,link};
}
function editEndpoint(body,endpoint,other,replacement) {
 const points=validateEndpoint(body,endpoint);validateEndpoint(body,other);
 assert.ok(endpoint.span.end<=other.span.start||other.span.end<=endpoint.span.start,'overlapping endpoints');
 let index=-1;
 for(let i=endpoint.span.start;i<endpoint.span.end;i++)if(/[\p{L}\p{N}]/u.test(points[i])&&!/\p{M}/u.test(points[i+1]||'')){index=i;break;}
 assert.ok(index>=0,'no independent editable character');
 const changed=replacement===undefined?(points[index]==='가'?'나':'가'):replacement;
 assert.ok(typeof changed==='string'&&Array.from(changed).length===1&&/[\p{L}\p{N}]/u.test(changed)&&changed!==points[index],'no-op or invalid replacement');
 const edited=[...points];edited[index]=changed;const content=edited.join('');assert.notEqual(content,body);
 assert.equal(edited.length,points.length);
 assert.deepEqual(edited.map((c,i)=>c!==points[i]?i:null).filter(i=>i!==null),[index]);
 assert.ok(endpoint.span.start<=index&&index<endpoint.span.end);
 assert.equal(edited.slice(other.span.start,other.span.end).join(''),other.quote);
 assert.deepEqual(edited.filter(c=>c==='\n'||c==='\r'||/\p{Extended_Pictographic}/u.test(c)),points.filter(c=>c==='\n'||c==='\r'||/\p{Extended_Pictographic}/u.test(c)));
 return {content,index,span:endpoint.span};
}
module.exports={approvedEndpoints,editEndpoint};

async function main(){
const actual=JSON.parse(fs.readFileSync(inputDir+'/kiwi-fixture.json','utf8')),empty=JSON.parse(fs.readFileSync(inputDir+'/empty-fixture.json','utf8'));
const review=JSON.parse(fs.readFileSync(inputDir+'/review-30000-fixture.json','utf8'));
assert.ok(review.analysis.relationCandidates.some(r=>r.assessment==='REQUIRES_REVIEW'));
assert.equal(review.analysis.argumentLinks.length,0);
const {claim,evidence,link}=approvedEndpoints(actual);
const claimEdit=editEndpoint(actual.writing.content,claim,evidence),evidenceEdit=editEndpoint(actual.writing.content,evidence,claim);
fs.mkdirSync(dir,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});const checks=[],errors=[];let pagesChecked=0;
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
  else if(p.startsWith('/api/writing-versions/'))return route.fulfill({status:404,json:{error:{code:'FIXTURE_ROUTE_UNAVAILABLE'}}});
  await route.fulfill({json:{data:value}});
 });
 const page=await context.newPage();
 const screenshot=options=>smoke?Promise.resolve():page.screenshot(options);
 page.on('pageerror',e=>errors.push(e.message));await page.goto(base);
 await page.getByRole('button',{name:new RegExp(data.writing.title)}).first().click();
 if(theme==='bookshelf')await page.getByRole('button',{name:'편집하기',exact:true}).click();
 const editor=page.getByRole('textbox',{name:'에세이 본문'});
 await editor.waitFor();assert.equal(await editor.inputValue(),actual.analysis.sourceVersion.content);
 await page.evaluate(()=>document.fonts.ready);
 const mirror=page.locator('.argument-editor-mirror');assert.equal(await mirror.locator('.argument-claim').count(),1);assert.equal(await mirror.locator('.argument-evidence').count(),1);
 assert.deepEqual(await page.evaluate(()=>{const n=document.querySelector('textarea[aria-label="에세이 본문"]'),m=document.querySelector('.argument-editor-mirror'),a=getComputedStyle(n),b=getComputedStyle(m);return [a.font===b.font,a.padding===b.padding,n.clientWidth===m.clientWidth]}),[true,true,true]);
 await editor.evaluate(node=>{const arrow=document.querySelector('.argument-editor-mirror [data-argument-relation]');const y=arrow.getBoundingClientRect().top-node.getBoundingClientRect().top+node.scrollTop;node.scrollTop=Math.max(0,y-100)});
 const editorArrow=page.locator('.argument-editor-controls .argument-link');await editorArrow.waitFor({state:'visible'});
 await screenshot({path:dir+`/${theme}-${width}-editor.png`});
 if(width===390)await editorArrow.tap();else {await editorArrow.focus();await page.keyboard.press('Enter')}
 await page.getByRole('region',{name:'주장과 근거 연결'}).waitFor();
 assert.equal(await editor.evaluate(n=>n.value.slice(n.selectionStart,n.selectionEnd)),claim.quote);
 await mirror.locator('.argument-focused').waitFor();
 assert.ok(await editor.evaluate(n=>n.scrollTop)<100);
 await screenshot({path:dir+`/${theme}-${width}-claim-editor.png`});
 const work=page.getByPlaceholder('작품명 (선택)',{exact:true}),question=page.getByPlaceholder('이 글에서 탐구하고 싶은 질문',{exact:true});
 await work.fill('다른 작품');assert.equal(await page.locator('.argument-editor-controls .argument-link').count(),0);await work.fill(actual.writing.work);
 await question.fill('다른 탐구 문맥');assert.equal(await page.locator('.argument-editor-controls .argument-link').count(),0);await question.fill(actual.writing.inquiryQuestion);
 // Edit exact immutable endpoints independently; neither mutation is a no-op.
 for(const [name,edit] of [['claim',claimEdit],['evidence',evidenceEdit]]) {
  await editor.fill(edit.content);assert.equal(await editor.inputValue(),edit.content);
  await page.getByText('본문 또는 문맥이 바뀌어 주장·근거 표시를 숨겼습니다. 재분석하면 새 관계를 표시합니다.',{exact:true}).waitFor();
  await page.waitForFunction(()=>!document.querySelector('.argument-editor-mirror .argument-claim,.argument-editor-mirror .argument-evidence,.argument-editor-mirror .argument-link,.argument-editor-controls .argument-link'),null,{timeout:5000});
  assert.equal(await mirror.locator('.argument-claim,.argument-evidence,.argument-link').count(),0);
  assert.equal(await page.locator('.argument-editor-controls .argument-link').count(),0);
  await screenshot({path:dir+`/${theme}-${width}-${name}-stale.png`,fullPage:true});
  await editor.fill(actual.writing.content);assert.equal(await editor.inputValue(),actual.writing.content);
  await page.waitForFunction(()=>document.querySelector('.argument-editor-mirror .argument-claim')&&document.querySelector('.argument-editor-mirror .argument-evidence')&&document.querySelector('.argument-editor-mirror [data-argument-relation]'),null,{timeout:5000});
  assert.equal(await mirror.locator('.argument-claim').count(),1);assert.equal(await mirror.locator('.argument-evidence').count(),1);
  // Controls exist only for anchors in the editor viewport. Observe the restored
  // relation, then scroll its exact anchor into view before asserting its button.
  await editor.evaluate(node=>{const arrow=document.querySelector('.argument-editor-mirror [data-argument-relation]');const y=arrow.getBoundingClientRect().top-node.getBoundingClientRect().top+node.scrollTop;node.scrollTop=Math.max(0,y-100)});
  await editorArrow.waitFor({state:'visible'});
  assert.equal(await page.locator('.argument-editor-controls .argument-link').count(),1);
 }
 await page.getByRole('button',{name:'책으로 읽기',exact:true}).click();
 const next=page.getByRole('button',{name:'다음 페이지',exact:true});
 let steps=0;while(!await page.locator('.page-body .argument-link').count()) {assert.ok(++steps<30);assert.equal(await next.isDisabled(),false);await next.click()}
 assert.ok(Number(await page.locator('.reading-page').first().getAttribute('data-start'))>claim.span.start);
 await screenshot({path:dir+`/${theme}-${width}-evidence-page.png`,fullPage:true});
 const bookArrow=page.locator('.page-body .argument-link').first();
 if(width===390)await bookArrow.tap();else {await bookArrow.focus();await page.keyboard.press('Enter')}
 assert.equal(Number(await page.locator('.reading-page').first().getAttribute('data-start')),0);
 await page.locator('.page-body .argument-focused').waitFor();
 await page.waitForFunction(()=>document.querySelector('.page-body .argument-focused')===document.activeElement,null,{timeout:1000});
 assert.equal(await page.locator('.page-body .argument-focused').evaluate(e=>e===document.activeElement),true);
 await screenshot({path:dir+`/${theme}-${width}-claim-page.png`,fullPage:true});
 // Exact full-body reconstruction also checks page cuts through annotations.
 let reconstructed='';if(!smoke)for(;;){
  reconstructed+=await page.locator('.page-body .argument-fragment').evaluateAll(es=>es.map(e=>e.textContent).join(''));
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
  assert.ok(await page.locator('.page-body').evaluateAll(es=>es.every(e=>e.scrollHeight<=e.clientHeight+1)));
  pagesChecked++;if(await next.isDisabled())break;await next.click();
 }
 if(!smoke){assert.equal(reconstructed,actual.analysis.sourceVersion.content);assert.equal(Array.from(reconstructed).length,30000);}
 checks.push({theme,width,actualKiwiFixture:true,claimHighlight:true,evidenceUnderline:true,linkedArrowsOnly:true,editorCursorPreserved:true,previousPageClaimJump:true,keyboardOrTouch:true,staleClaimEvidence:true,staleEndpointChecks:2,restorationChecks:2,relationId:link.id,claimEditCodePoint:claimEdit.index,evidenceEditCodePoint:evidenceEdit.index,bodyCodePoints:30000,overflow:false});
 data=structuredClone(review);await page.goto(base);await page.getByRole('button',{name:new RegExp(data.writing.title)}).first().click();
 if(theme==='bookshelf')await page.getByRole('button',{name:'편집하기',exact:true}).click();
 await page.locator('.argument-editor-mirror .argument-claim').waitFor();
 assert.equal(await page.locator('.argument-editor-mirror .argument-evidence').count(),1);
 assert.equal(await page.locator('[data-argument-relation],.argument-link').count(),0);
 data=structuredClone(empty);await page.goto(base);await page.getByRole('button',{name:new RegExp(data.writing.title)}).first().click();
 assert.equal(await page.locator('.argument-claim,.argument-evidence,.argument-link').count(),0);
 await context.close();
 }
 assert.deepEqual(errors,[]);fs.writeFileSync(dir+(smoke?'/browser-final-results.json':'/browser-results.json'),JSON.stringify({status:'PASS',mode:'ACTUAL_ISOLATED_KIWI_RESULT_BROWSER_TRANSPORT_FIXTURE',checks,errors,pagesChecked,fullReconstruction:!smoke},null,2));console.log(JSON.stringify({status:'PASS',cases:checks.length,pagesChecked,errors:errors.length}));
}finally{await browser.close()}}
if(require.main===module)main().catch(e=>{console.error(e);process.exitCode=1});
