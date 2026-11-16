locals {
  runtime = var.runtime_enabled ? 1 : 0
  apis = toset([
    "compute.googleapis.com", "artifactregistry.googleapis.com", "cloudbuild.googleapis.com",
    "secretmanager.googleapis.com", "iam.googleapis.com", "logging.googleapis.com",
    "storage.googleapis.com", "identitytoolkit.googleapis.com", "serviceusage.googleapis.com", "run.googleapis.com"
  ])
  runtime_config = {
    CORTE_PUBLIC_URL          = "https://${var.hosting_site_id}.web.app"
    CORTE_AUTH_PROVIDER       = "firebase"
    CORTE_FIREBASE_WEB_CONFIG = jsonencode(merge(var.firebase_web_config, { storageBucket = var.storage_bucket_name }))
    CORTE_FIREBASE_PROJECT_ID = var.project_id
    CORTE_OWNER_EMAIL         = var.owner_email
    CORTE_OWNER_UID           = var.owner_uid
    CORTE_TRUST_PROXY         = "1"
    CORTE_PROXY_HOPS          = "1"
    CORTE_DATA_DIR            = "/var/lib/corte"
    GOOGLE_CLOUD_PROJECT      = var.project_id
    _secret_versions = {
      CORTE_SESSION_SECRET = "projects/${var.project_id}/secrets/${google_secret_manager_secret.session.secret_id}/versions/1"
      CORTE_ENCRYPTION_KEY = "projects/${var.project_id}/secrets/${google_secret_manager_secret.encryption.secret_id}/versions/1"
    }
  }
}

resource "google_project_service" "api" {
  for_each           = local.apis
  service            = each.value
  disable_on_destroy = false
}

resource "google_service_account" "runtime" {
  account_id   = "corte-runtime"
  display_name = "Corte runtime - Google ADC, no downloaded key"
  depends_on   = [google_project_service.api]
}

resource "google_service_account" "build" {
  account_id   = "corte-build"
  display_name = "Corte Cloud Build"
  depends_on   = [google_project_service.api]
}

resource "google_service_account" "gateway" {
  account_id   = "corte-gateway"
  display_name = "Corte stateless gateway - no Firebase or secret access"
  depends_on   = [google_project_service.api]
}

resource "google_project_iam_custom_role" "firebase_session" {
  role_id     = "corteFirebaseSession"
  title       = "Corte Firebase sessions"
  permissions = ["firebaseauth.users.get", "firebaseauth.users.createSession"]
  depends_on  = [google_project_service.api]
}

resource "google_project_iam_member" "firebase_session" {
  project = var.project_id
  role    = google_project_iam_custom_role.firebase_session.name
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "logging" {
  for_each = {
    runtime = google_service_account.runtime.email
    build   = google_service_account.build.email
  }
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${each.value}"
}

resource "google_artifact_registry_repository" "app" {
  location      = var.region
  repository_id = "corte"
  description   = "Reviewed immutable Corte application builds"
  format        = "DOCKER"
  depends_on    = [google_project_service.api]
}

resource "google_artifact_registry_repository_iam_member" "runtime_reader" {
  location   = var.region
  repository = google_artifact_registry_repository.app.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_artifact_registry_repository_iam_member" "build_writer" {
  location   = var.region
  repository = google_artifact_registry_repository.app.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.build.email}"
}

resource "google_storage_bucket" "build_source" {
  name                        = "corte-${var.project_id}-build-source"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  lifecycle_rule {
    condition { age = 3 }
    action { type = "Delete" }
  }
  depends_on = [google_project_service.api]
}

resource "google_storage_bucket_iam_member" "build_source_reader" {
  bucket = google_storage_bucket.build_source.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.build.email}"
}

resource "google_storage_bucket_iam_member" "firebase_objects" {
  for_each   = toset(["roles/storage.objectCreator", "roles/storage.objectViewer"])
  bucket     = var.storage_bucket_name
  role       = each.value
  member     = "serviceAccount:${google_service_account.runtime.email}"
  depends_on = [google_storage_bucket.corte_private]
}

resource "google_storage_bucket" "corte_private" {
  count                       = var.create_storage_bucket ? 1 : 0
  name                        = var.storage_bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = { application = "corte" }
  lifecycle { prevent_destroy = true }
  depends_on = [google_project_service.api]
}

data "google_storage_bucket" "corte_existing" {
  count = var.create_storage_bucket ? 0 : 1
  name  = var.storage_bucket_name
  lifecycle {
    postcondition {
      condition     = self.uniform_bucket_level_access && self.public_access_prevention == "enforced"
      error_message = "The selected existing Corte bucket must enforce uniform access and public access prevention."
    }
  }
}

resource "google_secret_manager_secret" "session" {
  secret_id = "corte-session-secret"
  replication {
    auto {}
  }
  lifecycle { prevent_destroy = true }
  depends_on = [google_project_service.api]
}

resource "google_secret_manager_secret" "encryption" {
  secret_id = "corte-encryption-key"
  replication {
    auto {}
  }
  lifecycle { prevent_destroy = true }
  depends_on = [google_project_service.api]
}

resource "google_secret_manager_secret_iam_member" "session_reader" {
  secret_id = google_secret_manager_secret.session.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "encryption_reader" {
  secret_id = google_secret_manager_secret.encryption.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_compute_network" "app" {
  count                   = local.runtime
  name                    = "corte-vpc"
  auto_create_subnetworks = false
  depends_on              = [google_project_service.api]
}

resource "google_compute_subnetwork" "app" {
  count                    = local.runtime
  name                     = "corte-private"
  ip_cidr_range            = "10.73.0.0/24"
  region                   = var.region
  network                  = google_compute_network.app[0].id
  private_ip_google_access = true
}

resource "google_compute_subnetwork" "gateway" {
  count                    = local.runtime
  name                     = "corte-gateway"
  ip_cidr_range            = "10.74.0.0/24"
  region                   = var.region
  network                  = google_compute_network.app[0].id
  private_ip_google_access = true
}

resource "google_compute_address" "backend" {
  count        = local.runtime
  name         = "corte-backend-private"
  address_type = "INTERNAL"
  address      = "10.73.0.10"
  subnetwork   = google_compute_subnetwork.app[0].id
  region       = var.region
}

resource "google_compute_firewall" "gateway" {
  count                   = local.runtime
  name                    = "corte-only-private-gateway"
  network                 = google_compute_network.app[0].name
  direction               = "INGRESS"
  source_ranges           = [google_compute_subnetwork.gateway[0].ip_cidr_range]
  target_service_accounts = [google_service_account.runtime.email]
  allow {
    protocol = "tcp"
    ports    = ["8080"]
  }
}

resource "google_compute_router" "app" {
  count   = local.runtime
  name    = "corte-egress"
  network = google_compute_network.app[0].id
  region  = var.region
}

resource "google_compute_router_nat" "app" {
  count                              = local.runtime
  name                               = "corte-egress"
  router                             = google_compute_router.app[0].name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"
  subnetwork {
    name                    = google_compute_subnetwork.app[0].id
    source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
  }
}

resource "google_compute_disk" "data" {
  count = local.runtime
  name  = "corte-data"
  type  = "pd-balanced"
  zone  = var.zone
  size  = var.data_disk_gb
  lifecycle { prevent_destroy = true }
}

resource "google_compute_resource_policy" "snapshots" {
  count  = local.runtime
  name   = "corte-daily-data-snapshot"
  region = var.region
  snapshot_schedule_policy {
    schedule {
      daily_schedule {
        days_in_cycle = 1
        start_time    = "03:00"
      }
    }
    retention_policy {
      max_retention_days    = 14
      on_source_disk_delete = "KEEP_AUTO_SNAPSHOTS"
    }
    snapshot_properties { storage_locations = [var.region] }
  }
}

resource "google_compute_disk_resource_policy_attachment" "snapshots" {
  count = local.runtime
  name  = google_compute_resource_policy.snapshots[0].name
  disk  = google_compute_disk.data[0].name
  zone  = var.zone
}

resource "google_compute_instance" "app" {
  count                     = local.runtime
  name                      = "corte"
  machine_type              = var.machine_type
  zone                      = var.zone
  deletion_protection       = true
  allow_stopping_for_update = true
  boot_disk {
    initialize_params {
      image = var.cos_image
      size  = 20
      type  = "pd-balanced"
    }
  }
  attached_disk {
    source      = google_compute_disk.data[0].id
    device_name = "corte-data"
    mode        = "READ_WRITE"
  }
  network_interface {
    subnetwork = google_compute_subnetwork.app[0].id
    network_ip = google_compute_address.backend[0].address
  }
  service_account {
    email  = google_service_account.runtime.email
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }
  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }
  scheduling {
    automatic_restart   = true
    on_host_maintenance = "MIGRATE"
    provisioning_model  = "STANDARD"
  }
  metadata = {
    enable-oslogin             = "TRUE"
    block-project-ssh-keys     = "TRUE"
    disable-legacy-endpoints   = "TRUE"
    corte-image                = var.container_image
    corte-config               = jsonencode(local.runtime_config)
    corte-initialize-data-disk = tostring(var.initialize_empty_data_disk)
    startup-script             = file("${path.module}/startup.sh")
    shutdown-script            = "#!/bin/bash\nsystemctl stop corte.service || true\nsync\n"
  }
  depends_on = [google_compute_router_nat.app, google_artifact_registry_repository_iam_member.runtime_reader,
    google_secret_manager_secret_iam_member.session_reader, google_secret_manager_secret_iam_member.encryption_reader,
  google_project_iam_member.firebase_session, google_storage_bucket_iam_member.firebase_objects]
}

resource "google_cloud_run_v2_service" "gateway" {
  count               = local.runtime
  name                = "corte-gateway"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = true
  template {
    service_account                  = google_service_account.gateway.email
    execution_environment            = "EXECUTION_ENVIRONMENT_GEN2"
    max_instance_request_concurrency = 8
    timeout                          = "55s"
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    containers {
      image   = var.container_image
      command = ["gunicorn"]
      args    = ["-c", "cloud/gateway_gunicorn.conf.py", "cloud.gateway:create_app()"]
      ports { container_port = 8080 }
      resources {
        limits            = { cpu = "1", memory = "512Mi" }
        cpu_idle          = true
        startup_cpu_boost = true
      }
      env {
        name  = "CORTE_UPSTREAM_URL"
        value = "http://${google_compute_address.backend[0].address}:8080"
      }
      env {
        name  = "CORTE_PUBLIC_URL"
        value = "https://${var.hosting_site_id}.web.app"
      }
      startup_probe {
        tcp_socket {
          port = 8080
        }
        period_seconds    = 10
        timeout_seconds   = 3
        failure_threshold = 20
      }
    }
    vpc_access {
      egress = "PRIVATE_RANGES_ONLY"
      network_interfaces {
        network    = google_compute_network.app[0].id
        subnetwork = google_compute_subnetwork.gateway[0].id
        tags       = ["corte-gateway"]
      }
    }
  }
  depends_on = [google_compute_instance.app, google_compute_firewall.gateway]
}

# Public invocation is intentional: Firebase Hosting forwards normal HTTPS
# requests. The private backend verifies the owner's Firebase session cookie.
resource "google_cloud_run_v2_service_iam_member" "hosting_gateway" {
  count    = local.runtime
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.gateway[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_logging_project_exclusion" "gateway_oauth" {
  project     = var.project_id
  name        = "corte-gateway-oauth-callbacks"
  description = "Exclude temporary OAuth query codes only for Corte gateway request logs."
  filter      = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"corte-gateway\" AND logName:\"run.googleapis.com%2Frequests\" AND httpRequest.requestUrl=~\"/oauth/\""
  depends_on  = [google_project_service.api]
}
