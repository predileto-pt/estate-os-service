module "acm" {
  source = "../modules/acm"

  domain = var.domain_name
}
