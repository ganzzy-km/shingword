import { readFileSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import { createInterface } from "node:readline";
import { KiwiBuilder, Match } from "kiwi-nlp";

const modelDirectory = process.argv[2];
const modelFiles = Object.fromEntries(
  readdirSync(modelDirectory)
    .filter((name) => /\.(dict|mdl|txt|morph)$/.test(name))
    .map((name) => [name, readFileSync(join(modelDirectory, name))]),
);
const require = createRequire(import.meta.url);
const builder = await KiwiBuilder.create(require.resolve("kiwi-nlp/dist/kiwi-wasm.wasm"));
const kiwi = await builder.build({ modelFiles, modelType: "cong" });
if (!kiwi.ready()) {
  throw new Error("Kiwi initialization failed");
}

function analyze(text, topN) {
  // Kiwi WASM reports UTF-16 offsets. The Python API uses code points.
  const offsets = [0];
  let utf16 = 0;
  let codePoints = 0;
  for (const char of text) {
    utf16 += char.length;
    offsets[utf16] = ++codePoints;
  }
  return kiwi.analyzeTopN(text, topN, Match.all).map(({ tokens, score }) => [
    tokens.map(({ str, tag, position, length }) => {
      const start = offsets[position];
      const end = offsets[position + length];
      if (start === undefined || end === undefined) {
        throw new Error("Invalid Kiwi token offset");
      }
      return [str, tag, start, end - start];
    }),
    score,
  ]);
}

process.stdout.write(JSON.stringify({ version: builder.version() }) + "\n");
const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
for await (const line of input) {
  try {
    const [text, topN] = JSON.parse(line);
    process.stdout.write(JSON.stringify({ candidates: analyze(text, topN) }) + "\n");
  } catch {
    process.stdout.write('{"error":"KIWI_ANALYSIS_FAILED"}\n');
  }
}
