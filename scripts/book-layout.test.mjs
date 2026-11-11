import assert from 'node:assert/strict'
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs'
import ts from '../node_modules/typescript/lib/typescript.js'
const source = ts.transpileModule(readFileSync(new URL('../src/book-layout.ts', import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText
const { paginateText, mapSpan, paragraphs, utf16Offset } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
const searchSource = ts.transpileModule(readFileSync(new URL('../src/text-search.ts', import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText
const { findTextSpans } = await import(`data:text/javascript;base64,${Buffer.from(searchSource).toString('base64')}`)
assert.deepEqual(findTextSpans(Array.from('가😀가😀'), '😀'), [{start:1,end:2},{start:3,end:4}])
assert.deepEqual(findTextSpans(Array.from('aaaa'), 'aa'), [{start:0,end:2},{start:1,end:3},{start:2,end:4}])
assert.deepEqual(findTextSpans(Array.from('가\r\n나'), '\r\n'), [{start:1,end:3}])
assert.deepEqual(findTextSpans(Array.from('가'), ''), [])
assert.deepEqual(findTextSpans(Array.from('가'), '없는 구절'), [])
const benchmarkPoints=Array.from('같은 구절 😀 문장. '.repeat(3000)).slice(0,30000), needle='같은 구절'
const oldSearch=() => {
  const found=[], query=Array.from(needle)
  for(let i=0;i<=benchmarkPoints.length-query.length;i++)
    if(benchmarkPoints[i]===query[0] && benchmarkPoints.slice(i,i+query.length).join('')===needle)
      found.push({start:i,end:i+query.length})
  return found
}
assert.deepEqual(findTextSpans(benchmarkPoints,needle),oldSearch())
const oldStart=performance.now();for(let i=0;i<30;i++)oldSearch();const oldMs=performance.now()-oldStart
const newStart=performance.now();for(let i=0;i<30;i++)findTextSpans(benchmarkPoints,needle);const newMs=performance.now()-newStart
mkdirSync('artifacts/ui-refinement',{recursive:true})
writeFileSync('artifacts/ui-refinement/search-benchmark.json',JSON.stringify({scope:'Synthetic search microbenchmark, not total UI latency',codePoints:30000,iterations:30,oldMs,newMs,equivalent:true},null,2))
for (const size of [10000, 30000]) {
  const text = ('문학은 삶을 비추는 거울이다. 😀 같은 문장도 정확한 위치를 가진다.\n\n' .repeat(1000)).slice(0,size)
  for (const width of [180, 400, 900]) {
    const pages = paginateText(text, value => Array.from(value).length <= width)
    assert.equal(pages.map(p => Array.from(text).slice(p.start,p.end).join('')).join(''), text)
    assert.ok(pages.every((p,i) => p.end > p.start && (!i || pages[i-1].end === p.start)))
  }
}
const original = '😀첫 문장.\n\n같은 문장.\n\n같은 문장.'
const start = Array.from(original).length - Array.from('같은 문장.').length
const span = {start, end:Array.from(original).length}
const inserted = '추가 문단.\n\n' + original
const mapped = mapSpan(original,inserted,span,{start:0,end:0})
assert.equal(Array.from(inserted).slice(mapped.start,mapped.end).join(''),'같은 문장.')
assert.equal(mapped.start,span.start + Array.from('추가 문단.\n\n').length)
assert.equal(mapSpan(original,original.slice(0,-3)+'바뀐 구절.',span),null)
assert.equal(mapSpan(original,inserted,span),null)
assert.equal(utf16Offset(original,1),2)
assert.equal(paragraphs(original).length,3)
assert.equal(paginateText('',()=>true).length,1)
console.log('PASS: 10k/30k pagination at 3 capacities; Unicode offsets; repeated quote; changed-range invalidation; empty text')
