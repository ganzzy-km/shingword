import assert from 'node:assert/strict'
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs'
import ts from '../node_modules/typescript/lib/typescript.js'
const compile=text=>'data:text/javascript;base64,'+Buffer.from(ts.transpileModule(text,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2020}}).outputText).toString('base64')
const layout=compile(readFileSync('src/book-layout.ts','utf8'))
const module=compile(readFileSync('src/user-annotations.ts','utf8').replace('from "./book-layout"','from '+JSON.stringify(layout)))
const {verifiedAnnotationSpan,moveAnnotation}=await import(module)
const text='😀 가\n같은 구절. 같은 구절.',start=Array.from(text).join('').lastIndexOf('같은 구절.')-1 // UTF-16 emoji correction
const note={span:{start,end:start+6},quote:'같은 구절.'}
assert.equal(Array.from(text).slice(start,start+6).join(''),note.quote)
assert.deepEqual(verifiedAnnotationSpan(note,text,text),note.span)
assert.equal(verifiedAnnotationSpan(note,text,'다른 원문'),null)
assert.equal(verifiedAnnotationSpan({...note,quote:'잘못된 구절'},text,text),null)
const shifted=moveAnnotation(text,'앞 '+text,note.span,note.quote,{start:0,end:0})
assert.deepEqual(shifted,{start:start+2,end:start+8})
assert.equal(moveAnnotation(text,text.slice(0,-3)+'수정',note.span,note.quote),null)
assert.equal(moveAnnotation(text,text,null,note.quote),null)
const {utf16Offset}=await import(layout)
assert.equal(utf16Offset(Array.from(text),2),3)
const {argumentSegments}=await import(compile(readFileSync('src/argument-spans.ts','utf8')))
const points=Array.from(text),marks=[{id:'1',span:{start:0,end:2}},{id:'2',span:note.span},{id:'3',span:note.span}]
const pieces=argumentSegments(points,{start:0,end:points.length},[],[],null,marks)
assert.equal(pieces.map(s=>s.text).join(''),text)
assert.ok(pieces.some(s=>s.end===note.span.end))
mkdirSync('artifacts/annotations',{recursive:true});writeFileSync('artifacts/annotations/span-results.json',JSON.stringify({status:'PASS',checks:10,repeatedQuote:true,unicode:true,stale:true,multipleSameSpan:true,sourcePreserved:true},null,2))
console.log('PASS 10 annotation span assertions')
