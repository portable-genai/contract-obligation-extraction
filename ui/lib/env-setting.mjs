// The three-state environment read, in JavaScript.
//
// This is the twin of `hex_service_kit.netdefaults.read_env_setting`, which the Python half of
// every catalog repo already uses. It exists because the UI layer had the SAME defect the Python
// layer was audited for, and nothing on this side could express the middle state:
//
//   unset            nobody expressed an intent, so a documented default may stand
//   set and empty    an intent WAS expressed and it names nothing, so fail closed
//   set with a value use it
//
// `env.X || "default"` and `env.X ?? "default"` collapse the first two into one branch. Where the
// default is the more permissive branch (a framing policy, a CORS allowlist, a profile) an
// operator who deliberately empties the variable, or a Terraform variable that renders to
// nothing, or a `.env` line left as `NAME=`, silently inherits the permissive default. Worse, the
// emptied deployment is then BYTE-IDENTICAL to one that never configured the variable at all, so
// a deliberate lockdown cannot be told apart from an omission in the response an operator reads.
//
// Every security-relevant read in `ui/` goes through here, and `tests/three-state-env-reads.test.mjs`
// fails the build on any that does not.

/** Raised when a variable is present but names nothing, and inheriting the default would widen. */
export class ConfiguredEmptyError extends Error {}

/**
 * @typedef {object} EnvSetting
 * @property {string} name              the variable read
 * @property {string | undefined} raw   the value exactly as the environment carried it
 * @property {string} value             `raw` trimmed, or "" when unset
 * @property {boolean} isUnset          absent from the environment: nobody chose
 * @property {boolean} isConfiguredEmpty present and blank: somebody chose nothing
 * @property {boolean} hasValue         present and non-blank
 */

/**
 * Read `name` into its three mutually exclusive states.
 *
 * The value is trimmed, so the value a guard judges is exactly the value a caller uses: a
 * trailing newline out of a config map passes the check and then fails the thing it
 * configured.
 *
 * @param {Record<string, string | undefined>} env
 * @param {string} name
 * @returns {EnvSetting}
 */
export function readEnvSetting(env, name) {
  const present = env[name] !== undefined && env[name] !== null;
  const raw = present ? String(env[name]) : undefined;
  const value = raw === undefined ? "" : raw.trim();
  return {
    name,
    raw,
    value,
    isUnset: !present,
    isConfiguredEmpty: present && value === "",
    hasValue: present && value !== "",
  };
}
