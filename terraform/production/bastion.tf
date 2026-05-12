###############################################################################
# Bastion host — SSH jump box for operator access into private subnets.
#
# Pattern mirrors raz-consulting-services/compliance-agent-service:
# - **BYOK**: no tls_private_key generation. The operator pastes their
#   own laptop's SSH public key into `terraform.tfvars`
#   (`var.bastion_public_key`). Nothing private touches tfstate or the
#   working directory.
# - Direct `aws_instance` + `aws_security_group` resources (skipping the
#   ec2/security-group modules) — a single bastion with no app payload
#   doesn't benefit from the module layer.
# - IMDSv2 required — defense against SSRF-based IMDS abuse.
# - SG-to-SG ingress on the API EC2 (`ec2_sg` adds `aws_security_group.
#   bastion.id` as an allowed source for port 22).
#
# Operator workflow:
#   ssh -J ec2-user@<bastion-eip> ec2-user@<api-ec2-private-ip>
###############################################################################

# --- Security group: SSH ingress from var.bastion_allowed_cidr ---------------
resource "aws_security_group" "bastion" {
  name        = "${var.prefix_name}-bastion-sg"
  description = "Bastion ingress: SSH from configured CIDR"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.bastion_allowed_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.prefix_name}-bastion-sg"
  }
}

# --- Key pair: registers the operator's existing SSH public key --------------
# No private key is generated or stored by Terraform — the operator pastes
# their own laptop's public key into terraform.tfvars (var.bastion_public_key).
resource "aws_key_pair" "bastion" {
  key_name   = "${var.prefix_name}-bastion"
  public_key = var.bastion_public_key
}

# --- Bastion EC2 (t4g.nano, arm64) -------------------------------------------
resource "aws_instance" "bastion" {
  ami                         = data.aws_ami.amazon_linux_2023_arm.id
  instance_type               = "t4g.nano"
  subnet_id                   = module.vpc.presentation_subnets_ids[0]
  vpc_security_group_ids      = [aws_security_group.bastion.id]
  key_name                    = aws_key_pair.bastion.key_name
  associate_public_ip_address = true

  metadata_options {
    http_tokens   = "required" # IMDSv2 only
    http_endpoint = "enabled"
  }

  tags = {
    Name = "${var.prefix_name}-bastion"
  }
}

# --- Stable public IP --------------------------------------------------------
# EIP keeps the operator's ~/.ssh/config ProxyJump entry valid across
# bastion stop/start cycles.
resource "aws_eip" "bastion" {
  instance = aws_instance.bastion.id
  domain   = "vpc"
}
