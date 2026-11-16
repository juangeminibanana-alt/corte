# Dedicated Corte state, private and versioned. Authentication uses operator ADC.
# Bootstrap this bucket once before migrating an existing local state.
terraform {
  backend "gcs" {
    bucket = "corte-e-book-21589-tfstate"
    prefix = "terraform/corte"
  }
}
