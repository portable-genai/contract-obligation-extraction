# iam.tf: the least-privilege serving identity.
#
# Principle map (COMPLIANCE.md):
#   P-09 (defence in depth, least privilege): one serving identity that holds only the roles
#         the request pipeline needs (write audit entries, write traces, read its own secrets,
#         call the narration model). No shared kitchen-sink account and no primitive roles.
#   P-03 (residency): the identity is project-scoped and every service it reaches is regional.
#   P-06 / R8: routing an escalation to the human-review-console is an outbound HTTPS call carrying a
#         service credential from Secret Manager, not a GCP IAM role, so nothing is granted
#         for it here.
#
# There is deliberately ONE service account. A rendered repo's agent surface is a set of plain
# tool callables that run inside the same process as the API (nothing in agent/ needs a runtime
# to import), so a second identity would have nothing to attach to and would only widen what is
# provisioned. Add one in the same commit that deploys the agent somewhere else, never before.
#
# A vertical that binds a store, a warehouse or a bucket adds its role to local.app_roles in
# the same commit. Grant the narrowest role that works: datastore.user rather than
# datastore.owner, bigquery.dataEditor rather than bigquery.admin.
#
# NOTE for template maintainers: copied into a render VERBATIM. No Jinja here; the display name
# is built from local.render_repository (render.tf.json).

resource "google_service_account" "app" {
  account_id   = local.app_sa_id
  display_name = "${local.render_repository} serving identity (API)"
  project      = var.project_id

  depends_on = [google_project_service.required]
}

locals {
  # Every role below is traceable to a bound adapter or to the serving edge. aiplatform.user
  # covers a narration or classification model, which restates and classifies and never
  # produces a number or a verdict (the consequential decision is deterministic).
  app_roles = [
    "roles/logging.logWriter",            # audit.py (write only: it cannot read the WORM trail)
    "roles/cloudtrace.agent",             # tracer.py
    "roles/secretmanager.secretAccessor", # the inbound and outbound service credentials
    "roles/aiplatform.user",              # the narration surface a vertical binds
  ]
}

resource "google_project_iam_member" "app" {
  for_each = toset(local.app_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.app.email}"
}

# The app uses the CMEK for the envelope operations it performs directly.
resource "google_kms_crypto_key_iam_member" "app" {
  crypto_key_id = google_kms_crypto_key.cmek.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${google_service_account.app.email}"
}
