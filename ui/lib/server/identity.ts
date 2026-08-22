// Server-side identity resolution. This module is the ONLY place an actor is decided, and it
// never reads a value the browser supplied.
//
// The decisions themselves live in `../identity-policy.mjs`, in plain JavaScript, so `npm test`
// exercises them in bare node with no bundler and no browser. This file is the typed seam the
// route imports: types, re-exports, and nothing that decides anything.
//
// The three profiles mirror the service's own, and `UI_PROFILE` is read in THREE states:
//
//   unset   nobody chose. REFUSED, not defaulted: a deployment whose profile variable went
//           missing must not start seeding dev personas. This is the same rule the service's
//           own seeded-persona adapter enforces, on the same reasoning.
//   local   seeded dev personas, no IdP, no AD, no LDAP, chosen DELIBERATELY. The picker in the
//           page selects one, but the SELECTION is validated here against a fixed list, so a
//           hand-crafted request cannot invent a persona (or an ACL) the deployment never seeded.
//   secure  the platform in front of this UI authenticates the user and injects a SIGNED
//           assertion. The proxy forwards that assertion to the service, which verifies it. The
//           UI never parses it and never trusts a parsed copy of it.
//   onprem  the client's own identity provider. Deliberately unimplemented: it refuses rather
//           than falling back to the local personas, because a silent fallback here would turn a
//           misconfigured deployment into an unauthenticated one.
//
// `import "server-only"` is not used, so this module stays testable with plain node; the guard is
// that nothing here is imported from a "use client" module.

import {
  IdentityError,
  SEEDED_PERSONAS,
  apiBaseUrl,
  identityFor,
  resolveProfile,
  serviceCredentialHeaders,
} from "../identity-policy.mjs";

export type Profile = "local" | "secure" | "onprem";

export type Persona = (typeof SEEDED_PERSONAS)[number];

export interface ProfileChoice {
  /** The profile to serve. Meaningless unless `explicit` is true. */
  profile: Profile;
  /** Was `UI_PROFILE` actually set? False means nobody chose, which is never consent. */
  explicit: boolean;
}

export interface ResolvedIdentity {
  /** Headers to ADD to the forwarded request. Never copied from the incoming request. */
  headers: Record<string, string>;
  /** What the UI may display. Never used for an authorization decision. */
  label: string;
}

export { IdentityError, SEEDED_PERSONAS };

/**
 * Resolve `UI_PROFILE` into its three states. Unset yields `explicit: false`; set-and-empty and
 * set-and-unknown both throw an `IdentityError`, so neither can inherit the offline default.
 */
export function activeProfileChoice(env: Record<string, string | undefined>): ProfileChoice {
  return resolveProfile(env) as ProfileChoice;
}

/**
 * Decide the identity headers to forward. `incoming` is read ONLY for the dev persona selection
 * under a DELIBERATE local profile, and even then only as a hint validated against the seeded
 * list. Throws `IdentityError` when no profile was chosen, when the chosen one has no IdP wired,
 * and when a `secure` deployment receives a request with no signed assertion.
 */
export function resolveIdentity(
  incoming: Headers,
  env: Record<string, string | undefined>,
): ResolvedIdentity {
  return identityFor(incoming, env) as ResolvedIdentity;
}

/** The service-to-service credential, read from the SERVER environment and never exposed. */
export function serviceHeaders(env: Record<string, string | undefined>): Record<string, string> {
  return serviceCredentialHeaders(env);
}

/** Base URL of the service API this UI proxies to. Loopback by default, never a public host. */
export function serviceBaseUrl(env: Record<string, string | undefined>): string {
  return apiBaseUrl(env);
}
