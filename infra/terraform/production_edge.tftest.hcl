# production_edge.tftest.hcl: the posture claims, as executable tests.
#
# Every run below uses `mock_provider`, so the whole file runs with NO credentials, NO project
# and NO network beyond the provider download:
#
#   terraform init -backend=false && terraform test
#
# which is exactly what `make tf-check` and the `terraform` CI job run. Nothing here is ever
# applied anywhere; every run is plan-only and every value is obviously fictional.
#
# What these runs are for: a residency or fail-closed claim that only lives in a comment is a
# claim nobody checks. Each `expect_failures` run proves that a specific misconfiguration is
# refused at plan time rather than reaching an apply.
#
# NOTE for template maintainers: this file is copied into a render VERBATIM (cookiecutter.json
# `_copy_without_render`), so it holds no Jinja and no literal render value. It reads the
# render-time constants through the locals in render.tf.json instead, which is also what lets
# it assert the audit-log name is derived rather than pinned by hand.

mock_provider "google" {}

run "residency_defaults_are_in_country" {
  command = plan

  variables {
    project_id    = "fictional-agent-project"
    enable_vpc_sc = false
  }

  assert {
    condition     = local.region == local.render_region
    error_message = "With no override, the deploy region must be the region this repo was rendered for."
  }

  assert {
    condition     = length(local.allowed_regions) == 1 && contains(local.allowed_regions, local.render_region)
    error_message = "The default residency allowlist must be exactly the rendered region, and nothing else."
  }

  assert {
    condition     = google_kms_key_ring.cmek.location == local.region
    error_message = "CMEK key material must be regional and in the deployment region, never a multi-region ring."
  }

  assert {
    condition     = google_logging_project_bucket_config.worm_audit.location == local.region
    error_message = "The WORM audit bucket must be created in the deployment region."
  }

  assert {
    condition     = one(google_org_policy_policy.resource_locations[*].spec[0].rules[0].values[0].allowed_values) == tolist(["in:${local.render_region}-locations"])
    error_message = "The org-policy location allowlist must pin exactly the deployment region's location group."
  }

  assert {
    condition     = one(google_org_policy_policy.disable_sa_keys[*].spec[0].rules[0].enforce) == "TRUE"
    error_message = "Service-account key creation must stay forbidden: an exported key is a credential that leaves the perimeter in a file."
  }

  assert {
    condition     = var.worm_locked && var.retention_days == 180
    error_message = "The audit bucket must stay locked at the six-month retention floor by default."
  }

  assert {
    condition     = google_logging_project_bucket_config.worm_audit.locked
    error_message = "The WORM lock must be applied to the bucket, not merely defaulted in a variable."
  }

  # The two asserts below are the ones this template exists to make. The managed audit adapter
  # writes to the logger "<package_name>-audit" as a rendered code constant, and the sink must
  # name the same log or it routes an empty stream that looks exactly like a working sink.
  # Both sides come from the SAME cookiecutter variable, so they agree by construction; these
  # asserts are what stop somebody quietly re-pinning either half by hand.
  assert {
    condition     = local.audit_log_name == "${local.render_package_name}-audit"
    error_message = "The audit log name must stay DERIVED from the rendered package name, which is what the managed audit adapter's logger name is rendered from."
  }

  assert {
    condition     = strcontains(google_logging_project_sink.audit_to_worm.filter, "/logs/${local.audit_log_name}")
    error_message = "The WORM sink filter must name the log the application actually writes; a filter naming a log nobody writes routes an empty stream."
  }
}

run "perimeter_starts_in_dry_run" {
  command = plan

  variables {
    project_id       = "fictional-agent-project"
    access_policy_id = "123456789012"
  }

  assert {
    condition     = google_access_context_manager_service_perimeter.service[0].use_explicit_dry_run_spec
    error_message = "The perimeter must start in dry run: never enforce blind on a path nobody has watched."
  }

  assert {
    condition     = length(google_access_context_manager_service_perimeter.service[0].status[0].restricted_services) == 0
    error_message = "In dry run the enforced status must stay open; the restricted services belong in the dry-run spec."
  }

  assert {
    condition     = contains(google_access_context_manager_service_perimeter.service[0].spec[0].restricted_services, "logging.googleapis.com")
    error_message = "The dry-run spec must audit the logging API: the WORM audit trail is the evidence that must not be readable across the boundary."
  }
}

run "default_omits_the_serving_edge" {
  command = plan

  variables {
    project_id    = "fictional-agent-project"
    enable_vpc_sc = false
  }

  assert {
    condition     = length(google_cloud_run_v2_service.api) == 0 && length(google_compute_global_forwarding_rule.edge) == 0
    error_message = "The serving edge must be opt-in, so the residency and audit stack can be applied and reviewed before anything serves."
  }
}

run "serving_edge_contract" {
  command = plan

  # This repository still carries the code-owned managed-readiness block. The plan must
  # describe the hardened edge correctly AND refuse to authorize it for creation.
  expect_failures = [check.managed_profile_is_implemented_before_serving]

  # A mocked provider leaves every computed attribute unknown at plan time, and the CMEK key
  # id is one. Overriding it during the plan is what lets the run assert that the revision is
  # bound to THAT key rather than to nothing; the value here is a stand-in for a real key id
  # and is never applied anywhere.
  override_resource {
    target          = google_kms_crypto_key.cmek
    override_during = plan
    values = {
      id = "projects/fictional-agent-project/locations/example-region/keyRings/agent-ring/cryptoKeys/agent-cmek"
    }
  }

  variables {
    project_id                  = "fictional-agent-project"
    enable_vpc_sc               = false
    production_edge_enabled     = true
    api_image                   = "example-docker.pkg.dev/fictional-agent-project/agent/api@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    service_domain              = "agent.fictional-bank.example"
    human_review_url            = "https://review.fictional-bank.example"
    alert_notification_channels = ["projects/fictional-agent-project/notificationChannels/123"]
    iap_members                 = ["group:reviewers@example.com"]
    iap_audience                = "/projects/123456789012/global/backendServices/1234567890123456789"
  }

  assert {
    condition     = google_cloud_run_v2_service.api[0].ingress == "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
    error_message = "The API must reject direct public Cloud Run ingress; the load balancer is the only way in."
  }

  assert {
    condition     = google_cloud_run_v2_service.api[0].location == local.region
    error_message = "The serving revision must run in the deployment region."
  }

  assert {
    condition     = endswith(google_cloud_run_v2_service.api[0].template[0].containers[0].image, "@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    error_message = "The API image must remain the reviewed digest."
  }

  assert {
    condition     = google_cloud_run_v2_service.api[0].template[0].encryption_key == google_kms_crypto_key.cmek.id
    error_message = "The revision must be bound to the regional CMEK: encryption does not cascade."
  }

  assert {
    condition     = one([for item in google_cloud_run_v2_service.api[0].template[0].containers[0].env : item.value if item.name == "${local.render_env_prefix}_PROFILE"]) == "gcp"
    error_message = "The cloud profile must be named explicitly on the service: an unset profile is not a usable production posture."
  }

  assert {
    condition     = one([for item in google_cloud_run_v2_service.api[0].template[0].containers[0].env : item.value if item.name == "GCP_REGION"]) == local.region
    error_message = "The application region must equal the Terraform deployment region."
  }

  assert {
    condition     = one([for item in google_cloud_run_v2_service.api[0].template[0].containers[0].env : item.value if item.name == "HUMAN_REVIEW_URL"]) == var.human_review_url
    error_message = "Rule R8: the service must be told where an escalation is routed, or the managed router refuses."
  }

  assert {
    condition     = one([for item in google_cloud_run_v2_service.api[0].template[0].containers[0].env : item.value if item.name == "${local.render_env_prefix}_IAP_AUDIENCE"]) == var.iap_audience
    error_message = "The verified identity adapter must receive the exact audience it checks assertions against."
  }

  assert {
    condition     = length([for item in google_cloud_run_v2_service.api[0].template[0].containers[0].env : item.name if item.name == "${local.render_env_prefix}_QUALITY_URL"]) == 0
    error_message = "An unset quality URL must be ABSENT from the service, never set to empty: this service reads its environment in three states and an emptied value refuses."
  }

  assert {
    condition     = length(google_compute_backend_service.api[0].iap) == 1 && google_compute_backend_service.api[0].iap[0].enabled
    error_message = "The backend service must carry IAP: it is the only mechanism by which an end user can be authenticated here."
  }

  assert {
    condition     = length(google_iap_web_backend_service_iam_member.reviewers) == 1
    error_message = "The named reviewers must be granted IAP access, or the edge admits nobody."
  }

  assert {
    condition     = length(google_compute_security_policy.api_per_source) == 1
    error_message = "The edge must provision its per-source Cloud Armor abuse boundary."
  }

  assert {
    condition     = one([for rule in google_compute_security_policy.api_per_source[0].rule : rule.rate_limit_options[0].rate_limit_threshold[0].count if rule.action == "throttle"]) == 120
    error_message = "The per-source throttle must retain the reviewed requests-per-minute ceiling."
  }

  assert {
    condition     = google_compute_global_forwarding_rule.edge[0].port_range == "443"
    error_message = "The edge must listen on 443 only: there is no plaintext listener to redirect from."
  }
}

# The region below is deliberately fictional. A real region such as us-central1 would FALSE-PASS
# for a repo rendered at us-central1, and this file is copied verbatim into every render, so the
# refusal has to be provable at every rendered region.
run "reject_region_outside_the_residency_allowlist" {
  command = plan

  variables {
    project_id    = "fictional-agent-project"
    enable_vpc_sc = false
    region        = "nowhere-west1"
  }

  expect_failures = [var.region]
}

run "reject_retention_below_six_months" {
  command = plan

  variables {
    project_id     = "fictional-agent-project"
    enable_vpc_sc  = false
    retention_days = 179
  }

  expect_failures = [var.retention_days]
}

run "reject_reducing_existing_locked_retention" {
  command = plan

  variables {
    project_id                     = "fictional-agent-project"
    enable_vpc_sc                  = false
    retention_days                 = 180
    existing_locked_retention_days = 2557
  }

  expect_failures = [var.existing_locked_retention_days]
}

run "reject_perimeter_without_an_access_policy" {
  command = plan

  variables {
    project_id       = "fictional-agent-project"
    enable_vpc_sc    = true
    access_policy_id = ""
  }

  expect_failures = [var.access_policy_id]
}

run "reject_mutable_api_image" {
  command = plan

  variables {
    project_id                  = "fictional-agent-project"
    enable_vpc_sc               = false
    production_edge_enabled     = true
    api_image                   = "example-docker.pkg.dev/fictional-agent-project/agent/api:latest"
    service_domain              = "agent.fictional-bank.example"
    human_review_url            = "https://review.fictional-bank.example"
    alert_notification_channels = ["projects/fictional-agent-project/notificationChannels/123"]
  }

  expect_failures = [
    var.api_image,
    check.managed_profile_is_implemented_before_serving,
  ]
}

run "reject_edge_with_no_review_console" {
  command = plan

  variables {
    project_id                  = "fictional-agent-project"
    enable_vpc_sc               = false
    production_edge_enabled     = true
    api_image                   = "example-docker.pkg.dev/fictional-agent-project/agent/api@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    service_domain              = "agent.fictional-bank.example"
    human_review_url            = ""
    alert_notification_channels = ["projects/fictional-agent-project/notificationChannels/123"]
  }

  expect_failures = [
    var.human_review_url,
    check.managed_profile_is_implemented_before_serving,
  ]
}

run "reject_edge_with_no_alert_channel" {
  command = plan

  variables {
    project_id                  = "fictional-agent-project"
    enable_vpc_sc               = false
    production_edge_enabled     = true
    api_image                   = "example-docker.pkg.dev/fictional-agent-project/agent/api@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    service_domain              = "agent.fictional-bank.example"
    human_review_url            = "https://review.fictional-bank.example"
    alert_notification_channels = []
  }

  expect_failures = [
    var.alert_notification_channels,
    check.managed_profile_is_implemented_before_serving,
  ]
}

run "reject_audience_without_iap" {
  command = plan

  variables {
    project_id       = "fictional-agent-project"
    enable_vpc_sc    = false
    edge_iap_enabled = false
    iap_audience     = "/projects/123456789012/global/backendServices/1234567890123456789"
  }

  expect_failures = [terraform_data.edge_contract]
}

# GCP_REGION is a reserved name whatever this repo was rendered as, which is why it is the one
# used here: a verbatim-copied test file cannot spell the render-time <PREFIX>_ names, and
# naming.tf reserves both kinds.
run "reject_reserved_secret_override" {
  command = plan

  variables {
    project_id    = "fictional-agent-project"
    enable_vpc_sc = false
    additional_secret_env = {
      GCP_REGION = {
        secret_id = "wrong-region"
        version   = "1"
      }
    }
  }

  expect_failures = [var.additional_secret_env]
}

run "reject_moving_secret_version" {
  command = plan

  variables {
    project_id    = "fictional-agent-project"
    enable_vpc_sc = false
    additional_secret_env = {
      HUMAN_REVIEW_S2S_TOKEN = {
        secret_id = "hrz7-outbound-s2s"
        version   = "latest"
      }
    }
  }

  expect_failures = [var.additional_secret_env]
}
