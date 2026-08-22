# kms.tf: one regional Customer-Managed Encryption Key (CMEK), in country.
#
# Principle map (COMPLIANCE.md):
#   P-09 (defence in depth): CMEK DOES NOT CASCADE. A key on one resource does not protect
#         what that resource hands to another service, so every managed service that encrypts
#         with this key gets its OWN service-agent binding below, and each resource names the
#         key in its own file. There is no project-wide grant anywhere in this stack.
#   P-03 (residency): the key ring location is local.region, a REGIONAL key ring, never the
#         global or multi-region one. Regional CMEK is what pins the crypto material in
#         country alongside the data it protects.
#
# NOTE: key rings are indestructible. `terraform destroy` cannot remove the ring, so a
# redeploy into the same project must either import it or use a fresh var.name_prefix
# (naming.tf derives the ring and key names from it).
#
# NOTE for template maintainers: copied into a render VERBATIM. No Jinja here.

resource "google_kms_key_ring" "cmek" {
  name     = local.kms_ring_name
  location = local.region # regional, in-country key material (P-03)

  depends_on = [google_project_service.required]
}

resource "google_kms_crypto_key" "cmek" {
  name     = local.kms_key_name
  key_ring = google_kms_key_ring.cmek.id

  purpose         = "ENCRYPT_DECRYPT"
  rotation_period = "7776000s" # 90 days

  version_template {
    algorithm        = "GOOGLE_SYMMETRIC_ENCRYPTION"
    protection_level = "SOFTWARE"
  }

  lifecycle {
    # A destroyed key is unrecoverable and would strand every CMEK-encrypted audit entry and
    # every record a vertical later binds to it.
    prevent_destroy = true
  }
}

# --------------------------------------------------------------------------- #
# Per-service-agent key bindings. Each managed service encrypts under its OWN
# service agent, so every one of them needs its own binding here (P-09). The
# agent addresses are the documented, project-number-derived identities.
#
# A vertical that binds a store, a warehouse or a recogniser adds ITS service
# agent here in the same commit that adds the resource. A resource created with
# no binding falls back to Google-managed keys and looks identical in the
# console, which is why the four services this baseline touches are all listed
# rather than assumed.
# --------------------------------------------------------------------------- #
data "google_project" "this" {
  project_id = var.project_id
}

# Cloud Logging, for the locked WORM audit bucket (logging_worm.tf).
resource "google_kms_crypto_key_iam_member" "logging" {
  crypto_key_id = google_kms_crypto_key.cmek.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-logging.iam.gserviceaccount.com"
}

# Cloud Run, for the serving revision's own encrypted storage (production_edge.tf).
resource "google_kms_crypto_key_iam_member" "run" {
  crypto_key_id = google_kms_crypto_key.cmek.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:service-${data.google_project.this.number}@serverless-robot-prod.iam.gserviceaccount.com"
}

# Vertex AI, for whatever narration or classification surface this vertical binds. The binding
# is in the baseline so the key is already bound on the day the adapter arrives.
resource "google_kms_crypto_key_iam_member" "aiplatform" {
  crypto_key_id = google_kms_crypto_key.cmek.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-aiplatform.iam.gserviceaccount.com"
}

# Cloud Storage, for this vertical's first object input or export. Same reason as above: the
# bucket is per-repo, the key binding is not the interesting part of that commit, and a bucket
# created without it is silently encrypted under Google-managed keys.
resource "google_kms_crypto_key_iam_member" "storage" {
  crypto_key_id = google_kms_crypto_key.cmek.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:service-${data.google_project.this.number}@gs-project-accounts.iam.gserviceaccount.com"
}
