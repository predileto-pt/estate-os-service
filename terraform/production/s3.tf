module "documents_bucket" {
  source = "../modules/s3"

  bucket_name                  = "${var.prefix_name}-property-documents"
  enable_encryption_and_policy = true
}

# Staging bucket for Lambda deploy artifacts (deps layer zip + app zip).
# Direct uploads to `publish-layer-version` / `update-function-code` cap
# at ~50 MB; the S3-mediated path (`--content S3Bucket=...,S3Key=...`)
# lifts the ceiling to 250 MB unzipped. Lifecycle expires artifacts
# after 7 days - CI only needs the latest published version.
module "lambda_deploy_bucket" {
  source = "../modules/s3"

  bucket_name                  = "${var.prefix_name}-lambda-deploy"
  enable_encryption_and_policy = true
  enable_lifecycle_rules       = true
  lifecycle_rules = [
    {
      id                                     = "expire-deploy-artifacts"
      enabled                                = true
      prefix                                 = ""
      expiration_days                        = 7
      abort_incomplete_multipart_upload_days = 1
    }
  ]
}
