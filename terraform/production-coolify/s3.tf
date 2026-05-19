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
# Property images bucket — public-read, fronted by Cloudflare.
#
# Reads happen over https://images.predileto.pt, which is a Cloudflare-
# proxied CNAME pointing at the bucket's S3 hostname. Cloudflare terminates
# TLS for browsers and rewrites the `Host` header to the bucket's S3
# hostname so virtual-host routing works (Origin Rule in the Cloudflare
# dashboard). The bucket policy below grants `s3:GetObject` to `*` because
# the URLs are unguessable object keys and the content is inherently
# public (property listings).
#
# Writes happen from the api container via the `app_s3` IAM user
# (`iam.tf`) using presigned PUT URLs handed to the browser.
#
# Prior architecture: CloudFront + OAC + ACM (us-east-1). Removed 2026-05-19;
# the Bandwidth Alliance discontinuation made the CloudFront-egress savings
# negligible for our scale, and we wanted single-vendor TLS management.
###############################################################################

module "images_bucket" {
  source = "../modules/s3"

  bucket_name                  = "${var.prefix_name}-property-images"
  enable_encryption_and_policy = true

  # Browser-direct PUTs via presigned URLs require CORS. The api
  # generates a presigned PUT, the dashboard's <input type="file">
  # handler uploads straight to s3.<region>.amazonaws.com, and the
  # browser issues an OPTIONS preflight first. Without these rules
  # S3 returns 403 on the preflight and the upload never starts.
  enable_cors = true
  cors_rules = [
    {
      allowed_methods = ["GET", "PUT", "HEAD"]
      allowed_origins = [
        "https://predileto.pt",
        "https://imobiliarias.predileto.pt",
        "http://localhost:3000",
        "http://localhost:4000",
      ]
      # `*` covers Content-Type (signed in the presigned URL) plus any
      # x-amz-* headers the SDK might add. Tightening to an explicit
      # list buys nothing — the URL signature is the actual auth boundary.
      allowed_headers = ["*"]
      # FE doesn't need much back, but ETag is the standard signal that
      # the object landed; exposing it lets the dashboard confirm the
      # upload before calling the api's "image-recorded" endpoint.
      expose_headers  = ["ETag"]
      max_age_seconds = 3600
    },
  ]
}

# `block_public_policy = false` is the only relaxation — needed so the
# public-read bucket policy below can attach. The other three levers stay
# ON: ACLs blocked / ignored, plus restrict_public_buckets ON so a future
# misconfigured policy can't accidentally widen access via cross-account
# routes. The single legitimate public vector is the explicit bucket
# policy in `aws_s3_bucket_policy.images_public_read`.
resource "aws_s3_bucket_public_access_block" "images_bucket" {
  bucket = module.images_bucket.id

  block_public_acls       = true
  block_public_policy     = false
  ignore_public_acls      = true
  restrict_public_buckets = false
}

# Disable ACLs entirely. AWS-recommended for new buckets — all access
# control flows through bucket policy + IAM, never object ACLs.
resource "aws_s3_bucket_ownership_controls" "images_bucket" {
  bucket = module.images_bucket.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# Public read for the object set only. Listing (`s3:ListBucket`) is NOT
# granted — directory enumeration via the bucket root is still blocked,
# so the only way to read an object is to know its UUID-keyed path.
resource "aws_s3_bucket_policy" "images_public_read" {
  bucket = module.images_bucket.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowPublicReadOfObjects"
        Effect    = "Allow"
        Principal = "*"
        Action    = "s3:GetObject"
        Resource  = "${module.images_bucket.arn}/*"
      },
    ]
  })

  # The policy depends on the public-access-block being relaxed first.
  # Otherwise terraform may apply the policy before the block flips,
  # and S3 rejects the public statement.
  depends_on = [aws_s3_bucket_public_access_block.images_bucket]
}
