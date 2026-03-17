# --> VPC
resource "aws_vpc" "this" {
  cidr_block       = var.vpc_cidr
  instance_tenancy = "default"

  tags = merge(
    { Name = "${var.network_name}-vpc" },
  )
}

# --> Elastic IP
resource "aws_eip" "this-eip" {
  domain = "vpc"

  tags = merge(
    {
      Name = "${var.network_name}-eip-natgw"
    },
  )
}