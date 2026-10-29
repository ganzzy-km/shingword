const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict'),ts=require('typescript');
const source=fs.readFileSync(path.join(__dirname,'../src/ocr-review.ts'),'utf8');const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;const moduleValue={exports:{}};vm.runInNewContext(code,{module:moduleValue,exports:moduleValue.exports});const {replaceOcrSpan,tableColumnSpan}=moduleValue.exports;
let count=0;function check(name,fn){fn();count++;console.log('PASS '+name)}
check('Exact emoji/code-point separator edit',()=>{const s='가😀나다\n다음 줄';assert.equal(replaceOcrSpan(s,s,4,5,'\n',' '),'가😀나다 다음 줄')});
check('No-space join is an explicit user choice',()=>{const s='앞\n뒤';assert.equal(replaceOcrSpan(s,s,1,2,'\n',''),'앞뒤')});
check('Dirty draft is rejected without guesswork',()=>assert.throws(()=>replaceOcrSpan('수정된 앞\n뒤','앞\n뒤',1,2,'\n',' ')));
check('Wrong source span is rejected',()=>assert.throws(()=>replaceOcrSpan('앞\n뒤','앞\n뒤',0,1,'\n',' ')));
check('Out-of-range or fractional offsets rejected',()=>{for(const [a,b]of [[-1,2],[1,50],[.5,1],[2,1]])assert.throws(()=>replaceOcrSpan('앞\n뒤','앞\n뒤',a,b,'\n',' '))});
check('Literal text is never normalized or rewritten',()=>{const s='가\n방언·  그대로';assert.equal(replaceOcrSpan(s,s,2,3,'\n','\n\n'),'가\n\n방언·  그대로')});
check('Current and historical column spans remain compatible',()=>{assert.equal(tableColumnSpan({columnSpan:3}),3);assert.equal(tableColumnSpan({colSpan:2}),2);assert.equal(tableColumnSpan({}),1)});
check('Bad or excessive spans cannot distort table DOM',()=>{for(const v of [0,-1,10000,1.1,'2',true])assert.equal(tableColumnSpan({columnSpan:v}),1)});
console.log(JSON.stringify({passed:count,failed:0}));
