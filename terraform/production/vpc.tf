module "vpc" {
  source = "../modules/vpc"

  network_name = var.prefix_name
  vpc_cidr     = "10.0.0.0/16"

  presentation_subnets = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
  logic_subnets        = ["10.0.11.0/24", "10.0.12.0/24", "10.0.13.0/24"]
  data_subnets         = ["10.0.21.0/24", "10.0.22.0/24", "10.0.23.0/24"]

  presentation_subnet_tags = { Tier = "public" }
  logic_subnet_tags        = { Tier = "private" }

  enable_nat_gateway = false
}
