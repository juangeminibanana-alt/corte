variable "project_id" {
  description = "Existing Google/Firebase project with billing enabled."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Supply the real Google Cloud project ID."
  }
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "zone" {
  type    = string
  default = "us-central1-a"
  validation {
    condition     = startswith(var.zone, "${var.region}-")
    error_message = "The zone must belong to the selected region."
  }
}

variable "hosting_site_id" {
  description = "Existing NEW Corte Firebase Hosting site, never E-BOOK's default site."
  type        = string
  default     = "corte-e-book-21589"
  validation {
    condition     = can(regex("^corte-[a-z0-9-]{4,50}$", var.hosting_site_id))
    error_message = "Use the dedicated Corte Hosting site created in this project."
  }
}

variable "owner_email" {
  type = string
  validation {
    condition     = can(regex("^[^ @]+@[^ @]+\\.[^ @]+$", var.owner_email))
    error_message = "Supply the verified Google email allowed to open this private app."
  }
}

variable "owner_uid" {
  description = "Optional Firebase UID; when set, email AND UID must match."
  type        = string
  default     = ""
}

variable "storage_bucket_name" {
  description = "Dedicated private Corte bucket. Never select the shared project's default Firebase bucket."
  type        = string
  validation {
    condition     = can(regex("^corte-[a-z0-9][a-z0-9.-]{1,54}[a-z0-9]$", var.storage_bucket_name))
    error_message = "Use a separate globally unique bucket beginning corte-; the shared default bucket is prohibited."
  }
}

variable "create_storage_bucket" {
  description = "False when the dedicated Corte bucket already exists. True only after reviewing creation of a NEW isolated bucket."
  type        = bool
  default     = false
}

variable "firebase_web_config" {
  description = "Public web app config from the SAME Firebase project; no service-account key."
  type = object({
    apiKey        = string
    authDomain    = string
    projectId     = string
    storageBucket = string
    appId         = string
  })
  validation {
    condition     = var.firebase_web_config.projectId == var.project_id
    error_message = "Firebase and Compute Engine must use the same Google project."
  }
}

variable "runtime_enabled" {
  description = "Phase 1 false: APIs, identities, registry and empty secrets only. Phase 2 true: paid compute/network/storage."
  type        = bool
  default     = false
}

variable "container_image" {
  description = "Immutable Artifact Registry image URI including @sha256:digest, printed by manage.py build."
  type        = string
  default     = ""
  validation {
    condition = !var.runtime_enabled || can(regex(
    "^${var.region}-docker\\.pkg\\.dev/${var.project_id}/corte/corte@sha256:[0-9a-f]{64}$", var.container_image))
    error_message = "Enable runtime only after building a Corte image in this project's registry; use its immutable digest."
  }
}

variable "initialize_empty_data_disk" {
  description = "First startup ONLY: permit formatting the new blank Corte disk. Set false immediately after first successful boot."
  type        = bool
  default     = false
}

variable "machine_type" {
  description = "Single non-Spot VM. No horizontal scaling while SQLite is used."
  type        = string
  default     = "e2-medium"
}

variable "data_disk_gb" {
  type    = number
  default = 20
  validation {
    condition     = var.data_disk_gb >= 20 && floor(var.data_disk_gb) == var.data_disk_gb
    error_message = "Use at least 20 GB; shrinking a data disk is unsupported."
  }
}

variable "cos_image" {
  description = "Use a pinned COS image self-link after reviewing the first plan; family default selects current stable COS."
  type        = string
  default     = "projects/cos-cloud/global/images/family/cos-stable"
}
