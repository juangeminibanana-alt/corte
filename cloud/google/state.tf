# Dedicated recovery state. Application/build/gateway identities receive no
# bucket permissions here; keep state separate from data and build-source TTLs.
resource "google_storage_bucket" "terraform_state" {
  name                        = "corte-${var.project_id}-tfstate"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels = {
    application = "corte"
    purpose     = "terraform-state"
  }
  versioning { enabled = true }
  lifecycle { prevent_destroy = true }
  depends_on = [google_project_service.api]
}
