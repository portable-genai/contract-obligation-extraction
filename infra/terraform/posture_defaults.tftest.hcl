# posture_defaults.tftest.hcl: the reversible posture controls are OFF unless stated.
#
# Slice 7 of the 2026-09-23 posture rule (2026-10-01): a compliance control that is not
# irreversible defaults off in code, and terraform.tfvars.example carries the production
# form. This file pins that default with mock providers only, like the rest of the suite.

mock_provider "google" {}
mock_provider "google-beta" {}

# Required variables with no default, stated only so the plan runs.
variables {
  worm_locked = true
}

run "reversible_posture_controls_default_off" {
  command = plan

  variables {
    cmek_enabled = true
    project_id   = "fictional-agent-project"
  }

  assert {
    condition     = length(google_access_context_manager_service_perimeter.service) == 0
    error_message = "enable_vpc_sc defaults to false: no perimeter unless the deployment states it."
  }

  assert {
    condition     = length(google_org_policy_policy.resource_locations) == 0
    error_message = "enable_org_policies defaults to false: no org policy unless the deployment states it."
  }

  assert {
    condition     = length(google_org_policy_policy.disable_sa_keys) == 0
    error_message = "enable_org_policies defaults to false: no org policy unless the deployment states it."
  }

  assert {
    condition     = length(google_org_policy_policy.uniform_bucket_access) == 0
    error_message = "enable_org_policies defaults to false: no org policy unless the deployment states it."
  }

  assert {
    condition     = length(google_org_policy_policy.allowed_member_domains) == 0
    error_message = "enable_org_policies defaults to false: no org policy unless the deployment states it."
  }
}
