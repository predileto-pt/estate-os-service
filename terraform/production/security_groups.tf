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
  security_group_description = "Security group for EC2 - allows traffic from ALB and SSH"
  vpc_id                     = module.vpc.vpc_id

  ingress_rules = [
    {
      description     = "App traffic from ALB"
      from_port       = 8000
      to_port         = 8000
      protocol        = "tcp"
      security_groups = [module.alb_sg.security_group_id]
    },
    {
      description = "SSH access"
      from_port   = 22
      to_port     = 22
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
