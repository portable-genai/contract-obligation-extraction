// Every security-relevant environment read in `ui/` resolves THREE states, proved by scanning
// the shipped JavaScript and TypeScript.
//
// The Python gate has `tests/unit/test_three_state_env_reads.py`, which fails the build on any
// two-state `os.environ.get(name, default)` in the shipped source. It could not see this
// directory: it walks `src`, `scripts` and `eval` and parses with `ast`, so no `.mjs`, `.ts` or
// `.tsx` file was ever read. Its own docstring cites the `<PKG>_FRAME_ANCESTORS` scar, and that
// scar lived in the UI layer. A verifier proved the hole by adding
//
//     const allowed = env.UI_TENANT_ORIGINS || "*";
//
// to `lib/embed-policy.mjs`. A wildcard CORS allowlist, reachable by emptying one variable, and
// it survived the entire gate: every Python test, every node test, `tsc` clean. This file is the
// missing half. It runs in bare node with no bundler, in `npm test`, in the ui-gate workflow, and
// in the template's own render gate.
//
// The rule, mirroring the Python one exactly. `env.X || "default"` and `env.X ?? "default"`
// collapse three states into two:
//
//     unset          -> nobody expressed an intent, so a documented default may stand
//     set and empty  -> an intent WAS expressed and it names nothing, so fail closed
//     set with value -> use it
//
// The middle state is the dangerous one. Folded into the first, a value an operator deliberately
// emptied inherits the default, and where the default is the more permissive branch (a CORS
// allowlist, a shipped `frame-ancestors`, an offline profile) emptying a variable OPENS the UI.
// So this scan is stricter than the two operators the defect wore: it fails on ANY direct
// `env.X` / `process.env.X` read in the shipped source, whatever is done with the value, because
// `const raw = env.X; if (!raw) return DEFAULT;` is the same collapse spelled over two lines and
// is exactly the collapse `frameAncestors` must avoid. `lib/env-setting.mjs` returns a setting whose
// `isUnset` / `isConfiguredEmpty` / `hasValue` are mutually exclusive, so the middle state has
// somewhere to go.
//
// Two escapes, both narrow and both written down:
//
//   1. an EXACT-MATCH relaxation, the raw value compared against a literal (`env.X === "1"`).
//      There is no default to inherit and no truthiness to be surprised by, so unset, emptied
//      and "0" alike all mean no. Fail-closed by construction;
//   2. a variable named in TWO_STATE_READS_WITH_A_REASON below, which carries no posture at all.
//      Each entry needs a written reason, and a second test fails the build when an entry stops
//      matching anything, so the exemption list cannot quietly outlive its reads.
//
// `tests/` is not scanned: a test harness legitimately manipulates the environment, and none of
// it ships.

import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const UI_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));

/** Everything that ships or runs in the browser tier. */
const SCANNED_EXTENSIONS = [".mjs", ".js", ".jsx", ".ts", ".tsx", ".mts", ".cts"];

/** Never scanned: build output, third-party code, and the harness that fakes environments. */
const SKIPPED_DIRECTORIES = new Set(["node_modules", ".next", "tests", ".git", "out"]);

/**
 * The ONE module allowed to touch `env[name]` directly, because reading it is its whole job.
 * Everything else calls `readEnvSetting`.
 */
const THREE_STATE_READER_MODULE = join("lib", "env-setting.mjs");

/** The helper the failure message points at, rather than describing it. */
const THREE_STATE_READER = "readEnvSetting";

/**
 * variable name -> why a two-state read of it is not a posture decision. Adding an entry is a
 * reviewable claim, not a way past the test: if the variable can widen access, relax a check,
 * choose a weaker credential path, name a host, an origin, an audience or a profile, it does not
 * belong here and the read belongs in `readEnvSetting`.
 */
export const TWO_STATE_READS_WITH_A_REASON = {
  AGENT_S2S_TOKEN:
    "the OUTBOUND service credential this proxy presents, and the one read the commons " +
    "deliberately left two-state. `hex_service_kit.s2s.client_headers` treats an emptied token " +
    "as absent because omitting an outbound credential grants nobody anything: the RECEIVER " +
    "decides, and the receiver (`make_require_service_caller`) is three-state, so an emptied " +
    "secret refuses there. Raising here would convert a receiver-enforced 401 into a caller " +
    "crash and move the decision to the end of the call that has no authority over it.",
};

/** Recursively collect the shipped sources this rule applies to. */
export function scannedSources(root = UI_ROOT) {
  const found = [];
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const full = join(root, entry.name);
    if (entry.isDirectory()) {
      if (SKIPPED_DIRECTORIES.has(entry.name)) continue;
      found.push(...scannedSources(full));
      continue;
    }
    if (SCANNED_EXTENSIONS.some((extension) => entry.name.endsWith(extension))) found.push(full);
  }
  return found.sort();
}

/**
 * Blank out comments, preserving line numbering and every string literal.
 *
 * Comments are removed because these modules deliberately QUOTE the two-state reads they
 * replaced, to say what the defect was, and a scanner that could not tell code from prose would
 * forbid explaining the very thing it guards. String literals are KEPT so the exact-match escape
 * can still see the literal it compares against. The walk is character by character rather than
 * regex-based so that `"http://127.0.0.1:8080"` is not mistaken for a line comment.
 */
export function codeOnly(source) {
  let out = "";
  let i = 0;
  while (i < source.length) {
    const two = source.slice(i, i + 2);
    if (two === "//") {
      while (i < source.length && source[i] !== "\n") i += 1;
      continue;
    }
    if (two === "/*") {
      i += 2;
      while (i < source.length && source.slice(i, i + 2) !== "*/") {
        if (source[i] === "\n") out += "\n";
        i += 1;
      }
      i += 2;
      continue;
    }
    const quote = source[i];
    if (quote === '"' || quote === "'" || quote === "`") {
      out += quote;
      i += 1;
      while (i < source.length && source[i] !== quote) {
        if (source[i] === "\\") {
          out += source[i];
          i += 1;
        }
        if (i < source.length) {
          out += source[i];
          i += 1;
        }
      }
      out += quote;
      i += 1;
      continue;
    }
    out += source[i];
    i += 1;
  }
  return out;
}

// `env.NAME` and `process.env.NAME`. The leading class stops `myenv.NAME` and `a.env.NAME`
// matching: only the parameter this codebase calls `env`, and the real `process.env`.
const DOTTED_READ = /(^|[^\w$.])(?:process\s*\.\s*)?env\s*\.\s*([A-Za-z_$][\w$]*)/g;
// `env["NAME"]` and `env[computed]`. A computed name is reported as such and is never
// exemptible: an exemption must name the VARIABLE, and nobody can name one chosen at runtime.
const INDEXED_READ = /(^|[^\w$.])(?:process\s*\.\s*)?env\s*\[\s*(?:"([^"]*)"|'([^']*)'|([^\]]+))\]/g;

/** Is this read immediately compared against a string literal? Then it is fail-closed already. */
function isExactMatch(code, endIndex) {
  return /^\s*[=!]==?\s*["'`]/.test(code.slice(endIndex));
}

/** `{ line, name }` for every environment read in `source`, exact matches excluded. */
export function environmentReads(source) {
  const code = codeOnly(source);
  const lineOf = (index) => code.slice(0, index).split("\n").length;
  const found = [];
  for (const [pattern, nameGroups] of [
    [DOTTED_READ, [2]],
    [INDEXED_READ, [2, 3, 4]],
  ]) {
    pattern.lastIndex = 0;
    let match = pattern.exec(code);
    while (match !== null) {
      const literal = nameGroups.slice(0, 2).find((group) => match[group] !== undefined);
      const name = literal === undefined ? "<computed at runtime>" : match[literal];
      if (!isExactMatch(code, match.index + match[0].length)) {
        found.push({ line: lineOf(match.index + match[1].length), name });
      }
      match = pattern.exec(code);
    }
  }
  return found.sort((a, b) => a.line - b.line);
}

/** `{ line, name }` for every two-state read in `source` that has no written excuse. */
export function findings(source) {
  return environmentReads(source).filter(
    (read) => !Object.hasOwn(TWO_STATE_READS_WITH_A_REASON, read.name),
  );
}

const shipped = scannedSources().filter(
  (path) => relative(UI_ROOT, path) !== THREE_STATE_READER_MODULE.split("/").join(sep),
);

test("the scan actually walks the shipped UI, rather than an empty set", () => {
  // A scanner nobody proved can find anything is a green tick over an empty tree.
  const names = shipped.map((path) => relative(UI_ROOT, path));
  assert.ok(names.length >= 5, "only " + names.length + " files scanned: " + names.join(", "));
  for (const required of ["lib/embed-policy.mjs", "lib/identity-policy.mjs", "next.config.mjs"]) {
    assert.ok(
      names.includes(required.split("/").join(sep)),
      required + " is not being scanned, so nothing guards its environment reads",
    );
  }
});

for (const path of shipped) {
  const name = relative(UI_ROOT, path);
  test("no two-state environment read in " + name, () => {
    const offenders = findings(readFileSync(path, "utf8")).map(
      (read) => name + ":" + read.line + ": reads " + read.name + " directly",
    );
    assert.deepEqual(
      offenders,
      [],
      "these reads collapse 'unset' and 'set to an empty value' into one state, so a variable " +
        "an operator deliberately emptied inherits the default, which for a relaxation is the " +
        "permissive branch. Use " +
        THREE_STATE_READER +
        " from lib/env-setting.mjs, compare the raw value against a literal, or add the " +
        "variable to TWO_STATE_READS_WITH_A_REASON with a reason it carries no posture:\n" +
        offenders.join("\n"),
    );
  });
}

test("the scan finds the exact wildcard-CORS mutant that survived the whole gate", () => {
  // Character for character what the verifier planted in lib/embed-policy.mjs.
  const mutant =
    "export function corsOriginFor(origin, env) {\n" +
    '  const allowed = env.UI_TENANT_ORIGINS || "*";\n' +
    "  return allowed;\n" +
    "}\n";
  assert.deepEqual(findings(mutant), [{ line: 2, name: "UI_TENANT_ORIGINS" }]);
});

test("the nullish spelling of the same defect is caught too", () => {
  const mutant = 'const ancestors = env.UI_FRAME_ANCESTORS ?? "*";\n';
  assert.deepEqual(findings(mutant), [{ line: 1, name: "UI_FRAME_ANCESTORS" }]);
});

test("the two-line spelling, with no default operator at all, is caught", () => {
  // What frameAncestors actually did: read, then collapse the two absent states with `if (!raw)`.
  const mutant = "const raw = env.UI_FRAME_ANCESTORS;\nif (!raw) return \"'self'\";\n";
  assert.deepEqual(findings(mutant), [{ line: 1, name: "UI_FRAME_ANCESTORS" }]);
});

test("process.env, bracket and computed reads are all caught", () => {
  assert.deepEqual(findings('process.env.UI_TENANT_ORIGINS || "*";\n'), [
    { line: 1, name: "UI_TENANT_ORIGINS" },
  ]);
  assert.deepEqual(findings('env["UI_TENANT_ORIGINS"] || "*";\n'), [
    { line: 1, name: "UI_TENANT_ORIGINS" },
  ]);
  assert.deepEqual(findings("const n = pick();\nenv[n] || nothing;\n"), [
    { line: 2, name: "<computed at runtime>" },
  ]);
});

test("the scan accepts the three-state reader and an exact-match relaxation", () => {
  const clean =
    'import { readEnvSetting } from "./env-setting.mjs";\n' +
    'const origins = readEnvSetting(env, "UI_TENANT_ORIGINS");\n' +
    'const optedIn = env.UI_ALLOW_INSECURE_DEMO === "1";\n';
  assert.deepEqual(findings(clean), []);
});

test("a two-state read QUOTED in prose is not mistaken for one in code", () => {
  // These modules describe the defect they prevent. A guard that could not tell code from
  // comment would forbid the explanation, so it would be deleted, so it would guard nothing.
  const prose =
    '// Reading `env.UI_TENANT_ORIGINS || "*"` is a wildcard.\n' +
    "/* and `env.UI_FRAME_ANCESTORS ?? DEFAULT` in the block comment below it */\n" +
    'const url = "http://127.0.0.1:8080";\n';
  assert.deepEqual(findings(prose), []);
});

test("a URL inside a string is not mistaken for the start of a comment", () => {
  // The naive `//` strip would truncate the line here and hide anything after it.
  const source = 'const base = "http://127.0.0.1:8080"; const x = env.SOME_ORIGINS;\n';
  assert.deepEqual(findings(source), [{ line: 1, name: "SOME_ORIGINS" }]);
});

test("only the environment parameter matches, not any object whose name ends in env", () => {
  assert.deepEqual(findings("myenv.SOMETHING;\nconfig.env.SOMETHING;\n"), []);
});

test("every exemption still matches a real read", () => {
  // An exemption that outlives its read silently pre-approves the next variable of that name.
  const read = new Set();
  for (const path of shipped) {
    for (const found of environmentReads(readFileSync(path, "utf8"))) read.add(found.name);
  }
  const stale = Object.keys(TWO_STATE_READS_WITH_A_REASON).filter((name) => !read.has(name));
  assert.deepEqual(stale, [], stale.join(", ") + " are exempted but nothing reads them any more");
});

test("every exemption carries a reason somebody can review", () => {
  const unexplained = Object.entries(TWO_STATE_READS_WITH_A_REASON)
    .filter(([, reason]) => reason.trim().length < 40)
    .map(([name]) => name);
  assert.deepEqual(unexplained, [], unexplained.join(", ") + " are exempted with no real reason");
});
