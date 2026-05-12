module "vpc" {
  source = "../modules/vpc"

  network_name = var.prefix_name
  vpc_cidr     = "10.0.0.0/16"

  presentation_subnets = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
  logic_subnets        = ["10.0.11.0/24", "10.0.12.0/24", "10.0.13.0/24"]
  data_subnets         = ["10.0.21.0/24", "10.0.22.0/24", "10.0.23.0/24"]

  presentation_subnet_tags = { Tier = "public" }
  logic_subnet_tags        = { Tier = "private" }

  # Egress for private subnets via the NAT EC2 (see `nat.tf`). The
  # managed `aws_nat_gateway` stays off — too expensive for v1
  # workloads. Flip `enable_nat_gateway = true` later if availability
  # becomes worth the price.
  enable_nat_gateway     = false
  enable_ec2_nat_gateway = true
  ec2_nat_gateway_id     = module.nat_instance.primary_network_interface_id
}
