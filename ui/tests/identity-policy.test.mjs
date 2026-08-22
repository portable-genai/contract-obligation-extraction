// The UI's identity boundary, tested with no framework and no browser: plain node, run by
// `npm test` and by the ui-gate workflow on every push.
//
// The defect these cover has actually shipped: `activeProfile` did
//
//     const raw = (env.UI_PROFILE ?? "").trim();
//     if (!raw) return "local";
//
// so an unset or blanked UI_PROFILE yielded the seeded-persona profile, and `resolveIdentity`
// forwarded `X-Dev-Persona` (defaulting to `analyst`) to the API. A deployment that lost one
// environment variable therefore authenticated every caller as a seeded analyst. Two states
// where there are three, in TypeScript, exactly as in the Python resolver next to it.

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  IdentityError,
  KNOWN_PROFILES,
  SEEDED_PERSONAS,
  apiBaseUrl,
  identityFor,
  resolveProfile,
  serviceCredentialHeaders,
  validatedPersona,
} from "../lib/identity-policy.mjs";

const headers = (init = {}) => new Headers(init);

test("an unset profile is NO CHOICE, and it is never read as a chosen local", () => {
  const choice = resolveProfile({});
  assert.equal(choice.explicit, false);
  assert.notEqual(choice.explicit, true);
});

test("an unset profile refuses to seed a persona rather than defaulting to analyst", () => {
  assert.throws(
    () => identityFor(headers(), {}),
    (error) => error instanceof IdentityError && /not set/.test(error.message),
  );
});

test("a profile SET to an empty value refuses and does not inherit the unset default", () => {
  for (const blank of ["", "   ", "\t", "\n"]) {
    assert.throws(
      () => resolveProfile({ UI_PROFILE: blank }),
      (error) => error instanceof IdentityError && /empty value/.test(error.message),
      "UI_PROFILE=" + JSON.stringify(blank) + " was accepted",
    );
    assert.throws(() => identityFor(headers(), { UI_PROFILE: blank }), IdentityError);
  }
});

test("an unknown or mis-capitalised profile is refused rather than coerced", () => {
  for (const bogus of ["Local", "LOCAL", "Secure", "on-prem", "bogus"]) {
    assert.throws(
      () => resolveProfile({ UI_PROFILE: bogus }),
      (error) => error instanceof IdentityError && /not a known profile/.test(error.message),
      "UI_PROFILE=" + bogus + " was accepted",
    );
  }
});

test("every known profile is selectable, and only deliberately", () => {
  for (const profile of KNOWN_PROFILES) {
    const choice = resolveProfile({ UI_PROFILE: profile });
    assert.deepEqual(choice, { profile, explicit: true });
  }
});

test("a DELIBERATE local profile still serves the offline demo", () => {
  const resolved = identityFor(headers({ "x-dev-persona": "approver" }), { UI_PROFILE: "local" });
  assert.equal(resolved.headers["X-Dev-Persona"], "approver");
});

test("a persona the deployment never seeded cannot be invented by the browser", () => {
  const resolved = identityFor(headers({ "x-dev-persona": "root" }), { UI_PROFILE: "local" });
  assert.equal(resolved.headers["X-Dev-Persona"], SEEDED_PERSONAS[0]);
  assert.equal(validatedPersona("root"), SEEDED_PERSONAS[0]);
});

test("the secure profile forwards a signed assertion and refuses a request without one", () => {
  const env = { UI_PROFILE: "secure" };
  const withAssertion = identityFor(headers({ "x-goog-iap-jwt-assertion": "signed.jwt" }), env);
  assert.equal(withAssertion.headers["X-Goog-IAP-JWT-Assertion"], "signed.jwt");
  assert.throws(() => identityFor(headers(), env), IdentityError);
});

test("the onprem profile refuses rather than falling back to the dev personas", () => {
  assert.throws(
    () => identityFor(headers(), { UI_PROFILE: "onprem" }),
    (error) => error instanceof IdentityError && /no identity provider/.test(error.message),
  );
});

test("no profile state ever yields a persona header except a deliberate local", () => {
  const states = [{}, { UI_PROFILE: "" }, { UI_PROFILE: "Local" }, { UI_PROFILE: "onprem" }];
  for (const env of states) {
    let resolved = null;
    try {
      resolved = identityFor(headers({ "x-dev-persona": "approver" }), env);
    } catch (error) {
      assert.ok(error instanceof IdentityError);
    }
    assert.equal(resolved, null, "a persona was seeded for " + JSON.stringify(env));
  }
});

test("the OUTBOUND credential stays two-state ON PURPOSE, matching the commons", () => {
  // Deliberately NOT three-stated, and exempted by name in three-state-env-reads.test.mjs.
  // This is the calling side: omitting an outbound credential grants nobody anything, because
  // the receiver decides, and the receiver refuses an emptied secret itself. Raising here would
  // turn a receiver-enforced 401 into a caller crash. Pinned so nobody "fixes" it by reflex.
  assert.deepEqual(serviceCredentialHeaders({}), {});
  assert.deepEqual(serviceCredentialHeaders({ AGENT_S2S_TOKEN: "" }), {});
  assert.deepEqual(serviceCredentialHeaders({ AGENT_S2S_TOKEN: "   " }), {});
  assert.deepEqual(serviceCredentialHeaders({ AGENT_S2S_TOKEN: "t" }), {
    Authorization: "Bearer t",
  });
});

test("the API base URL defaults to loopback and never carries a trailing slash", () => {
  assert.equal(apiBaseUrl({}), "http://127.0.0.1:8080");
  assert.equal(apiBaseUrl({ AGENT_API_URL: "https://svc.bank.example/" }), "https://svc.bank.example");
  assert.equal(apiBaseUrl({ AGENT_API_URL: "  https://svc.bank.example  " }), "https://svc.bank.example");
});

test("an EMPTIED service address refuses rather than quietly proxying to loopback", () => {
  // An empty string is not a URL. Inheriting the loopback default would make a deployment whose
  // service address rendered empty indistinguishable from one that never configured it, and it
  // would report connection failures that name no cause.
  for (const blank of ["", "   ", "\n"]) {
    assert.throws(
      () => apiBaseUrl({ AGENT_API_URL: blank }),
      (error) => error instanceof IdentityError && /set but empty/.test(error.message),
      "AGENT_API_URL=" + JSON.stringify(blank) + " was accepted",
    );
  }
});
