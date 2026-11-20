import assert from "node:assert/strict"
import { readFileSync, writeFileSync } from "node:fs"
import ts from "../node_modules/typescript/lib/typescript.js"
const source = ts.transpileModule(readFileSync(new URL("../src/feedback-spans.ts", import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText
const { validatedSpans } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`)
const points = Array.from("가😀\n같은 구절 같은 구절")
const spans = { first: {start: 3,end: 8}, second: {start: 9,end: 14}, stale: {start:0,end:2}, invalid: {start:-1,end:2} }
const findings = [{id:"first",current:"같은 구절"},{id:"second",current:"같은 구절"},{id:"stale",current:"바뀜"},{id:"invalid",current:"가😀"}]
const result = validatedSpans(points,findings,spans)
assert.deepEqual(result.first,spans.first);assert.deepEqual(result.second,spans.second)
assert.equal(result.stale,null);assert.equal(result.invalid,null)
assert.equal(validatedSpans([],findings,spans).first,null)
const text = Array.from("문학은 삶을 생각하게 한다. 😀\n\n".repeat(2000)).slice(0,30000).join("")
const cp=Array.from(text), many=Array.from({length:447},(_,i)=>({id:String(i),current:cp.slice(i*40,i*40+12).join("")})), mapped=Object.fromEntries(many.map((f,i)=>[f.id,{start:i*40,end:i*40+12}]))
let oldResult;const before=performance.now()
for(let render=0;render<10;render++) oldResult=many.map(f=>{const span=mapped[f.id];return Array.from(text).slice(span.start,span.end).join("")===f.current?span:null})
const oldMs=performance.now()-before,after=performance.now(),cached=validatedSpans(cp,many,mapped)
for(let render=0;render<10;render++) assert.deepEqual(many.map(f=>cached[f.id]),oldResult)
const newMs=performance.now()-after
const evidence={kind:"Span-validation microbenchmark; not browser total latency",codePoints:cp.length,findings:447,renders:10,beforeMs:+oldMs.toFixed(2),afterMs:+newMs.toFixed(2),equivalent:true,unicodeAndStaleCases:"PASS"}
writeFileSync("artifacts/optimization/span-benchmark.json",JSON.stringify(evidence,null,2));console.log(JSON.stringify(evidence))
