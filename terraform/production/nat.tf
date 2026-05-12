###############################################################################
# NAT EC2 — egress for private subnets. Cheap alternative to a managed
# `aws_nat_gateway` (~$3.50/mo vs ~$32/mo fixed). Single instance in AZ-a;
# upgrade path documented in `terraform/modules/nat-instance/main.tf`.
###############################################################################

data "aws_ami" "amazon_linux_2023_arm" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023*-arm64"]
  }

  filter {
    name   = "architecture"
    values = ["arm64"]
  }
}

module "nat_instance" {
  source = "../modules/nat-instance"

  name_prefix          = var.prefix_name
  vpc_id               = module.vpc.vpc_id
  public_subnet_id     = module.vpc.presentation_subnets_ids[0]
  private_subnet_cidrs = ["10.0.11.0/24", "10.0.12.0/24", "10.0.13.0/24", "10.0.21.0/24", "10.0.22.0/24", "10.0.23.0/24"]
  ami_id               = data.aws_ami.amazon_linux_2023_arm.id
  instance_type        = "t4g.nano"
  key_name             = var.key_name
}
