# org_policy.tf: project-level Org Policy guardrails (defence in depth).
#
# Principle map (COMPLIANCE.md):
#   P-03 (residency): constraints/gcp.resourceLocations restricts where resources may be
#         created to the selected region's location group. Combined with the per-resource
#         region pin and the VPC-SC perimeter, an out-of-jurisdiction resource becomes
#         impossible to create rather than merely avoided by convention. Documentation is not
#         enforcement; this file is the enforcement.
#   P-09 (defence in depth, least privilege): service-account key creation is disabled
#         (attached service accounts and Workload Identity instead of exportable keys), and
#         uniform bucket-level access is required so no legacy ACL can reopen a bucket.
#
# Applied at the PROJECT level (parent = projects/<id>), so this stack needs no org-admin
# rights beyond the target project. Requires orgpolicy.googleapis.com (apis.tf) and that the
# caller holds roles/orgpolicy.policyAdmin on the project.
#
# Gating: every policy here is created only when var.enable_org_policies = true (the default).
# Set it false for a project-scoped evaluation deploy by a caller without that role; the
# per-resource region pins still apply, but this layer is skipped, which is NOT compliant for
# production.
#
# NOTE for template maintainers: copied into a render VERBATIM. No Jinja here.

locals {
  # The selected region's location group, plus anything an adopter's own policy evaluation
  # requires for the location-less global edge objects. See var.additional_resource_locations.
  resource_location_values = concat(
    ["in:${local.region}-locations"],
    var.additional_resource_locations,
  )
}

# Residency: allow resource creation only in the selected region's location group.
resource "google_org_policy_policy" "resource_locations" {
  count = var.enable_org_policies ? 1 : 0

  name   = "projects/${var.project_id}/policies/gcp.resourceLocations"
  parent = "projects/${var.project_id}"

  spec {
    rules {
      values {
        # For a repo rendered at asia-southeast1 this is "in:asia-southeast1-locations": the
        # region plus its zones and sub-locations, and nothing else.
        allowed_values = local.resource_location_values
      }
    }
  }

  depends_on = [google_project_service.required]
}

# Key hygiene: forbid creating exportable service-account keys (P-09). The service account in
# iam.tf is attached to Cloud Run and never needs an exported key; an exported key is a
# credential that leaves the perimeter in a file.
resource "google_org_policy_policy" "disable_sa_keys" {
  count = var.enable_org_policies ? 1 : 0

  name   = "projects/${var.project_id}/policies/iam.disableServiceAccountKeyCreation"
  parent = "projects/${var.project_id}"

  spec {
    rules {
      enforce = "TRUE"
    }
  }

  depends_on = [google_project_service.required]
}

# Require uniform bucket-level access on every bucket (no legacy object ACLs). The baseline
# creates no bucket, but a vertical's first object input is exactly where a per-object ACL
# makes one public; the constraint is cheaper to hold from day one than to retrofit.
resource "google_org_policy_policy" "uniform_bucket_access" {
  count = var.enable_org_policies ? 1 : 0

  name   = "projects/${var.project_id}/policies/storage.uniformBucketLevelAccess"
  parent = "projects/${var.project_id}"

  spec {
    rules {
      enforce = "TRUE"
    }
  }

  depends_on = [google_project_service.required]
}

# Optional domain-restricted sharing: only principals from the listed customer or directory
# ids may be granted IAM. Created only when org policies are enabled AND the list is non-empty.
resource "google_org_policy_policy" "allowed_member_domains" {
  count = var.enable_org_policies && length(var.allowed_policy_member_domains) > 0 ? 1 : 0

  name   = "projects/${var.project_id}/policies/iam.allowedPolicyMemberDomains"
  parent = "projects/${var.project_id}"

  spec {
    rules {
      values {
        allowed_values = var.allowed_policy_member_domains
      }
    }
  }

  depends_on = [google_project_service.required]
}
