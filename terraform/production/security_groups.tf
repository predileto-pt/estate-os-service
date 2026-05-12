module "alb_sg" {
  source = "../modules/security-group"

  security_group_name        = "${var.prefix_name}-alb-sg"
  security_group_description = "Security group for ALB - allows HTTP/HTTPS from internet"
  vpc_id                     = module.vpc.vpc_id

  ingress_rules = [
    {
      description = "HTTP from internet"
      from_port   = 80
      to_port     = 80
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
    },
    {
      description = "HTTPS from internet"
      from_port   = 443
      to_port     = 443
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
    },
  ]

  egress_rules = [
    {
      from_port   = 0
      to_port     = 0
      protocol    = "-1"
      cidr_blocks = ["0.0.0.0/0"]
    },
  ]
}

module "ec2_sg" {
  source = "../modules/security-group"

  security_group_name        = "${var.prefix_name}-ec2-sg"
  security_group_description = "Security group for the API EC2 - app traffic from ALB + SSH from bastion."
  vpc_id                     = module.vpc.vpc_id

  # SSH ingress is gated to the bastion SG (jump-host pattern, matches
  # whyhow-ai/case-identification-monorepo and cargochain). Operator
  # workflow: SSH to bastion via internet (key auth), then ProxyJump
  # to the API EC2 via its private IP.
  ingress_rules = [
    {
      description     = "App traffic from ALB"
      from_port       = 8000
      to_port         = 8000
      protocol        = "tcp"
      security_groups = [module.alb_sg.security_group_id]
    },
    {
      description     = "SSH from bastion only"
      from_port       = 22
      to_port         = 22
      protocol        = "tcp"
      security_groups = [aws_security_group.bastion.id]
    },
  ]

  egress_rules = [
    {
      from_port   = 0
      to_port     = 0
      protocol    = "-1"
      cidr_blocks = ["0.0.0.0/0"]
    },
  ]
}

# Bastion SG lives in `bastion.tf` as a direct `aws_security_group`
# (matches the raz-consulting pattern — module indirection adds noise for
# a single bastion that just needs SSH ingress + all-egress).

# Lambda worker SG — Lambdas are in private (logic) subnets per ADR-018.
# No ingress (Lambdas don't accept inbound). Egress to anywhere via the
# NAT instance (`nat.tf`) so handlers can reach Supabase, OpenAI,
# Pinecone, Reducto, Google Places, Resend, plus AWS service endpoints.
module "lambda_sg" {
  source = "../modules/security-group"

  security_group_name        = "${var.prefix_name}-lambda-sg"
  security_group_description = "Security group for worker Lambdas - egress only via NAT."
  vpc_id                     = module.vpc.vpc_id

  ingress_rules = []

  egress_rules = [
    {
      from_port   = 0
      to_port     = 0
      protocol    = "-1"
      cidr_blocks = ["0.0.0.0/0"]
    },
  ]
}
