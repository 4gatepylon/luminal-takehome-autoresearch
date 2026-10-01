"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { before, test } = require("node:test");
const oniguruma = require("vscode-oniguruma");
const { Registry, parseRawGrammar, INITIAL } = require("vscode-textmate");

const extensionRoot = path.resolve(__dirname, "..");
const repositoryRoot = path.resolve(extensionRoot, "../../..");
let grammar;
let rawGrammar;

before(async () => {
  await oniguruma.loadWASM(fs.readFileSync(require.resolve("vscode-oniguruma/release/onig.wasm")));
  const registry = new Registry({
    onigLib: Promise.resolve({
      createOnigScanner: (sources) => new oniguruma.OnigScanner(sources),
      createOnigString: (text) => new oniguruma.OnigString(text),
    }),
    loadGrammar: async (scope) => {
      assert.equal(scope, "source.luminal-ssa");
      const filename = path.join(extensionRoot, "syntaxes/ssa.tmLanguage.json");
      rawGrammar = parseRawGrammar(fs.readFileSync(filename, "utf8"), filename);
      return rawGrammar;
    },
  });
  grammar = await registry.loadGrammar("source.luminal-ssa");
});

function tokenize(source) {
  let state = INITIAL;
  return source.split("\n").map((line) => {
    const result = grammar.tokenizeLine(line, state);
    state = result.ruleStack;
    return result.tokens.map((token) => ({
      text: line.slice(token.startIndex, token.endIndex),
      scopes: token.scopes,
    }));
  });
}

function hasScope(tokens, text, scope) {
  assert.ok(tokens.some((token) => token.text === text && token.scopes.includes(scope)),
    `Expected ${JSON.stringify(text)} in ${scope}: ${JSON.stringify(tokens)}`);
}

test("manifest registers .ssa and all referenced files exist", () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(extensionRoot, "package.json"), "utf8"));
  const language = manifest.contributes.languages[0];
  const contribution = manifest.contributes.grammars[0];
  assert.deepEqual(language.extensions, [".ssa"]);
  assert.equal(contribution.language, language.id);
  assert.equal(contribution.scopeName, rawGrammar.scopeName);
  const configuration = JSON.parse(fs.readFileSync(path.join(extensionRoot, language.configuration), "utf8"));
  assert.equal(configuration.comments.lineComment, "#");
  assert.equal(configuration.comments.blockComment, undefined);
});

test("every checked-in SSA file tokenizes without invalid scopes", () => {
  const directory = path.join(repositoryRoot, "programs", "ssa");
  const files = fs.readdirSync(directory).filter((name) => name.endsWith(".ssa"));
  assert.ok(files.length > 0);
  for (const file of files) {
    const tokens = tokenize(fs.readFileSync(path.join(directory, file), "utf8")).flat();
    assert.ok(!tokens.some((token) => token.scopes.some((scope) => scope.startsWith("invalid."))), file);
    assert.ok(tokens.some((token) => token.scopes.includes("meta.program.ssa")), file);
    assert.ok(tokens.some((token) => token.scopes.includes("meta.cases.ssa")), file);
  }
});

test("headers, sections, splat, ternary, comments, and embedded JSON receive appropriate scopes", () => {
  const lines = tokenize(`lang: ssa-v1
name: "# example"
================ BUFFERS ================
{"a":8}
================ PROGRAM ================
  # whole-line comment
v = ...a
r = yes if { condition } else no
a = const(3) # invalid inline comment
x = const(1) @ {"note":{"value":"# data"}} y = ...x
================ CASES ================
{"a":[1,2,3,4,5,6,7,8]}`);
  hasScope(lines[0], "ssa-v1", "constant.language.version.ssa");
  hasScope(lines[1], "# example", "string.quoted.double.json");
  hasScope(lines[2], "================ BUFFERS ================", "entity.name.section.ssa");
  hasScope(lines[3], "8", "constant.numeric.json");
  hasScope(lines[5], "  # whole-line comment", "comment.line.number-sign.ssa");
  hasScope(lines[6], "...", "keyword.operator.ssa");
  hasScope(lines[7], "if", "keyword.control.conditional.ssa");
  hasScope(lines[7], "else", "keyword.control.conditional.ssa");
  hasScope(lines[7], "condition", "variable.other.ssa");
  hasScope(lines[8], "# invalid inline comment", "invalid.illegal.inline-comment.ssa");
  hasScope(lines[9], "# data", "string.quoted.double.json");
  hasScope(lines[9], "y", "variable.other.ssa");
  hasScope(lines[11], "8", "constant.numeric.json");
});

test("program scopes survive multiline statements and full-line comments", () => {
  const lines = tokenize(`================ PROGRAM ================
v =
  ...a
r = yes if {
  # condition below
  gate
} else no
================ CASES ================
{"a":[0]}`);
  hasScope(lines[2], "...", "keyword.operator.ssa");
  hasScope(lines[4], "  # condition below", "comment.line.number-sign.ssa");
  hasScope(lines[5], "gate", "variable.other.ssa");
  hasScope(lines[6], "else", "keyword.control.conditional.ssa");
  hasScope(lines[8], "0", "constant.numeric.json");
});

test("Unicode Python identifiers include combining marks and special identifier letters", () => {
  const lines = tokenize("================ PROGRAM ================\nλ = const(1)\ne\u0301 = λ + λ\n℘ = e\u0301 * λ");
  hasScope(lines[1], "λ", "variable.other.ssa");
  hasScope(lines[2], "e\u0301", "variable.other.ssa");
  hasScope(lines[3], "℘", "variable.other.ssa");
});
