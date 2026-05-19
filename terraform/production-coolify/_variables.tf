variable "aws_region" {
  type    = string
  default = "eu-west-3"
}

variable "prefix_name" {
  type    = string
  default = "estate-os-service-prod"
}

# Public hostname for the property-images bucket. Set in the Coolify
# project-level `IMAGES_CDN_BASE_URL` env var (prefixed with `https://`)
# and resolved at request time by the FE via the api response payload.
# DNS lives in Cloudflare — operator adds a proxied CNAME pointing at
# `images_bucket_s3_host` (see `_outputs.tf`) plus an Origin Rule that
# rewrites the `Host` header on the upstream request to S3.
variable "cdn_domain_name" {
  type    = string
  default = "images.predileto.pt"
}
