---
name: deploy-and-residency-hardening
description: >-
  Make a repo's cloud posture enforceable at deploy time, not merely documented: a per-repo
  Dockerfile plus infra/terraform that pins data residency to an in-country region, applies
  Org Policy (resource-location allowlist, no service-account keys), binds CMEK end to end,
  stands up a dry-run-first VPC-SC perimeter, writes WORM audit logs, and alerts on guardrail
  blocks / key creation / perimeter denials. Use when adding deployment to a scaffolded repo,
  hardening residency/sovereignty/CMEK/VPC-SC, or when asked to "make it deployable",
  "add the infra", or "pin the region".
---

# Deploy-time and residency hardening (infrastructure as code)

The application skills (`ports-and-adapters-repo`, `deterministic-domain-service`,
`audit-first-demo`) make a repo correct and portable. This skill makes its **deployed**
posture enforceable. The rule it encodes: a control that lives only in a document is not a
control. Residency, encryption, perimeter, and audit are pinned in `infra/terraform/` so
`terraform plan` fails when a deploy would violate them, and a reviewer can read the control
next to the resource it governs.

The reference cloud is Google Cloud (Terraform + GCP). The shape (region allowlist, location
policy, customer-managed keys, a network perimeter, immutable audit logs, posture alerts) maps
to any managed cloud; keep the structure, swap the provider resources. It is realized most
fully in `cdd-sow-research`; other repos keep the subset that fits their risk, so each repo's
`COMPLIANCE.md` is the source of truth for which control maps to which principle (the numbers
differ between repos, so do not hard-code one here).

## When to use

- A repo is scaffolded and green but has no `Dockerfile` / `infra/` yet.
- The system handles regulated data and must prove in-country residency, CMEK, and a closed
  network perimeter.
- You are asked to add deployment, terraform, residency pinning, CMEK, or VPC-SC.

## Deploy artifacts (the common shape)

```
Dockerfile                         # builds the API/agent image; no secrets baked in
infra/terraform/
  providers.tf                     # provider + backend; region wired from a variable
  variables.tf                     # region with a residency ALLOWLIST + validation
  terraform.tfvars.example         # in-country defaults (e.g. region = "asia-southeast1")
  apis.tf                          # enable ONLY the managed services this stack uses
  org_policy.tf                    # gcp.resourceLocations allowlist (+ repo-specific policy)
  kms.tf                           # one regional CMEK key + an IAM binding PER service
  vpc_sc.tf                        # service perimeter (dry-run first where supported)
  logging_worm.tf                  # locked/retention-bucket log sink: immutable audit
  monitoring.tf                    # log-based alerts on posture-violation signals
  iam.tf                           # least-privilege service accounts; no broad roles
  managed_readiness.tf             # serving-edge refusal while primary managed ops are stubs
  outputs.tf
```

Treat that as the common core, not a fixed manifest. Repos add what their domain needs
(`cdd-sow-research` adds `document_ai.tf`, `dlp.tf`, `model_armor.tf`, `agent_runtime.tf`;
`architecture-validator` adds `cloud_asset_inventory.tf` (its residency-scan module) and `cloudbuild.tf`), and a leaner
repo may omit `monitoring.tf`. A `make tf-plan` target runs `terraform plan` for the pinned
region so the posture is checked the same way locally and in CI.

## The controls (cite your repo's COMPLIANCE.md, not a fixed number)

Each control maps to a General Principle, but the **numbers vary per repo** (CMEK is P-09 in
`cdd-sow-research` and a different number in `architecture-validator`, for example), so map each control to
a principle in THAT repo's `COMPLIANCE.md` rather than hard-coding a number. The controls are
the constant; `cdd-sow-research` realizes the full set and leaner repos keep a subset.

1. **Residency pinned and validated.** The region is a variable constrained to an in-country
   allowlist; `variables.tf` rejects any other value at plan time, and the app validates the
   same allowlist at settings load so it fails fast off-region too. Use regional endpoints,
   never global.
2. **Location Org Policy.** `gcp.resourceLocations` pins where resources may be created. Each
   repo adds the constraints that fit its posture: `cdd-sow-research` also disables
   service-account key creation (use Workload Identity instead); `architecture-validator`
   denies external IPs and forces CMEK via `gcp.restrictNonCmekServices`.
3. **Managed-first, minimal surface.** `apis.tf` enables only the services the pinned stack
   actually uses. No public ingress; egress through the perimeter / Private Service Connect,
   not the open internet.
4. **CMEK does not cascade.** One regional customer-managed key, with an explicit IAM binding
   for each service agent that needs it (no project-wide grant). Encryption is bound end to
   end: storage, logs, and the model/runtime.
5. **VPC-SC perimeter, dry-run first where supported.** Stand up the service perimeter in
   dry-run, confirm no legitimate path is broken from the audit logs, then enforce
   (`cdd-sow-research` does this with an enforce toggle plus an explicit dry-run spec). Some
   repos enforce directly behind a single enable/disable toggle; never enforce blind on a path
   you have not first watched in dry-run.
6. **WORM audit logs.** A log sink to a bucket with retention/lock (or equivalent) so audit
   events are immutable. The application already redacts before it logs (see
   `deterministic-domain-service` and `audit-first-demo`); the infra guarantees they cannot be
   altered or deleted.
7. **Posture alerts (where present).** Log-based alerts fire on the signals that mean the
   posture slipped: guardrail/safety blocks, service-account key creation, VPC-SC denials, and
   CMEK key changes. `cdd-sow-research` ships these in `monitoring.tf`; a blocked attempt
   should page someone, not pass silently.
8. **Managed readiness is code-owned and fail-closed.** Before adding a serving edge, scan the
   managed adapters for primary methods that only import an SDK and raise. Name each operation
   in `managed_readiness.py`. The production container runs that module before Uvicorn, and the
   API's executable `main()` runs the same preflight. The assertion evaluates the selected
   binding map, so an explicit test or migration rebind may replace a placeholder while the
   default managed family still refuses. `managed_readiness.tf` also refuses the serving edge
   while the code-owned list is non-empty; a caller cannot override the fact with tfvars. Remove
   an entry only with a real implementation and a live integration test. Local remains available
   through its own complete adapters; incomplete managed work is not graceful degradation.

## Steps to add deployment to a scaffolded repo

1. Write the `Dockerfile` (build the API image; run as non-root; no secrets in layers). Set
   the profile to the cloud profile EXPLICITLY here (`ENV <PKG>_PROFILE=gcp`, or set it on
   the Cloud Run service in `infra/`). An unset profile variable is NOT a usable production
   posture: the app treats it as "nobody chose", which binds the offline adapters, refuses
   service-to-service callers and confines the service to loopback (see the three-state
   resolution in `ports-and-adapters-repo`). Production opts IN by naming the profile; never
   rely on a baked-in default to select cloud, and never expect an unnamed profile to serve.
   Remember that this `CMD` hands the app OBJECT to uvicorn and never calls `main()`, so any
   posture check written in `main()` does not run here.
2. Create `infra/terraform/` with the files above. Start from `variables.tf`: declare `region`
   with a `validation` block whose `condition` is membership in the residency allowlist.
3. Add `org_policy.tf` (resource-location allowlist + disable SA-key creation), then `kms.tf`
   (one regional key, per-service IAM bindings), then `vpc_sc.tf` (perimeter, `dry_run = true`).
4. Add `logging_worm.tf` (immutable audit sink) and `monitoring.tf` (the posture alerts).
5. Mirror the residency allowlist in the app: validate the configured region against the same
   list at `Settings` load, failing fast. The allowlist is the single source of truth shared
   by code and infra.
6. Audit every public managed-adapter operation. If any primary path is construction-only, add
   the startup and Terraform managed-readiness refusals described above and a unit test proving
   `local` stays available while `gcp` refuses.
7. Add a `make tf-plan` target; run it and confirm the plan is clean for the in-country region
   and rejects an out-of-region value.
8. Record each control in `COMPLIANCE.md` (the residency, encryption, audit, and perimeter
   rows, by whatever numbers that repo uses) with the `infra/terraform` file as evidence, and
   the exit story in `docs/onprem-migration.md`. See the required doc/artifact set in
   `skills/README.md`.

## The residency-scanner variant

A dedicated repo can turn this posture into a product: a deterministic service that scans
Terraform plans / Cloud Asset Inventory for resources created outside the residency allowlist
and reports violations as severity-ranked findings (build the engine with
`deterministic-domain-service`, the report with `audit-first-demo`). The same allowlist drives
the scanner, the Org Policy, and the app's load-time check.

## Checklist

- [ ] `Dockerfile` + full `infra/terraform/` present; no secrets baked in.
- [ ] Region is allowlist-validated at `terraform plan` AND at app settings load (same list).
- [ ] Org Policy pins resource locations (plus the repo-specific constraints it needs).
- [ ] One regional CMEK key, IAM-bound per service (no project-wide grant).
- [ ] VPC-SC perimeter enforced only after a clean dry-run (where the provider supports it).
- [ ] WORM/immutable audit log sink; the app redacts before logging.
- [ ] Log-based alerts on the posture signals (key creation, VPC-SC denials, CMEK changes)
      where the repo ships monitoring.
- [ ] Construction-only managed operations block API startup and Terraform serving authorization;
      the block cannot be lifted by a caller variable.
- [ ] `make tf-plan` clean in-region, rejects out-of-region; controls recorded in COMPLIANCE.md.

**Docs style:** no em-dashes in `.md` or `.html` files, commit messages, or PR bodies. See
`skills/README.md`.
