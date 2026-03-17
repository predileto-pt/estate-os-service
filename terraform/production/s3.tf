module "documents_bucket" {
  source = "../modules/s3"

  bucket_name                  = "${var.prefix_name}-property-documents"
  enable_encryption_and_policy = true
}
