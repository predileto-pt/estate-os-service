###############################################################################
# ACM certificate for the property-images CDN.
#
# CloudFront's custom-domain TLS requires the cert in us-east-1. The
# bucket lives in eu-west-3 — that's fine; only the cert needs the
# specific region. All resources here use the `aws.us_east_1` aliased
# provider from _providers.tf.
#
# Validation is DNS-based: terraform creates the cert in PENDING state,
# outputs the validation record name + value, and the operator adds a
# CNAME at Vercel pointing the name at the value. Once propagated, the
# validation resource flips ISSUED and CloudFront can attach the cert.
###############################################################################

resource "aws_acm_certificate" "images" {
  provider = aws.us_east_1

  domain_name       = var.cdn_domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_acm_certificate_validation" "images" {
  provider = aws.us_east_1

  certificate_arn = aws_acm_certificate.images.arn

  # The single validation record name + value land in _outputs.tf so
  # the runbook can show the operator what to add in Vercel DNS.
  validation_record_fqdns = [
    for opt in aws_acm_certificate.images.domain_validation_options : opt.resource_record_name
  ]

  timeouts {
    create = "20m"
  }
}
