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
# Only the GA google provider is required. Nothing in the baseline needs google-beta; a
# vertical that adds a beta-only resource adds the second provider in the same commit.
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
  }
}

provider "google" {
  project = var.project_id
  region  = local.region # the selected, allowlisted region: pinned, never global
}
