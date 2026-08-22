# monitoring.tf: log-based metrics and alert policies for the posture signals.
#
# Principle map (COMPLIANCE.md):
#   P-07 / P-09 (detect, do not merely record): DATA_READ logging (logging_worm.tf) records
#         reads, but recording is not detection. These metrics and policies SURFACE the events
#         that mean the posture slipped, rather than leaving the signal unread in the WORM
#         bucket for the length of the retention window.
#
# Every filter below names a field this deployment actually emits:
#   - critical_escalations : the managed audit adapter writes AuditEvent as a struct payload,
#     so jsonPayload.decision is "escalated" or "allowed" (domain/kernel.py Decision) and
#     jsonPayload.severity carries the band. A critical escalation is a maker-checker event a
#     reviewer has to see; the deterministic core decided it, so it is never noise.
#   - sa_key_creation : an exportable service-account key was created. Org policy should have
#     refused it (org_policy.tf), so this firing means the policy is off or was overridden.
#   - vpc_sc_denials : a VPC Service Controls violation. In dry run this is the evidence used
#     to decide whether enforcing would break a legitimate path.
#   - cmek_changes : a CMEK key destroy or update. Key material changing is a P-09 event.
#   - edge_denials : Cloud Armor denied or throttled a request at the edge.
#
# There is deliberately no guardrail-block metric. A rendered repo binds no guardrail port yet
# (COMPLIANCE rule R1 records that as owed), and a metric whose filter can never match is a
# green light nobody earned. Add it in the same commit that binds the guardrail.
#
# Alert policies are always created; var.alert_notification_channels attaches the channels.
#
# NOTE for template maintainers: copied into a render VERBATIM. No Jinja here.

locals {
  security_metrics = {
    critical_escalations = {
      description = "Critical-severity escalation recorded in the app audit log (maker-checker, P-06)"
      filter      = "logName=\"projects/${var.project_id}/logs/${local.audit_log_name}\" AND jsonPayload.decision=\"escalated\" AND jsonPayload.severity=\"critical\""
    }
    sa_key_creation = {
      description = "Service-account key created (org policy should forbid this)"
      filter      = "protoPayload.methodName=\"google.iam.admin.v1.CreateServiceAccountKey\""
    }
    vpc_sc_denials = {
      description = "VPC Service Controls violation"
      filter      = "protoPayload.metadata.@type=\"type.googleapis.com/google.cloud.audit.VpcServiceControlAuditMetadata\""
    }
    cmek_changes = {
      description = "CMEK key destroy or update operation"
      filter      = "protoPayload.serviceName=\"cloudkms.googleapis.com\" AND (protoPayload.methodName:\"DestroyCryptoKeyVersion\" OR protoPayload.methodName:\"UpdateCryptoKey\")"
    }
    edge_denials = {
      description = "Cloud Armor denied or throttled a request at the serving edge"
      filter      = "resource.type=\"http_load_balancer\" AND jsonPayload.enforcedSecurityPolicy.outcome=\"DENY\""
    }
  }
}

resource "google_logging_metric" "security" {
  for_each = local.security_metrics

  project     = var.project_id
  name        = "${local.metric_prefix}_${each.key}"
  description = each.value.description
  filter      = each.value.filter

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }

  depends_on = [google_project_service.required]
}

resource "google_monitoring_alert_policy" "security" {
  for_each = local.security_metrics

  project      = var.project_id
  display_name = "${var.name_prefix} security: ${each.key}"
  combiner     = "OR"

  conditions {
    display_name = each.value.description

    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.security[each.key].name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_DELTA"
        cross_series_reducer = "REDUCE_SUM"
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = var.alert_notification_channels

  documentation {
    content   = "Security signal '${each.key}' fired for ${local.render_catalog_id}. Investigate the matching entries in Cloud Logging and in the WORM audit bucket (${local.worm_bucket_id})."
    mime_type = "text/markdown"
  }

  depends_on = [google_project_service.required]
}
