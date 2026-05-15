module "documents_bucket" {
  source = "../modules/s3"

  bucket_name                  = "${var.prefix_name}-property-documents"
  enable_encryption_and_policy = true
}

# `modules/s3` doesn't provision a public-access-block (only encryption,
# CORS, lifecycle, policy, notifications). Add one explicitly — defense in
# depth on top of the account-level default. The bucket has no attached
# bucket policy, so the only public-access vector would be a misconfigured
# object ACL; block all four levers to make that impossible.
resource "aws_s3_bucket_public_access_block" "documents_bucket" {
  bucket = module.documents_bucket.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# CORS rules are intentionally NOT enabled here. The api uses presigned
# URLs for GET operations (src/shared/adapters/s3_document_storage.py:46
# and :60). Presigned GETs don't require browser CORS — only presigned
# PUTs do, and the api doesn't currently issue those. If a future feature
# adds browser-direct PUT uploads, enable `enable_cors = true` on the
# module call and populate `cors_rules` with the production Vercel
# origins.

###############################################################################
# Property images bucket — private, fronted by CloudFront.
#
# Reads happen exclusively via the CloudFront distribution in `cloudfront.tf`
# using Origin Access Control (OAC); the bucket policy in that file locks
# `s3:GetObject` to the distribution's source ARN. Direct
# `<bucket>.s3.amazonaws.com` URLs return 403.
#
# Writes happen from the api container via the `app_s3` IAM user
# (`iam.tf`) using presigned PUT URLs handed to the browser.
###############################################################################

module "images_bucket" {
  source = "../modules/s3"

  bucket_name                  = "${var.prefix_name}-property-images"
  enable_encryption_and_policy = true
}

# Same defense-in-depth as documents_bucket — block all public-access
# vectors at the bucket level. The bucket policy in cloudfront.tf grants
# read access only to the specific CloudFront distribution via OAC.
resource "aws_s3_bucket_public_access_block" "images_bucket" {
  bucket = module.images_bucket.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Disable ACLs entirely. AWS-recommended for new buckets — all access
# control flows through bucket policy + IAM, never object ACLs.
resource "aws_s3_bucket_ownership_controls" "images_bucket" {
  bucket = module.images_bucket.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}
