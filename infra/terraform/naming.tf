# naming.tf: every resource name derived from var.name_prefix, in one place, plus the
# effective region pair derived from render.tf.json.
#
# A non-default prefix lets a second instance coexist in the same project, and lets a destroy
# plus redeploy sidestep the indestructible KMS key ring a previous stack left behind.
#
# Length note: GCP service-account ids must be 6 to 30 characters. The longest derived id is
# <prefix>-app, so any prefix the variable's own regex accepts is safe here. The prefix is a
# LITERAL default rather than a value derived from a render variable, deliberately: the render
# variables have proven length envelopes (a 1 character env_prefix and a 48 character
# package_name are both valid renders) and nothing in a rendered repo may depend on the length
# of a rendered value.
#
# One name IS derived from a render variable: the audit log name. The managed audit adapter
# writes to the logger "<package_name>-audit" as a rendered code constant (adapters/gcp/
# audit.py), and the WORM sink filter (logging_worm.tf) must name the same log or it routes an
# empty stream that looks exactly like a working sink. Three sibling repos each had to pin
# that literal by hand; here BOTH sides render from the same cookiecutter variable
# (render.tf.json carries it as local.render_package_name), so they agree by construction,
# and production_edge.tftest.hcl asserts the derivation so it cannot quietly change.
#
# NOTE for template maintainers: copied into a render VERBATIM. No Jinja here.

locals {
  # The effective residency pair. variables.tf keeps region and allowed_regions nullable so
  # this file, not a rendered default, is where the render-time region takes effect; an
  # operator overrides either in terraform.tfvars, and the single cross-variable validation on
  # var.region holds the pair consistent (it lives there alone, because two validations reading
  # each other's variable is a dependency cycle Terraform refuses to build).
  region          = coalesce(var.region, local.render_region)
  allowed_regions = var.allowed_regions == null ? [local.render_region] : var.allowed_regions

  prefix_u = replace(var.name_prefix, "-", "_")

  # KMS (kms.tf). Key rings are indestructible: a new prefix means a new ring.
  kms_ring_name = "${var.name_prefix}-ring"
  kms_key_name  = "${var.name_prefix}-cmek"

  # WORM audit trail (logging_worm.tf, monitoring.tf).
  worm_bucket_id  = "${var.name_prefix}-worm"
  audit_sink_name = "${var.name_prefix}-audit-to-worm"

  # Fixed by the application, derived from the SAME render variable the application's logger
  # name renders from. See the header note above.
  audit_log_name = "${local.render_package_name}-audit"

  # Service account (iam.tf).
  app_sa_id = "${var.name_prefix}-app"

  # VPC-SC (vpc_sc.tf): perimeter and access-level names allow letters, digits, underscores.
  perimeter_name    = "${local.prefix_u}_perimeter"
  access_level_name = "${local.prefix_u}_operators"

  # Log-based metrics (monitoring.tf).
  metric_prefix = local.prefix_u

  # Serving edge (production_edge.tf).
  api_service_name = "${var.name_prefix}-api"

  # Environment variable names this stack sets on the Cloud Run service. Derived from the
  # render-time prefix so an operator-supplied secret can never silently shadow the residency,
  # identity or routing wiring (the additional_secret_env validation in variables.tf).
  reserved_env_names = [
    "${local.render_env_prefix}_PROFILE",
    "${local.render_env_prefix}_SETTINGS",
    "${local.render_env_prefix}_IAP_AUDIENCE",
    "${local.render_env_prefix}_QUALITY_URL",
    "GOOGLE_CLOUD_PROJECT",
    "GCP_REGION",
    "HUMAN_REVIEW_URL",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "PORT",
  ]
}
