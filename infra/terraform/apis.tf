# apis.tf: enable exactly the managed services this baseline depends on.
#
# Principle map (COMPLIANCE.md):
#   P-01 (managed-first, minimal surface): every entry below is here because a port this repo
#         binds calls it, because a resource in this stack needs it, or because the CMEK
#         service-agent binding for it lives in kms.tf and a vertical must not have to
#         remember to add both halves. Nothing here is aspirational.
#   P-03 (residency): enabling these is the prerequisite for the regional, CMEK-protected
#         resources the sibling files create.
#
# This is the VERTICAL-NEUTRAL baseline. A vertical that binds a store, a warehouse, a bucket
# or a speech recogniser adds its API here in the SAME commit that adds the resource, its CMEK
# service-agent binding (kms.tf), its role (iam.tf) and its perimeter entry (vpc_sc.tf). Four
# places, one commit; a service enabled with no key binding encrypts under Google-managed keys
# and looks identical from the console.
#
# disable_on_destroy = false, so destroying this stack does not yank platform APIs out from
# under other workloads in a shared project.
#
# NOTE for template maintainers: this file is copied into a render VERBATIM (cookiecutter.json
# `_copy_without_render`), so keep Jinja out of it. Render-time values arrive through
# render.tf.json.

locals {
  required_services = [
    # Called by a bound adapter (adapters/gcp/).
    "logging.googleapis.com",       # audit.py: the WORM audit sink (rule R2)
    "cloudtrace.googleapis.com",    # tracer.py: spans, content off
    "iap.googleapis.com",           # identity.py: the one adapter that declares VERIFIED
    "secretmanager.googleapis.com", # the inbound and outbound service credentials

    # Needed by a resource this stack creates.
    "run.googleapis.com",        # the serving edge (production_edge.tf)
    "cloudkms.googleapis.com",   # the regional CMEK key ring (kms.tf)
    "monitoring.googleapis.com", # the log-based metrics and alert policies (monitoring.tf)

    # Enabled with their CMEK service-agent binding rather than after it. Vertex AI is what a
    # vertical's first narration or classification adapter calls, and Cloud Storage is what its
    # first object input or export uses; both bind the key in kms.tf. Enabling the API creates
    # nothing and costs nothing, and it is what keeps "CMEK does not cascade" from becoming a
    # step somebody forgets on the day they add the adapter.
    "aiplatform.googleapis.com",
    "storage.googleapis.com",

    # Supporting services the above require.
    "accesscontextmanager.googleapis.com", # the VPC-SC perimeter (P-03)
    "compute.googleapis.com",              # the external load balancer and Cloud Armor
    "iam.googleapis.com",                  # least-privilege service accounts
    "orgpolicy.googleapis.com",            # the residency and key-hygiene constraints (P-03)
  ]
}

resource "google_project_service" "required" {
  for_each = toset(local.required_services)

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}
