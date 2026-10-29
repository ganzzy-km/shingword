import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from '../node_modules/typescript/lib/typescript.js'
const transpile = file => ts.transpileModule(readFileSync(new URL(file, import.meta.url), 'utf8'), {compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2020}}).outputText
const {api, resetApiSession, ApiError} = await import(`data:text/javascript;base64,${Buffer.from(transpile('../src/api.ts')).toString('base64')}`)
const events=[]
globalThis.window={dispatchEvent:e=>events.push(e.type)}
const response=(status,data)=>({ok:status<400,status,headers:{get:()=> 'application/json'},json:async()=>data})
let release
globalThis.fetch=()=>new Promise(resolve=>{release=resolve})
const old=api.get('/writings')
resetApiSession()
release(response(200,{data:[{title:'previous account private essay'}]}))
await assert.rejects(old,/계정이 변경/)
let received=[]
globalThis.fetch=async (path,init)=>{
  received.push({path,headers:init?.headers})
  return response(200,{data:path==='/api/auth/session'?{csrfToken:'new-account-fixture-token'}:{loggedOut:true}})
}
await api.post('/auth/logout')
assert.equal(received[1].headers['X-CSRF-Token'],'new-account-fixture-token')
globalThis.fetch=async()=>response(401,{error:{code:'ACCESS_DENIED',message:'authentication required'}})
await assert.rejects(api.get('/writings'),e=>e instanceof ApiError && e.status===401)
assert.deepEqual(events,['geulbit-auth-required'])
for(const status of [403,500]){
  globalThis.fetch=async()=>response(status,{error:{code:'EXPECTED_ERROR',message:'synthetic error'}})
  await assert.rejects(api.get('/writings'),e=>e instanceof ApiError && e.status===status && e.code==='EXPECTED_ERROR')
}
globalThis.fetch=async()=>{throw new TypeError('synthetic network failure')}
await assert.rejects(api.get('/writings'),/network failure/)
let releaseBlob
globalThis.fetch=async()=>({ok:true,headers:{get:()=> 'application/pdf'},blob:()=>new Promise(resolve=>{releaseBlob=resolve})})
const download=api.download('/analyses/synthetic/pdf')
await Promise.resolve(); resetApiSession(); releaseBlob(new Blob(['synthetic']))
await assert.rejects(download,/계정이 변경/)
// A cached CSRF await must not send a mutation after account reset.
globalThis.fetch=async()=>response(200,{data:{csrfToken:'synthetic-cached-token'}})
await api.get('/auth/session')
let mutations=0
globalThis.fetch=async()=>{mutations++;return response(200,{data:{}})}
const mutation=api.post('/writings',{title:'synthetic'})
resetApiSession()
await assert.rejects(mutation,/계정이 변경/)
assert.equal(mutations,0)
const count=events.length
globalThis.fetch=async()=>response(401,{error:{code:'ACCESS_DENIED'}})
await assert.rejects(api.download('/analyses/synthetic/pdf'),e=>e instanceof ApiError && e.status===401)
assert.equal(events.length,count+1)
await assert.rejects(api.post('/writings',{}),e=>e instanceof ApiError && e.status===401)
assert.equal(events.length,count+2)
const beforeAnnotation=events.length
await assert.rejects(api.post('/writings/synthetic/annotations',{},true),e=>e instanceof ApiError && e.status===401)
assert.equal(events.length,beforeAnnotation) // Input remains visible; server still rejects.
globalThis.fetch=async()=>response(200,{data:{csrfToken:'synthetic-annotation-token'}})
await api.get('/auth/session')
globalThis.fetch=async()=>response(401,{error:{code:'ACCESS_DENIED'}})
await assert.rejects(api.patch('/annotations/synthetic',{content:'synthetic'},true),e=>e instanceof ApiError && e.status===401)
assert.equal(events.length,beforeAnnotation)
console.log('PASS: 12 account isolation cases, including annotation input retention without server authentication bypass')
