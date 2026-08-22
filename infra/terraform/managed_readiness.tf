# Generated repos may plan the production edge only after every primary managed adapter is real.
# This is a code-owned fact, not a caller override: change it to true in the same reviewed commit
# that empties INCOMPLETE_MANAGED_OPERATIONS and adds live integration evidence.
locals {
  managed_profile_implemented = false
}

check "managed_profile_is_implemented_before_serving" {
  assert {
    condition     = !var.production_edge_enabled || local.managed_profile_implemented
    error_message = "production_edge_enabled requires real, integration-tested managed adapters. This repository still has construction-only gcp operations; see managed_readiness.py."
  }
}
