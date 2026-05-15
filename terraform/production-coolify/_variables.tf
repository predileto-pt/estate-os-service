variable "aws_region" {
  type    = string
  default = "eu-west-3"
}

variable "prefix_name" {
  type    = string
  default = "estate-os-service-prod"
}

# CDN hostname for the property-images CloudFront distribution.
# Used by `acm.tf` (cert domain_name) and `cloudfront.tf` (distribution
# aliases). DNS lives in Vercel — operator adds the CNAME during the
# runbook section 10 bring-up.
variable "cdn_domain_name" {
  type    = string
  default = "images.predileto.pt"
}
