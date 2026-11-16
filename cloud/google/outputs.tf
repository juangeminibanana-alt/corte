output "deployment" {
  description = "Non-secret values consumed by manage.py. Expected URL is NOT proof of a live deployment."
  value = {
    project_id              = var.project_id
    region                  = var.region
    zone                    = var.zone
    hosting_site_id         = var.hosting_site_id
    image_repository        = "${var.region}-docker.pkg.dev/${var.project_id}/corte/corte"
    build_service_account   = google_service_account.build.id
    build_source_bucket     = google_storage_bucket.build_source.name
    session_secret_id       = google_secret_manager_secret.session.secret_id
    encryption_secret_id    = google_secret_manager_secret.encryption.secret_id
    storage_bucket_name     = var.storage_bucket_name
    runtime_service_account = google_service_account.runtime.email
    runtime_enabled         = var.runtime_enabled
    instance_name           = var.runtime_enabled ? google_compute_instance.app[0].name : null
    backend_private_ip      = var.runtime_enabled ? google_compute_address.backend[0].address : null
    gateway_uri             = var.runtime_enabled ? google_cloud_run_v2_service.gateway[0].uri : null
    gateway_service         = "corte-gateway"
    expected_url            = "https://${var.hosting_site_id}.web.app"
  }
}
