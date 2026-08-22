// The identity policy, as pure functions with no framework, no I/O and no Next.js.
//
// It lives in a plain module for the same reason `embed-policy.mjs` does: so `npm test` can run
// it in bare node, with no bundler and no browser. `lib/server/identity.ts` is the typed seam the
// route imports; every DECISION is here, where it is tested.
//
// `UI_PROFILE` has THREE states, and the difference between the first two is the whole point:
//
//   unset            nobody chose. This is a deployment whose environment lost a variable, and
//                    it is NOT a request for the seeded dev personas. It refuses.
//   set and empty    an intent was expressed and it names no profile. It refuses, loudly, and it
//                    never inherits the unset default.
//   set to a name    honoured exactly: `local`, `secure` or `onprem`. A mis-capitalised value is
//                    refused rather than coerced, so a typo cannot downgrade the posture.
//
// Doing `const raw = (env.UI_PROFILE ?? "").trim(); if (!raw) return
// "local";` folds the first two states into the third-most-permissive one: an unset or
// blanked variable yields the seeded-persona profile, and `resolveIdentity` then forwards
// `X-Dev-Persona` (defaulting to `analyst`) to the API on every request. The skill this UI is
// built from requires this adapter to REFUSE rather than seed a persona when the profile is not
// deliberately local, and refusing is what it does.
//
// Every read here goes through `readEnvSetting`, the JavaScript twin of the commons'
// `read_env_setting`, with ONE deliberate exception recorded at `serviceCredentialHeaders`.

import { readEnvSetting } from "./env-setting.mjs";

/** Raised for every identity decision that cannot be made safely. The route answers it with 401. */
export class IdentityError extends Error {}

/** The profiles this UI knows how to serve. Anything else is a configuration error. */
export const KNOWN_PROFILES = ["local", "secure", "onprem"];

/** The seeded offline personas. Must match the service's local identity adapter. */
export const SEEDED_PERSONAS = ["analyst", "approver", "auditor", "other-tenant"];

/**
 * Resolve `UI_PROFILE` into its three states.
 *
 * Returns `{ profile, explicit }`. `explicit` is false ONLY when the variable is absent, and a
 * caller must treat that as "no posture was chosen" rather than as `local`. Throws for a value
 * that is present but empty, and for one that is present and unknown.
 *
 * @param {Record<string, string | undefined>} env
 * @returns {{ profile: string, explicit: boolean }}
 */
export function resolveProfile(env) {
  const setting = readEnvSetting(env, "UI_PROFILE");
  if (setting.isUnset) {
    // Absent. Carry "nobody chose" forward as its own state; do not invent consent.
    return { profile: "local", explicit: false };
  }
  const value = setting.value;
  if (setting.isConfiguredEmpty) {
    throw new IdentityError(
      "UI_PROFILE is set to an empty value, which is not a profile. A variable that was " +
        "deliberately emptied is not the same as an unset one, so it does not inherit the " +
        "offline default. Unset it, or set it to one of: " +
        KNOWN_PROFILES.join(", "),
    );
  }
  if (!KNOWN_PROFILES.includes(value)) {
    // Refused, not coerced: a mis-capitalised value must not silently downgrade the posture.
    throw new IdentityError(
      "UI_PROFILE=" + value + " is not a known profile; expected one of: " + KNOWN_PROFILES.join(", "),
    );
  }
  return { profile: value, explicit: true };
}

/**
 * Validate a requested dev persona against the seeded list.
 * @param {string | null | undefined} requested
 * @returns {string}
 */
export function validatedPersona(requested) {
  const wanted = (requested ?? "").trim();
  const found = SEEDED_PERSONAS.find((persona) => persona === wanted);
  return found ?? SEEDED_PERSONAS[0];
}

/**
 * Decide the identity headers to forward, from the deployment's own signal.
 *
 * `incoming` is read ONLY for the dev persona selection under a DELIBERATE local profile, and
 * even then only as a hint validated against the seeded list.
 *
 * @param {Headers} incoming
 * @param {Record<string, string | undefined>} env
 * @returns {{ headers: Record<string, string>, label: string }}
 */
export function identityFor(incoming, env) {
  const choice = resolveProfile(env);
  if (!choice.explicit) {
    throw new IdentityError(
      "UI_PROFILE is not set, so the local profile was inherited rather than chosen. The " +
        "seeded dev personas authenticate nobody, and seeding one for a deployment whose " +
        "profile variable went missing would turn a misconfiguration into an unauthenticated " +
        "deployment. Set UI_PROFILE=local deliberately for a demo, or UI_PROFILE=secure behind " +
        "an identity-aware proxy.",
    );
  }
  if (choice.profile === "local") {
    const persona = validatedPersona(incoming.get("x-dev-persona"));
    return { headers: { "X-Dev-Persona": persona }, label: persona + " (seeded dev persona)" };
  }
  if (choice.profile === "secure") {
    const assertion = incoming.get("x-goog-iap-jwt-assertion");
    if (!assertion) {
      throw new IdentityError(
        "no signed identity assertion on the request: this deployment must sit behind an " +
          "identity-aware proxy, and an unauthenticated request must not reach the service",
      );
    }
    return {
      headers: { "X-Goog-IAP-JWT-Assertion": assertion },
      label: "verified by the platform",
    };
  }
  throw new IdentityError(
    "the onprem profile has no identity provider wired: bind the client's own IdP here " +
      "(see ui/README.md). Falling back to dev personas would be an unauthenticated deployment.",
  );
}

/**
 * The service-to-service credential, read from the SERVER environment and never exposed.
 *
 * DELIBERATELY two-state, and exempted by name in `tests/three-state-env-reads.test.mjs`. This
 * is the CALLING side, and it follows `hex_service_kit.s2s.client_headers`, which the commons
 * left two-state on purpose while three-stating everything around it: omitting an outbound
 * credential grants nobody anything, because the RECEIVER decides. The service this proxy calls
 * verifies callers with `make_require_service_caller`, which is three-state and refuses a
 * request whose expected secret was emptied. So an operator who blanks `AGENT_S2S_TOKEN` gets a
 * refusal from the party entitled to issue one, with the audit record on the side that has the
 * authority; raising here instead would convert that receiver-enforced 401 into a caller crash
 * and move the decision to the wrong end of the call.
 *
 * The read that WOULD be a posture decision is the receiving side's, and it is not in this repo's
 * UI at all. Nothing here widens on an empty value: the header is simply absent, which is the
 * least authority this proxy can present.
 *
 * @param {Record<string, string | undefined>} env
 * @returns {Record<string, string>}
 */
export function serviceCredentialHeaders(env) {
  const token = (env.AGENT_S2S_TOKEN ?? "").trim();
  return token ? { Authorization: "Bearer " + token } : {};
}

/** Where the proxy forwards when nobody named a service. Loopback, never a public host. */
export const DEFAULT_API_BASE_URL = "http://127.0.0.1:8080";

/**
 * Base URL of the service API this UI proxies to. Loopback by default, never a public host.
 *
 * Read in three states: an emptied `AGENT_API_URL` REFUSES rather than falling back to loopback.
 * An empty string is not a URL, and a deployment whose service address rendered empty is a
 * deployment that should say so at once instead of quietly proxying to a port on its own
 * container and reporting connection failures that name no cause.
 *
 * @param {Record<string, string | undefined>} env
 * @returns {string}
 */
export function apiBaseUrl(env) {
  const setting = readEnvSetting(env, "AGENT_API_URL");
  if (setting.isConfiguredEmpty) {
    throw new IdentityError(
      "AGENT_API_URL is set but empty, which is not a URL. Inheriting the " +
        DEFAULT_API_BASE_URL +
        " default would make a deployment whose service address rendered empty look exactly " +
        "like one that never configured it. Unset AGENT_API_URL for the loopback default, or " +
        "give it the address of the service this UI fronts.",
    );
  }
  return (setting.value || DEFAULT_API_BASE_URL).replace(/\/+$/, "");
}
