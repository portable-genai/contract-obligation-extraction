# providers.tf: provider pinning and state for this catalog service.
#
# Principle map (COMPLIANCE.md):
#   P-03 (single region / residency): every provider call is pinned to the effective region
#         (local.region, naming.tf), which is SELECTED AT DEPLOY TIME and validated against a
#         residency allowlist (variables.tf). There is no global or multi-region default; the
#         default is the region this repo was rendered for (render.tf.json).
#   P-02 (no lock-in): Terraform is the only place infrastructure is described. The app talks
#         to ports, never to these resources.
#
# The GA google provider covers everything but one resource: google_model_armor_template
# (model_armor.tf, rule R1) is google-beta only on the pinned provider version. A vertical that
# adds another beta-only resource keeps using this same provider rather than adding a third.
#
# NOTE for template maintainers: this file is copied into a render VERBATIM (it is listed in
# cookiecutter.json `_copy_without_render`, as every *.tf and *.tftest.hcl here is), so keep
# Jinja out of it. Render-time values arrive through render.tf.json.

terraform {
  required_version = ">= 1.9.0"

  # Partial backend. `terraform init -backend-config=...` supplies the reviewed state bucket
  # and the per-installation prefix, so neither is committed here and the module stays
  # reusable across installations. Keeping the declaration active is what makes accidental
  # local state impossible in a real runner; `-backend=false` is for offline validation only.
  backend "gcs" {}

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 7.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = local.region # the selected, allowlisted region: pinned, never global
}

provider "google-beta" {
  project = var.project_id
  region  = local.region # the selected, allowlisted region: pinned, never global
}
