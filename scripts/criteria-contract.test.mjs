import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),ts=require('typescript');
const text=fs.readFileSync(new URL('../src/App.tsx',import.meta.url),'utf8');
const ast=ts.createSourceFile('App.tsx',text,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
function declaration(name){let found;function visit(n){if(ts.isFunctionDeclaration(n)&&n.name?.text===name)found=n;ts.forEachChild(n,visit)}visit(ast);assert.ok(found,name);return found.getText(ast)}
const criteria=declaration('CriteriaScreen'),row=declaration('FileRow'),dialog=declaration('OcrDialog');
let normalize;function visit(n){if(ts.isVariableDeclaration(n)&&n.name.getText(ast)==='rubricStatus'){const out=ts.transpileModule('exports.normalize='+n.initializer.getText(ast),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText,context={exports:{}};vm.runInNewContext(out,context);normalize=context.exports.normalize}ts.forEachChild(n,visit)}visit(ast);

test('actual and historical pending/confirmed statuses use one canonical UI value',()=>{for(const name of['확인 완료','등록 완료'])assert.equal(normalize(name),'확인 완료');for(const name of['확인 필요','OCR 확인 필요'])assert.equal(normalize(name),'확인 필요');for(const name of['OCR 실행 환경 필요','처리 실패','OCR 일부 완료'])assert.equal(normalize(name),name)});
test('confirmed and pending catalogue counts and filters use canonical status',()=>{assert.match(criteria,/rubricStatus\(item\.status\) === status/);assert.match(criteria,/rubricStatus\(file\.status\) === "확인 완료"/);assert.match(criteria,/rubricStatus\(file\.status\) === "확인 필요"/);assert.match(criteria,/<option value="확인 완료">확인 완료<\/option>/);assert.match(criteria,/<option value="확인 필요">확인 필요<\/option>/)});
test('actual extract can be reviewed independently of old OCR warning badge',()=>{assert.match(row,/\{onOcr && \(/);assert.match(row,/추출 글 확인/);assert.match(criteria,/onOcr=\{item\.correctedText\?\.trim\(\) \|\| item\.ocrText\?\.trim\(\)/)});
test('rubric upload advertises only server-supported native PDF and UTF-8 text',()=>{const accepts=[...criteria.matchAll(/accept="([^"]+)"/g)].map(x=>x[1]);assert.deepEqual(accepts,['application/pdf,text/plain,.pdf,.txt'])});
test('disabled scanned-rubric OCR is not offered as runnable',()=>{assert.match(dialog,/const canRun = model\.kind !== "rubric" &&/);assert.match(dialog,/model\.kind === "rubric" \? "추출 글 확인"/)});
test('native extract and correction confirmation retain actual API contract',()=>{assert.match(criteria,/detail\.correctedText\?\.trim\(\) \|\| detail\.ocrText\?\.trim\(\) \? "not_required"/);assert.match(criteria,/api\.patch\(`\/rubrics\/\$\{ocrDialog\.id\}`/);assert.match(criteria,/correctedText: ocrDialog\.pages\.map/);assert.match(criteria,/confirm: true/)});
