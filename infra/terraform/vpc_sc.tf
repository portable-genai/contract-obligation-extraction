# vpc_sc.tf: the VPC Service Controls perimeter around the AI and control plane.
#
# Principle map (COMPLIANCE.md):
#   P-01 / P-03 (hybrid posture and residency): a service perimeter draws a logical boundary
#         around the sovereignty-critical APIs (Vertex AI, Logging, Monitoring, Trace, KMS,
#         Secret Manager, Storage, Cloud Run). The audit trail, the key material and the
#         service credentials cannot be read across that boundary into an out-of-jurisdiction
#         project, which is what stops regulated evidence leaving the country even when an
#         identity inside the project is compromised.
#   P-01 (least surface): only the services this stack uses are inside the perimeter. A
#         vertical adds its own API to local.perimeter_restricted_services in the same commit
#         that adds the resource: a data store outside the perimeter is a hole in it.
#
# Two toggles:
#   var.enable_vpc_sc  - create the perimeter at all. Requires var.access_policy_id (validated
#                        at plan time in variables.tf); set it false for a project-scoped quick
#                        deploy without one.
#   var.vpc_sc_enforce - enforce (true) or DRY-RUN / audit (false, the default). Apply with
#                        false first, watch the dry-run violations that the vpc_sc_denials
#                        alert surfaces, add the operator identities to an access level, then
#                        flip to true. Implemented with use_explicit_dry_run_spec: in dry run
#                        the restricted services live in `spec` (audited, not enforced) and
#                        `status` stays open.
#
# NOTE on egress: VPC-SC governs access to GOOGLE APIs across perimeters, not arbitrary
# internet egress. The outbound call that routes an escalation to the Hrz7 console (rule R8) is
# ordinary HTTPS to a non-Google host, so it is a VPC firewall and Cloud NAT concern, not a
# VPC-SC egress rule. Run the service with egress that reaches exactly that console and nothing
# else.
#
# NOTE for template maintainers: copied into a render VERBATIM. No Jinja here.

locals {
  perimeter_restricted_services = [
    "aiplatform.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "cloudtrace.googleapis.com",
    "cloudkms.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
    "run.googleapis.com",
  ]

  # An access level is created only when operators are supplied AND the perimeter is enabled.
  make_access_level = var.enable_vpc_sc && length(var.operator_members) > 0
  access_level_names = local.make_access_level ? [
    "accessPolicies/${var.access_policy_id}/accessLevels/${local.access_level_name}"
  ] : []
}

# Allow named operator and CI identities to reach the restricted APIs from outside.
resource "google_access_context_manager_access_level" "operators" {
  count = local.make_access_level ? 1 : 0

  parent = "accessPolicies/${var.access_policy_id}"
  name   = "accessPolicies/${var.access_policy_id}/accessLevels/${local.access_level_name}"
  title  = local.access_level_name

  basic {
    conditions {
      members = var.operator_members
    }
  }
}

resource "google_access_context_manager_service_perimeter" "service" {
  count = var.enable_vpc_sc ? 1 : 0

  parent = "accessPolicies/${var.access_policy_id}"
  name   = "accessPolicies/${var.access_policy_id}/servicePerimeters/${local.perimeter_name}"
  title  = local.perimeter_name

  perimeter_type = "PERIMETER_TYPE_REGULAR"

  # Dry run (audit) until var.vpc_sc_enforce flips to true.
  use_explicit_dry_run_spec = !var.vpc_sc_enforce

  # The enforced configuration. In dry run this stays open (nothing restricted); in enforce
  # mode it carries the restricted-service boundary.
  status {
    resources           = ["projects/${data.google_project.this.number}"]
    restricted_services = var.vpc_sc_enforce ? local.perimeter_restricted_services : []
    access_levels       = var.vpc_sc_enforce ? local.access_level_names : []

    dynamic "vpc_accessible_services" {
      for_each = var.vpc_sc_enforce ? [1] : []
      content {
        enable_restriction = true
        allowed_services   = local.perimeter_restricted_services
      }
    }
  }

  # The dry-run spec: audited, not enforced. Present only while not enforcing.
  dynamic "spec" {
    for_each = var.vpc_sc_enforce ? [] : [1]
    content {
      resources           = ["projects/${data.google_project.this.number}"]
      restricted_services = local.perimeter_restricted_services
      access_levels       = local.access_level_names

      vpc_accessible_services {
        enable_restriction = true
        allowed_services   = local.perimeter_restricted_services
      }
    }
  }

  depends_on = [google_project_service.required]
}
