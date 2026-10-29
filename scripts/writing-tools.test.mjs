import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import ts from '../node_modules/typescript/lib/typescript.js'
const compile=path=>'data:text/javascript;base64,'+Buffer.from(ts.transpileModule(readFileSync(path,'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2020}}).outputText).toString('base64')
const {selectionAnchor,cpSlice,keywordQueries}=await import(compile('src/writing-tools.ts'))
const {findTextSpans,findMultipleTextSpans}=await import(compile('src/text-search.ts'))
test('Unicode code-point selection binds exact immutable version',()=>{
 const body='😀 빛과 소리. 빛의 자리.'
 assert.deepEqual(selectionAnchor({id:'v',content:body},body,{start:0,end:3}),{essayVersionId:'v',span:{start:0,end:3},quote:'😀 빛'})
 assert.equal(cpSlice(body,{start:0,end:1}),'😀')
})
test('Changed version, booleans, empty and out-of-bounds spans fail',()=>{
 for(const span of [{start:0,end:0},{start:true,end:2},{start:-1,end:2},{start:0,end:99}])assert.throws(()=>selectionAnchor({id:'v',content:'원문'},'원문',span))
 assert.throws(()=>selectionAnchor({id:'old',content:'이전'},'현재',{start:0,end:1}))
})
test('Multiple explicit keywords preserve overlap, deduplicate and keep code points',()=>{
 const body=Array.from('😀 빛 빛과 소리 빛')
 assert.deepEqual(findMultipleTextSpans(body,'빛, 소리,빛'),[{start:2,end:3},{start:4,end:5},{start:7,end:9},{start:10,end:11}])
 assert.deepEqual(findMultipleTextSpans(body,''),[])
 assert.deepEqual(keywordQueries(' 빛,소리\n빛 '),['빛','소리'])
})
test('Original single-query contract remains exact including punctuation',()=>{
 assert.deepEqual(findTextSpans(Array.from('a,b a,b'),'a,b'),[{start:0,end:3},{start:4,end:7}])
 assert.deepEqual(findTextSpans(Array.from('aaaa'),'aa'),[{start:0,end:2},{start:1,end:3},{start:2,end:4}])
})
