###############################################################################
# CloudFront distribution for the property-images bucket.
#
# Origin Access Control (OAC, sigv4) — the modern replacement for OAI.
# The bucket policy below restricts s3:GetObject to this specific
# distribution via the AWS:SourceArn condition; no other path can read
# the bucket from outside.
#
# Distribution itself is a global AWS resource; we configure it through
# the default eu-west-3 provider. The cert lives in us-east-1 (see
# acm.tf) but the distribution accepts ARNs from either region.
#
# CORS at the CloudFront layer is intentionally NOT configured — `<img
# src="">` doesn't trigger a CORS preflight. If a future feature needs
# to fetch image bytes via `fetch()`, add a response-headers policy
# with `Access-Control-Allow-Origin`.
###############################################################################

resource "aws_cloudfront_origin_access_control" "images" {
  name                              = "${var.prefix_name}-property-images"
  description                       = "OAC for ${module.images_bucket.name}"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "images" {
  enabled         = true
  is_ipv6_enabled = true
  comment         = "Property images CDN — ${var.cdn_domain_name}"

  aliases = [var.cdn_domain_name]

  # Free tier price class (US + Canada + Europe). Re-evaluate if we
  # ever target users outside Europe meaningfully.
  price_class = "PriceClass_100"

  origin {
    origin_id                = "s3-images-bucket"
    domain_name              = "${module.images_bucket.name}.s3.${var.aws_region}.amazonaws.com"
    origin_access_control_id = aws_cloudfront_origin_access_control.images.id
  }

  default_cache_behavior {
    target_origin_id       = "s3-images-bucket"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    # AWS-managed CachingOptimized policy — Cache-Control / Etag honored,
    # gzip + brotli compression on text payloads, sensible default TTLs.
    # (S3 image objects don't include Cache-Control on PUT today; the
    # response-headers policy in the follow-up commit overrides this so
    # browsers cache for a year.)
    cache_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.images.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}

# Lock the images bucket so only this distribution can read it. Anyone
# trying https://<bucket>.s3.eu-west-3.amazonaws.com/<key> gets 403.
resource "aws_s3_bucket_policy" "images" {
  bucket = module.images_bucket.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowCloudFrontOACRead"
        Effect = "Allow"
        Principal = {
          Service = "cloudfront.amazonaws.com"
        }
        Action   = "s3:GetObject"
        Resource = "${module.images_bucket.arn}/*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.images.arn
          }
        }
      }
    ]
  })
}
