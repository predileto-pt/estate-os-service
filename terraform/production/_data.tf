data "aws_caller_identity" "current" {}

# Primary AL2023 — x86_64. Used by the API EC2 (`var.instance_type =
# t3.small` is x86_64). The arm64 sibling for the NAT + bastion
# (t4g.nano) lives in `nat.tf` as `data.aws_ami.amazon_linux_2023_arm`.
data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023*-x86_64"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}
