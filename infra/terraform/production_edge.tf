# production_edge.tf: the Cloud Run serving edge, fronted by an external load balancer,
# Cloud Armor and Identity-Aware Proxy.
#
# The whole edge is gated on var.production_edge_enabled, so a residency and audit stack can be
# applied on its own before anything serves traffic.
#
# The Cloud Run service accepts traffic ONLY from internal sources and the external Application
# Load Balancer (INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER); the run.app URL is not a way in.
#
# IAP is the shipped posture because the only identity adapter a rendered repo declares
# VERIFIED is the IAP one (adapters/gcp/identity.py), which checks the assertion's signature
# against IAP's own key set, its audience against the configured <PREFIX>_IAP_AUDIENCE, its
# expiry and its issuer before reading a single claim. With IAP off, the exposure guard has
# still stood down under the gcp profile, so every end-user route simply answers 401 and nobody
# can be authenticated at all.
#
# What is NOT here: a UI service. A rendered repo builds one image (the API), and the ui/
# micro-frontend ships no Dockerfile, so a UI backend would point at an image nothing produces.
# Add the second Cloud Run service, its backend service and a url_map path_matcher in the same
# commit that builds a UI image, not before.
#
# NOTE for template maintainers: copied into a render VERBATIM. No Jinja here. The environment
# variable NAMES that carry the render-time prefix are built from local.render_env_prefix
# (render.tf.json), which is the same cookiecutter variable config.py reads them under.

resource "terraform_data" "edge_contract" {
  input = {
    edge_enabled  = var.production_edge_enabled
    iap_enabled   = var.edge_iap_enabled
    audience_set  = var.iap_audience != ""
    custom_client = var.iap_oauth2_client_id != ""
  }

  lifecycle {
    precondition {
      condition     = (var.iap_oauth2_client_id == "") == (var.iap_oauth2_client_secret == "")
      error_message = "Supply iap_oauth2_client_id and iap_oauth2_client_secret together, or neither (which uses the Google-managed OAuth client)."
    }

    precondition {
      condition     = var.edge_iap_enabled || var.iap_audience == ""
      error_message = "iap_audience names an IAP-protected backend service, so it cannot be set while edge_iap_enabled is false: nothing would be minting the assertions the app verifies against it."
    }
  }
}

# --------------------------------------------------------------------------- #
# Secrets. No secret VALUE is ever in this configuration: the inbound service
# credential and the outbound Hrz7 credentials are existing Secret Manager
# versions, referenced by id and pinned to an exact numeric version.
# --------------------------------------------------------------------------- #
resource "google_secret_manager_secret_iam_member" "api_env" {
  for_each = var.production_edge_enabled ? var.additional_secret_env : {}

  project   = var.project_id
  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"
}

resource "google_cloud_run_v2_service" "api" {
  count    = var.production_edge_enabled ? 1 : 0
  project  = var.project_id
  name     = local.api_service_name
  location = local.region
  ingress  = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  deletion_protection = true

  template {
    service_account = google_service_account.app.email

    # CMEK on the revision's own storage (P-09): it does not cascade from anywhere else.
    encryption_key = google_kms_crypto_key.cmek.id

    scaling {
      min_instance_count = var.edge_min_instances
      max_instance_count = var.edge_max_instances
    }

    containers {
      image = var.api_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }

      # The profile is named EXPLICITLY here as well as in the image. An unset profile is not a
      # usable production posture: the app treats it as nobody having chosen, binds the
      # offline adapters, refuses every service-to-service caller and confines itself to
      # loopback. Production opts IN by naming it.
      env {
        name  = "${local.render_env_prefix}_PROFILE"
        value = "gcp"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GCP_REGION"
        value = local.region
      }
      # Rule R8: the console an escalation is routed to. Required whenever the edge is enabled
      # (variables.tf), because the managed router refuses rather than swallowing one.
      env {
        name  = "HUMAN_REVIEW_URL"
        value = var.human_review_url
      }

      # The three variables below are set only when they carry a value. This service reads its
      # environment in THREE states, and a variable set to empty is an expressed intent that
      # names nothing: an emptied quality URL means no promotion authority and refuses, and an
      # emptied audience refuses every caller. Writing "" here would therefore be a different,
      # louder posture than leaving the variable off the service.
      dynamic "env" {
        for_each = var.iap_audience == "" ? [] : [var.iap_audience]
        content {
          name  = "${local.render_env_prefix}_IAP_AUDIENCE"
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.quality_service_url == "" ? [] : [var.quality_service_url]
        content {
          name  = "${local.render_env_prefix}_QUALITY_URL"
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.otlp_endpoint == "" ? [] : [var.otlp_endpoint]
        content {
          name  = "OTEL_EXPORTER_OTLP_ENDPOINT"
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.additional_secret_env
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value.secret_id
              version = env.value.version
            }
          }
        }
      }

      # /healthz stays reachable without an end-user identity by design: a fronted deployment
      # has to remain health-checkable, and the endpoint carries no per-caller data.
      startup_probe {
        failure_threshold     = 12
        initial_delay_seconds = 5
        period_seconds        = 5
        timeout_seconds       = 3
        http_get {
          path = "/healthz"
          port = 8080
        }
      }

      liveness_probe {
        period_seconds  = 30
        timeout_seconds = 5
        http_get {
          path = "/healthz"
          port = 8080
        }
      }
    }
  }

  depends_on = [google_secret_manager_secret_iam_member.api_env]
}

# A serverless network endpoint group presents no application identity to Cloud Run, so the
# service has to accept unauthenticated invocations for the load balancer to reach it at all.
# That is not an open door: ingress already rejects everything except the load balancer and
# internal sources, and IAP below is what decides who gets through the load balancer.
resource "google_cloud_run_v2_service_iam_member" "api_load_balancer" {
  count    = var.production_edge_enabled ? 1 : 0
  project  = var.project_id
  location = local.region
  name     = google_cloud_run_v2_service.api[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_compute_region_network_endpoint_group" "api" {
  count                 = var.production_edge_enabled ? 1 : 0
  project               = var.project_id
  name                  = "${var.name_prefix}-api-neg"
  region                = local.region
  network_endpoint_type = "SERVERLESS"

  cloud_run {
    service = google_cloud_run_v2_service.api[0].name
  }
}

resource "google_compute_security_policy" "api_per_source" {
  count   = var.production_edge_enabled ? 1 : 0
  project = var.project_id
  name    = "${var.name_prefix}-api-rate-limit"

  rule {
    action   = "throttle"
    priority = 1000

    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }

    rate_limit_options {
      conform_action = "allow"
      exceed_action  = "deny(429)"
      enforce_on_key = "IP"

      rate_limit_threshold {
        count        = var.edge_per_source_rate_limit_per_minute
        interval_sec = 60
      }
    }

    description = "Per-source abuse boundary. One request costs a model call and an audit write, so the ceiling belongs at the edge rather than in the request path."
  }

  rule {
    action   = "allow"
    priority = 2147483647

    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }

    description = "Default allow after the per-source throttle."
  }
}

resource "google_compute_backend_service" "api" {
  count                 = var.production_edge_enabled ? 1 : 0
  project               = var.project_id
  name                  = local.api_service_name
  protocol              = "HTTPS"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  security_policy       = google_compute_security_policy.api_per_source[0].id

  backend {
    group = google_compute_region_network_endpoint_group.api[0].id
  }

  # Full-rate request logging: this is the record that shows an IAP denial or a Cloud Armor
  # throttle, which the edge_denials alert (monitoring.tf) counts.
  log_config {
    enable      = true
    sample_rate = 1
  }

  # The identity edge. `oauth2_client_id` and `oauth2_client_secret` are omitted when the
  # variables are empty, which selects the Google-managed OAuth client.
  dynamic "iap" {
    for_each = var.edge_iap_enabled ? [1] : []
    content {
      enabled              = true
      oauth2_client_id     = var.iap_oauth2_client_id != "" ? var.iap_oauth2_client_id : null
      oauth2_client_secret = var.iap_oauth2_client_secret != "" ? var.iap_oauth2_client_secret : null
    }
  }
}

# Who IAP admits. An empty list grants nobody, which denies everyone rather than admitting
# anyone; grant the reviewer group here, or at project scope if IAP membership is managed
# outside this stack.
resource "google_iap_web_backend_service_iam_member" "reviewers" {
  for_each = var.production_edge_enabled && var.edge_iap_enabled ? toset(var.iap_members) : toset([])

  project             = var.project_id
  web_backend_service = google_compute_backend_service.api[0].name
  role                = "roles/iap.httpsResourceAccessor"
  member              = each.value
}

resource "google_compute_url_map" "edge" {
  count           = var.production_edge_enabled ? 1 : 0
  project         = var.project_id
  name            = "${var.name_prefix}-edge"
  default_service = google_compute_backend_service.api[0].id

  host_rule {
    hosts        = [var.service_domain]
    path_matcher = "api"
  }

  path_matcher {
    name            = "api"
    default_service = google_compute_backend_service.api[0].id
  }
}

resource "google_compute_managed_ssl_certificate" "edge" {
  count   = var.production_edge_enabled ? 1 : 0
  project = var.project_id
  name    = "${var.name_prefix}-edge"

  managed {
    domains = [var.service_domain]
  }
}

resource "google_compute_target_https_proxy" "edge" {
  count            = var.production_edge_enabled ? 1 : 0
  project          = var.project_id
  name             = "${var.name_prefix}-edge"
  url_map          = google_compute_url_map.edge[0].id
  ssl_certificates = [google_compute_managed_ssl_certificate.edge[0].id]
}

resource "google_compute_global_address" "edge" {
  count   = var.production_edge_enabled ? 1 : 0
  project = var.project_id
  name    = "${var.name_prefix}-edge"
}

# Port 443 only. There is no port-80 forwarding rule and therefore no plaintext listener to
# redirect from; the managed certificate and HSTS from the application do the rest.
resource "google_compute_global_forwarding_rule" "edge" {
  count                 = var.production_edge_enabled ? 1 : 0
  project               = var.project_id
  name                  = "${var.name_prefix}-edge-https"
  target                = google_compute_target_https_proxy.edge[0].id
  port_range            = "443"
  ip_address            = google_compute_global_address.edge[0].id
  load_balancing_scheme = "EXTERNAL_MANAGED"
}

resource "google_dns_record_set" "edge" {
  count        = var.production_edge_enabled && var.dns_managed_zone != "" ? 1 : 0
  project      = var.project_id
  managed_zone = var.dns_managed_zone
  name         = "${var.service_domain}."
  type         = "A"
  ttl          = 300
  rrdatas      = [google_compute_global_address.edge[0].address]
}
