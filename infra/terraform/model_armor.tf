# model_armor.tf: the Model Armor guardrail template the `gcp` guardrail adapter screens
# through (rule R1).
#
# Principle map (COMPLIANCE.md):
#   P-04 / R1 (guardrail screening): adapters/gcp/guardrail.py screens every generation call's
#         input and output through this template for prompt injection, jailbreak, sensitive-data
#         leakage and malicious URLs, in both directions.
#   P-05 (residency): the template is created in the region this repo runs in (local.region) and
#         called on the regional Model Armor host (config/settings.yaml model_armor.host), never
#         the global endpoint.
#
# template_id matches the default config/settings.yaml model_armor.template_id
# ("contract-obligation-extraction-guardrail"), so a zero-edit render names a template this
# file provisions, rather than an id nothing creates.
#
# The malicious-URI filter and multi-language detection are NOT served in every region: a region
# that refuses them fails the whole template with CAPABILITY_NOT_SUPPORTED rather than degrading,
# so both are gated on var.model_armor_full_capabilities (default true) and a deployment in such
# a region sets it false explicitly and discloses the narrowed guardrail instead of failing every
# apply. See docs/gcp-service-region-availability.md upstream for which regions serve which.
#
# verify: https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/model_armor_template

resource "google_model_armor_template" "guardrail" {
  provider    = google-beta
  project     = var.project_id
  location    = local.region
  template_id = "${local.render_repository}-guardrail" # matches settings.yaml model_armor.template_id

  filter_config {
    pi_and_jailbreak_filter_settings {
      filter_enforcement = "ENABLED"
      confidence_level   = "LOW_AND_ABOVE"
    }
    # Regional capability. A region that does not serve it refuses the WHOLE template with
    # CAPABILITY_NOT_SUPPORTED, so a deployment there declines it EXPLICITLY via the variable
    # and discloses the narrowed guardrail. The default keeps it on, so a region that does serve
    # it gets it without having to ask.
    dynamic "malicious_uri_filter_settings" {
      for_each = var.model_armor_full_capabilities ? [1] : []
      content {
        filter_enforcement = "ENABLED"
      }
    }
    rai_settings {
      rai_filters {
        filter_type      = "DANGEROUS"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
      rai_filters {
        filter_type      = "HARASSMENT"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
      rai_filters {
        filter_type      = "HATE_SPEECH"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
      rai_filters {
        filter_type      = "SEXUALLY_EXPLICIT"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
    }
  }

  # Required by the API even though every field inside it is optional: creating the template
  # without this block succeeds, and the NEXT apply then fails with "The 'template_metadata'
  # field is required" while trying to remove what the service itself populated. Neither
  # `terraform validate` nor the offline suite resolves the API's own field requirements, so this
  # is only ever found by applying twice; shipping it from the first apply avoids that entirely.
  template_metadata {
    # Multi-language detection is a regional capability, refused the same way the malicious-URI
    # filter is, so it follows the same variable and the same disclosure.
    dynamic "multi_language_detection" {
      for_each = var.model_armor_full_capabilities ? [1] : []
      content {
        enable_multi_language_detection = true
      }
    }

    # OFF, and this is the decision rather than the default. Sanitize-operation logs carry the
    # prompt/response text that was screened; the WORM audit trail (logging_worm.tf) already
    # records what the domain narrated, under this stack's own retention, so a second copy of
    # the same content in ordinary operation logs would sit outside that retention for no reader.
    log_sanitize_operations = false

    # Stated false, which is also the API default, so nothing here asks the service to treat a
    # screen where some filters were skipped or failed as complete. The application does not
    # rely on this flag either way: adapters/gcp/guardrail.py allows only when
    # invocation_result is SUCCESS, so a PARTIAL or FAILURE screen (a filter past its token
    # limit, an unsupported language with multi-language detection off, a detector error) is
    # refused even when it reports no match.
    ignore_partial_invocation_failures = false
  }

  depends_on = [google_project_service.required]
}
