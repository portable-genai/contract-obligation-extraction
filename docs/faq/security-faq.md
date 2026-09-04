# Security FAQ

For AppSec and security architecture. Every answer names the file that is the evidence, so the
review can read the control rather than the claim.

### Who is the actor on a decision, and can a caller assert it?

A server-verified `Principal`, always. The request schemas carry no `actor` field: the audit actor
and the review maker both come from the identity adapter, and every client-supplied actor, tenant,
role, ACL and authorization header is discarded at the browser boundary
(`ui/lib/embed-policy.mjs`). Under the `gcp` profile the adapter verifies the IAP-injected
assertion against the configured audience, against IAP's own key set and against the issuer
(`adapters/gcp/identity.py`); an unset or emptied `CONTRACT_IAP_AUDIENCE` REFUSES every caller,
because `audience=None` means google-auth does not verify the audience at all and would accept any
Google-signed token from any project.

### What is the largest risk in a system like this?

A contract is UNTRUSTED THIRD-PARTY TEXT, written by a counterparty, that this system feeds to a
model. That is the highest-value prompt-injection target in the catalog: a clause crafted to read
as an instruction could try to suppress a liability-cap flag or invent a termination date.

Two things stand between that and a wrong register, and only one of them is in place:

- **In place:** the model can only PROPOSE. `domain/flags.py` and `domain/contracts.py` decide
  admissibility against a frozen taxonomy, a proposal outside the taxonomy is dropped rather than
  coerced, an ambiguous proposal is routed to a human, and no date arithmetic is ever the model's.
  So a successful injection changes what is proposed, not what is admitted unreviewed.
- **NOT in place:** screening. The `agent-guardrail-gateway` is not bound in front of
  `ExtractionPort`. Rule R1 in `COMPLIANCE.md` records that, and it is the highest-priority
  security item for this repo.

### What does the extraction seam actually do today?

It refuses. `adapters/gcp/extraction.py` is a DECLARED seam: it names the model it would use and
raises `NotImplementedError`, because the Document AI processor id and layout configuration are
per-deployment. Offline, `domain/corpus.py` replays canned proposals against five fictional
contracts. So the managed document path has never run, which is worth knowing before it is
reviewed as if it had.

### What happens if the profile variable goes missing in production?

The process still binds the SDK-free adapters (the alternative is importing cloud SDKs that are
not installed), but nobody chose them, so every relaxation is withdrawn: the seeded dev personas
refuse to construct, no service-to-service scheme is selected, the dev CORS allowlist and the
`X-Dev-Persona` header are gone, the interactive docs are not registered, and the loopback
exposure guard refuses every route to any non-loopback peer. An emptied or mis-capitalised value
raises AT IMPORT, so the process fails to boot rather than serving on a posture nobody chose
(`config.py`, `tests/unit/test_profile_single_source.py`).

### Does setting the service-to-service token open anything?

No, and this is enforced rather than intended. The exposure guard's posture is derived from the
identity BINDING (the adapter declares `VERIFIED` / `CLIENT_ASSERTED` / `UNIMPLEMENTED`), never
from a credential. `CONTRACT_S2S_TOKEN` authenticates a calling SERVICE and no end user.
`tests/unit/test_end_user_auth_posture.py` walks the guard's argument through the constants it
names and fails the build if a credential reappears at any depth.

### Where does personal data go?

Contracts carry counterparty names, signatory names and contact details, so redaction runs before
every boundary rather than once at the end: before the audit write, before a review payload leaves
the process, and before a tool result can enter a model's context. The pattern set and its ORDER
are this vertical's (`domain/pii.py`, national rows first, universal rows last), drawn from the
shared `pii-kit`. The `pii_safety` eval metric holds this at `>= 0.99` and
`tests/unit/test_not_falsely_green.py` proves the metric can go red.

Where the SOURCE documents live is an adopter decision and a bigger one than the redaction: this
repo reads a corpus, it does not own a document store.

### How is the audit trail protected?

Append-only and hash-chained, AND externally anchored. The chain catches an edit, a deletion or a
reorder; only the anchor catches a TRUNCATED TAIL, because dropping the newest rows leaves a
shorter chain that verifies perfectly. `audit_anchor_path` (`CONTRACT_AUDIT_ANCHOR`) writes the
chain head to a file on another volume, and `tests/unit/test_audit_anchor.py` proves the
detection, proves the control case goes UNDETECTED without an anchor, and proves an append after
truncation refuses rather than re-anchoring. Under the managed profile the sink is a locked Cloud
Logging bucket (`infra/terraform/logging_worm.tf`).

### What about supply chain?

Both lockfiles are committed and pin every dependency exactly; the catalog commons, including
`obligation-register-kit`, are pinned to 40-character COMMIT shas rather than tags, because a
re-pushed tag changes what installs with no diff in the lockfile. The base image is digest-pinned,
Actions are SHA-pinned, dependabot covers pip, docker, github-actions and npm, and `pip-audit`
plus `npm audit --audit-level=high` are HARD CI failures. `tests/unit/test_repo_artifacts.py`
asserts each of these from inside the repo, and it asks git whether each pinned sha is a COMMIT
object rather than an annotated tag object.

### What is deliberately out of scope?

- **Login.** This repo authenticates nobody itself: the platform in front of it does.
- **Injection defence and output filtering.** Owned by `agent-guardrail-gateway`; not bound, and needed here.
- **The document store.** This service reads a corpus; where contracts live, who may read them and
  how long they are kept are adopter controls.
- **The review queue.** Owned by `human-review-console`; this repo produces escalations and routes them.
- **Network egress control.** VPC-SC governs access to Google APIs across perimeters, not
  arbitrary internet egress. The private-egress rule is an adopter network decision, called out in
  `COMPLIANCE.md` P-01.
