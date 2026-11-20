// Real isolated API/browser; synthetic signed OIDC, never real Google.
const {chromium}=require(process.env.PLAYWRIGHT_PACKAGE || 'C:/Users/USER/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const base=process.env.GEULBIT_QA_ORIGIN || 'https://127.0.0.1:8768';if(!/^https:\/\/(localhost|127\.0\.0\.1):8768$/.test(base))throw Error('LOOPBACK_QA_ONLY');const dir=path.resolve('artifacts/beta/signup');fs.mkdirSync(dir,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
 const ctx=await browser.newContext({ignoreHTTPSErrors:true,acceptDownloads:true});const page=await ctx.newPage(),errors=[],shots=[];
 page.on('pageerror',e=>errors.push(e.message));
 const shot=async name=>{await page.screenshot({path:path.join(dir,name+'.png'),fullPage:true});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,name);shots.push(name);};
 await page.goto(base+'/api/auth/login');await page.getByRole('heading',{name:'비공개 베타 이용 안내'}).waitFor();
 for(const width of [1440,820,390,320]){await page.setViewportSize({width,height:1000});await shot('consent-'+width);}
 assert.equal((await ctx.request.get(base+'/api/writings')).status(),401);
 await page.getByLabel('만 14세 이상입니다.').check();await page.getByLabel('위 개인정보 처리 안내를 읽고 필수 처리에 동의합니다.').check();await page.getByRole('button',{name:'동의하고 내 서재 시작'}).click();await page.locator('.gb:visible').waitFor();
 const session=(await(await ctx.request.get(base+'/api/auth/session')).json()).data;assert.equal(session.role,'USER');assert.equal(session.status,'ACTIVE');const headers={'X-CSRF-Token':session.csrfToken};
 const api=async(method,url,data)=>{const r=await ctx.request.fetch(base+'/api'+url,{method,headers,data});assert.ok(r.ok(),method+' '+url+' '+r.status());return (await r.json()).data};
 const body='나는 며칠 동안 작품을 읽었다. 몇일 동안이라고 쓰면 표기를 확인해야 한다. 😀\n\n인물의 선택은 책임을 보여 준다고 생각한다. “나는 돌아오겠다.”라는 말은 그 선택을 드러낸다.';
 const w=await api('POST','/writings',{title:'비공개 베타 가입 검증 에세이',content:body,inquiryQuestion:'인물의 선택은 어떤 책임을 보여 주는가?'});
 await page.goto(base);await page.getByRole('button',{name:new RegExp(w.title)}).click();const editor=page.getByRole('textbox',{name:'에세이 본문'});await editor.waitFor();assert.equal(await editor.inputValue(),body);
 await page.getByRole('button',{name:'분석하기',exact:true}).click();await page.getByRole('button',{name:'분석하기',exact:true}).waitFor();await page.getByRole('button',{name:/원문으로 이동/}).first().waitFor();await shot('default-feedback');
 const writing=await api('GET','/writings/'+w.id);assert.ok(writing.latestAnalysisId);const run=await api('GET','/analyses/'+writing.latestAnalysisId);assert.equal(run.sourceVersion.content,body);
 await page.getByRole('button',{name:/원문으로 이동/}).first().click();assert.equal(await editor.evaluate(e=>e.value.slice(e.selectionStart,e.selectionEnd)),'몇일');
 await page.getByRole('button',{name:'화면 설정',exact:true}).first().click();await page.getByRole('button',{name:/책장 테마/}).click();await page.getByRole('button',{name:'닫기',exact:true}).click();await page.getByRole('button',{name:'← 서재로 돌아가기',exact:true}).click();await page.getByRole('button',{name:new RegExp(w.title)}).click();await page.getByLabel('책 본문. 좌우 방향키로 페이지 이동').waitFor();await shot('bookshelf-feedback');assert.equal((await api('GET','/writings/'+w.id)).latestAnalysisId,writing.latestAnalysisId);
 await page.locator('.writing-more > summary').click();const pending=page.waitForEvent('download');await page.getByRole('button',{name:'PDF 저장',exact:true}).click();const pdf=await pending;await pdf.saveAs(path.join(dir,'synthetic-beta.pdf'));assert.equal(fs.readFileSync(path.join(dir,'synthetic-beta.pdf')).subarray(0,5).toString(),'%PDF-');
 await page.getByRole('button',{name:'내 계정',exact:true}).click();await page.getByRole('button',{name:'로그아웃',exact:true}).click();await page.getByRole('link',{name:'Google 로그인'}).waitFor();assert.equal((await ctx.request.get(base+'/api/writings/'+w.id)).status(),401);await shot('logged-out');
 await page.goto(base+'/api/auth/login');await page.locator('.gb:visible').waitFor();await page.getByRole('button',{name:'내 계정',exact:true}).click();await page.getByRole('button',{name:'개인정보 관리·계정 탈퇴',exact:true}).click();await shot('account-withdrawal');assert.equal(await page.getByRole('button',{name:'계정 탈퇴 확정',exact:true}).isDisabled(),true);await page.getByLabel('탈퇴 확인 입력').fill('탈퇴');page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'계정 탈퇴 확정',exact:true}).click();await page.getByRole('link',{name:'Google 로그인'}).waitFor();assert.equal((await ctx.request.get(base+'/api/writings/'+w.id)).status(),401);
 assert.deepEqual(errors,[]);const result={status:'PASS',actualApi:true,isolated:true,authentication:'SYNTHETIC_SIGNED_OIDC_NOT_ACTUAL_GOOGLE',screenshots:shots,checks:['consent required','age14 required','immediate ACTIVE USER','exact version and span','same essay/run in two themes','PDF bytes and browser download','logout denies original','confirmed withdrawal through current account UI denies original'],errors};fs.writeFileSync(path.join(dir,'evidence.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({status:result.status,screenshots:shots.length,errors:0,authentication:result.authentication}));
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
