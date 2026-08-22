// The embedding policy is the UI's security boundary, so it gets tests with no framework and no
// browser: plain node, run by `npm test`, by the ui-gate workflow on every push, and by the
// template's own render gate.
//
// Each test is a defect that has actually shipped somewhere before: a wildcard origin honoured
// because it was in the allowlist string, an actor header forwarded because the proxy copied
// every header, an empty allowlist treated as "allow everything", and the one this file was
// rewritten for: an emptied allowlist answering exactly like an unset one, so a deliberate
// lockdown and a lost environment variable produced the same bytes.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  CLIENT_ASSERTED_IDENTITY_HEADERS,
  ConfiguredEmptyError,
  UnhydratableCspError,
  assertEmbedPolicyConfigured,
  assertHydratableCsp,
  corsOriginFor,
  frameAncestors,
  generateNonce,
  isEmbeddable,
  parseAllowlist,
  securityHeaders,
  stripClientIdentity,
  tenantOrigins,
} from "../lib/embed-policy.mjs";

test("an UNSET framing allowlist means embeddable by nobody but itself", () => {
  assert.equal(frameAncestors({}), "'self'");
  assert.equal(isEmbeddable({}), false);
  assert.equal(securityHeaders({})["X-Frame-Options"], "SAMEORIGIN");
});

test("an EMPTIED framing allowlist refuses instead of answering like an unset one", () => {
  // The defect, executed: unset, "", "   " and "," all yielded frame-ancestors 'self' plus
  // X-Frame-Options: SAMEORIGIN, byte for byte, so nothing an operator could read told the two
  // apart. Emptying a variable is an expressed intent; it does not inherit the shipped default.
  for (const blank of ["", "   ", "\t", "\n"]) {
    assert.throws(
      () => frameAncestors({ UI_FRAME_ANCESTORS: blank }),
      (error) => error instanceof ConfiguredEmptyError && /set but empty/.test(error.message),
      "UI_FRAME_ANCESTORS=" + JSON.stringify(blank) + " was accepted",
    );
    assert.throws(() => securityHeaders({ UI_FRAME_ANCESTORS: blank }), ConfiguredEmptyError);
  }
});

test("a value that names no origin refuses too, however it is spelled", () => {
  for (const nothing of [",", " , , ", "*", "'*'", "null", "*, *"]) {
    assert.throws(
      () => frameAncestors({ UI_FRAME_ANCESTORS: nothing }),
      ConfiguredEmptyError,
      "UI_FRAME_ANCESTORS=" + JSON.stringify(nothing) + " was accepted",
    );
    assert.throws(
      () => corsOriginFor("https://bank.example", { UI_TENANT_ORIGINS: nothing }),
      ConfiguredEmptyError,
      "UI_TENANT_ORIGINS=" + JSON.stringify(nothing) + " was accepted",
    );
  }
});

test("a wildcard is never honoured, whatever else is in the list", () => {
  assert.deepEqual(parseAllowlist("*"), []);
  assert.deepEqual(parseAllowlist("https://a.bank.example, *"), ["https://a.bank.example"]);
  assert.equal(corsOriginFor("*", { UI_TENANT_ORIGINS: "https://a.bank.example" }), null);
});

test("a list containing a wildcard is REFUSED, not quietly narrowed to the rest", () => {
  // A dropped wildcard with the remaining origins honoured means an operator who
  // wrote two entries got a policy with one and no way to see it. The dropped entry is the one
  // that would have mattered.
  for (const configured of ["https://a.bank.example *", "*, https://a.bank.example"]) {
    assert.throws(
      () => frameAncestors({ UI_FRAME_ANCESTORS: configured }),
      ConfiguredEmptyError,
      "UI_FRAME_ANCESTORS=" + JSON.stringify(configured) + " was accepted",
    );
  }
});

test("a wildcard hiding inside an origin is refused too", () => {
  // The refusal matched a fixed set of exact tokens, so a host-source wildcard was in no set and
  // was emitted verbatim. CSP honours that form, so every subdomain could frame the console,
  // including one obtained by takeover or served as user content.
  for (const configured of [
    "https://*.bank.example",
    "*.bank.example",
    "https://*",
    "https://a.bank.example https://*.evil.example",
  ]) {
    assert.throws(
      () => frameAncestors({ UI_FRAME_ANCESTORS: configured }),
      ConfiguredEmptyError,
      "UI_FRAME_ANCESTORS=" + JSON.stringify(configured) + " was accepted",
    );
    assert.throws(
      () => tenantOrigins({ UI_TENANT_ORIGINS: configured }),
      ConfiguredEmptyError,
      "UI_TENANT_ORIGINS=" + JSON.stringify(configured) + " was accepted",
    );
  }
  assert.equal(corsOriginFor("https://*.bank.example", { UI_TENANT_ORIGINS: "https://a.bank.example" }), null);
});

test("named parent origins are allowed, and X-Frame-Options stops contradicting them", () => {
  const env = { UI_FRAME_ANCESTORS: "https://a.bank.example https://b.bank.example" };
  assert.equal(frameAncestors(env), "https://a.bank.example https://b.bank.example");
  assert.equal(isEmbeddable(env), true);
  const headers = securityHeaders(env);
  assert.ok(headers["Content-Security-Policy"].includes("frame-ancestors https://a.bank.example"));
  assert.equal(headers["X-Frame-Options"], undefined);
});

test("'none' is the spelling for refusing framing outright, and it must stand alone", () => {
  const env = { UI_FRAME_ANCESTORS: "'none'" };
  assert.equal(frameAncestors(env), "'none'");
  assert.equal(isEmbeddable(env), false);
  assert.equal(securityHeaders(env)["X-Frame-Options"], "DENY");
  assert.throws(
    () => frameAncestors({ UI_FRAME_ANCESTORS: "'none' https://a.bank.example" }),
    (error) => error instanceof ConfiguredEmptyError && /no meaning beside/.test(error.message),
  );
});

test("CORS is per tenant: a registered origin is echoed, an unregistered one is denied", () => {
  const env = { UI_TENANT_ORIGINS: "https://a.bank.example, https://b.bank.example" };
  assert.deepEqual(tenantOrigins(env), ["https://a.bank.example", "https://b.bank.example"]);
  assert.equal(corsOriginFor("https://a.bank.example", env), "https://a.bank.example");
  assert.equal(corsOriginFor("https://evil.example", env), null);
  assert.equal(corsOriginFor(null, env), null);
});

test("an UNSET tenant allowlist denies rather than opening up", () => {
  // Unset is already the restrictive branch here, so it stands rather than refusing.
  assert.deepEqual(tenantOrigins({}), []);
  assert.equal(corsOriginFor("https://a.bank.example", {}), null);
});

test("an EMPTIED tenant allowlist refuses, on every request, not only cross-origin ones", () => {
  assert.throws(() => tenantOrigins({ UI_TENANT_ORIGINS: "" }), ConfiguredEmptyError);
  // Resolved before the cheap `!origin` exit: a same-origin request must not silently skip the
  // check that would have told the operator the allowlist selects nothing.
  assert.throws(() => corsOriginFor(null, { UI_TENANT_ORIGINS: "" }), ConfiguredEmptyError);
});

test("the boot-time assertion refuses exactly what the per-request functions refuse", () => {
  assert.doesNotThrow(() => assertEmbedPolicyConfigured({}));
  assert.doesNotThrow(() =>
    assertEmbedPolicyConfigured({
      UI_FRAME_ANCESTORS: "https://portal.bank.example",
      UI_TENANT_ORIGINS: "https://portal.bank.example",
    }),
  );
  for (const env of [{ UI_FRAME_ANCESTORS: "" }, { UI_TENANT_ORIGINS: "" }, { UI_FRAME_ANCESTORS: "*" }]) {
    assert.throws(
      () => assertEmbedPolicyConfigured(env),
      ConfiguredEmptyError,
      JSON.stringify(env) + " would have booted",
    );
  }
});

test("every client-asserted identity header is discarded before forwarding", () => {
  const incoming = new Headers({ "Content-Type": "application/json" });
  for (const name of CLIENT_ASSERTED_IDENTITY_HEADERS) {
    incoming.set(name, "attacker-supplied");
  }
  incoming.set("cookie", "session=1");
  const forwarded = stripClientIdentity(incoming);
  for (const name of CLIENT_ASSERTED_IDENTITY_HEADERS) {
    assert.equal(forwarded.get(name), null, name + " survived the proxy hop");
  }
  assert.equal(forwarded.get("cookie"), null);
  assert.equal(forwarded.get("content-type"), "application/json");
});

test("the security header baseline is complete on every response", () => {
  const headers = securityHeaders({});
  for (const name of [
    "Content-Security-Policy",
    "Referrer-Policy",
    "X-Content-Type-Options",
    "Cross-Origin-Opener-Policy",
  ]) {
    assert.ok(headers[name], name + " is missing from the baseline");
  }
  assert.ok(headers["Content-Security-Policy"].includes("object-src 'none'"));
  assert.ok(!headers["Content-Security-Policy"].includes("unsafe-eval"));
});

// The hydration half of the policy. These exist because the defect they guard is INVISIBLE to
// every cheap check: `script-src 'self'` serves a page whose headers are correct, whose module
// tests pass and whose screenshot looks right, while Next's inline hydration bootstrap is
// blocked, `__next_f` stays empty and React never attaches. The console is dead markup.
//
// The half-fix is worse than the defect, which is the reason `assertHydratableCsp` exists. Minting
// a nonce while the route is still statically prerendered means nothing carries the nonce AND
// `'strict-dynamic'` switches off the `'self'` fallback that was at least loading the chunk
// scripts, so strictly more is blocked than before. A CSP assertion alone cannot see that: the
// header is identical either way. Only the rendering mode tells the two apart.

test("a nonce turns script-src into a policy Next can actually hydrate under", () => {
  const nonce = generateNonce();
  const csp = securityHeaders({}, nonce)["Content-Security-Policy"];
  assert.ok(csp.includes(`script-src 'self' 'nonce-${nonce}' 'strict-dynamic'`), csp);
  const scriptSrc = csp.split("; ").find((directive) => directive.startsWith("script-src"));
  // The fix is a nonce. A blanket inline allowance would hydrate too, and would also let any
  // injected inline script run, which is the whole thing the policy is for.
  assert.ok(!scriptSrc.includes("unsafe-inline"), "unsafe-inline is not the fix");
  assert.ok(!scriptSrc.includes("unsafe-eval"));
});

test("without a nonce script-src stays the strict self-only default", () => {
  const csp = securityHeaders({})["Content-Security-Policy"];
  assert.ok(csp.includes("script-src 'self'"));
  assert.ok(!csp.includes("nonce-"), "a response with no document needs no nonce");
});

test("each nonce is fresh, because a reused nonce is a guessable one", () => {
  assert.notEqual(generateNonce(), generateNonce());
  assert.ok(generateNonce().length >= 20);
});

test("the shipped layout forces the dynamic rendering the nonce requires", () => {
  const layout = readFileSync(new URL("../app/layout.tsx", import.meta.url), "utf8");
  assertHydratableCsp(layout);
});

test("assertHydratableCsp can go red, so its green means something", () => {
  // The mutant is the exact regression: a layout that lost the force-dynamic line. Without this
  // control the assertion could be checking nothing at all and would still pass.
  assert.throws(
    () => assertHydratableCsp('export const metadata = { title: "Agent console" };\n'),
    UnhydratableCspError,
  );
  assert.throws(() => assertHydratableCsp('export const dynamic = "auto";\n'), UnhydratableCspError);
});
