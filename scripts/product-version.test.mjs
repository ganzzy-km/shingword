import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import test from "node:test"
import ts from "../node_modules/typescript/lib/typescript.js"

const root = new URL("../", import.meta.url)
const metadata = JSON.parse(readFileSync(new URL("package.json", root), "utf8"))
const source = readFileSync(new URL("src/product-version.ts", root), "utf8")
const output = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText
const exports = {}
new Function("require", "exports", output)(createRequire(new URL("src/product-version.ts", root)), exports)

test("product label uses the existing package root version", () => {
  assert.equal(metadata.version, "1.2.0")
  assert.equal(exports.PRODUCT_LABEL, "글빛 1.2.0")
  assert.match(source, /import \{ version \} from "\.\.\/package\.json"/)
  assert.equal(source.includes("1.2.0"), false)
})

test("both themes share one label in the existing settings content", () => {
  const library = readFileSync(new URL("src/Library.tsx", root), "utf8")
  assert.match(library, /import \{ PRODUCT_LABEL \} from "\.\/product-version"/)
  assert.equal((library.match(/data-product-version/g) || []).length, 1)
  assert.match(library, /분석·접근성·데이터 설정 열기\s*<\/button>\s*<small className="settings-note" data-product-version>\{PRODUCT_LABEL\}<\/small>/)
  assert.equal(library.includes("글빛 1.2.0"), false)
})

test("package metadata is the single numeric version source", () => {
  const changedVersionMetadata = { ...metadata, version: "9.8.7" }
  const injected = {}
  new Function("require", "exports", output)((request) => {
    assert.equal(request, "../package.json")
    return changedVersionMetadata
  }, injected)
  assert.equal(injected.PRODUCT_LABEL, "글빛 9.8.7")
})
