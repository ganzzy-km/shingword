import assert from 'node:assert/strict'
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs'
import ts from '../node_modules/typescript/lib/typescript.js'
const source=ts.transpileModule(readFileSync(new URL('../src/argument-spans.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2020}}).outputText
const {argumentMarks,argumentSegments}=await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
const text='😀 가 뿌리는 사랑을 상징한다.\n시에서 뿌리는 꽃을 지킨다.',points=Array.from(text)
const make=(id,start,end,role)=>({id,analysisRunId:'a1',essayVersionId:'v1',span:{start,end},quote:points.slice(start,end).join(''),roles:[role],signals:[]})
const split=points.indexOf('\n'),claim=make('c1',0,split,'CLAIM_CANDIDATE'),evidence=make('e1',split+1,points.length,'EVIDENCE_CANDIDATE')
const relation={id:'r1',analysisRunId:'a1',essayVersionId:'v1',claimId:'c1',evidenceId:'e1',claimSpan:claim.span,evidenceSpan:evidence.span,signals:['SHARED_TOPIC_NOUNS'],sharedNouns:['뿌리'],confidence:'REVIEW_SIGNALS'}
const marks=argumentMarks(points,text,'a1','v1',[claim,evidence],[relation]);assert.equal(marks.links.length,1)
assert.equal(argumentSegments(points,{start:0,end:points.length},marks.candidates,marks.links).map(s=>s.text).join(''),text)
assert.equal(argumentSegments(points,{start:0,end:split+8},marks.candidates,marks.links).flatMap(s=>s.arrows).length,0)
assert.equal(argumentSegments(points,{start:split+8,end:points.length},marks.candidates,marks.links).flatMap(s=>s.arrows).length,1)
for(const changed of [text.replace('사랑','자유'),text.replace('꽃','잎'), '문맥 추가.\n'+text,text.replace('\n','\n\n'),text.replace('시에서 뿌리는 꽃을 지킨다.','')]) {
 const stale=argumentMarks(Array.from(changed),text,'a1','v1',[claim,evidence],[relation]);assert.equal(stale.stale,true);assert.equal(stale.links.length,0);assert.equal(stale.candidates.length,0)
}
assert.equal(argumentMarks(points,text,'a2','v1',[claim,evidence],[relation]).candidates.length,0)
assert.equal(argumentMarks(points,text,'a1','v2',[claim,evidence],[relation]).candidates.length,0)
assert.equal(argumentMarks(points,text,'a1','v1',[claim,{...evidence,quote:'偽'}],[relation]).links.length,0)
assert.equal(argumentMarks(points,text,'a1','v1',[claim,evidence],[{...relation,claimSpan:{start:1,end:split}}]).links.length,0)
assert.equal(argumentMarks(points,text,'a1','v1',[],[]).links.length,0)
const longPoints=Array.from('가😀 문장. '.repeat(5000)).slice(0,30000),longText=longPoints.join('')
const longNodes=Array.from({length:1000},(_,i)=>({id:'n'+i,analysisRunId:'a1',essayVersionId:'v1',span:{start:i*30,end:i*30+20},quote:longPoints.slice(i*30,i*30+20).join(''),roles:['CLAIM_CANDIDATE'],signals:[]}))
const started=performance.now();const longMarks=argumentMarks(longPoints,longText,'a1','v1',longNodes,[]),parts=argumentSegments(longPoints,{start:0,end:30000},longMarks.candidates,[])
assert.equal(parts.map(s=>s.text).join(''),longText)
const proof={status:'PASS',unicode:true,staleClaimEvidenceContext:true,versionAndRunIsolation:true,pageBoundary:true,codePoints:30000,marks:1000,milliseconds:+(performance.now()-started).toFixed(2)}
mkdirSync('artifacts/argument-links',{recursive:true});writeFileSync('artifacts/argument-links/span-results.json',JSON.stringify(proof,null,2));console.log(JSON.stringify(proof))
