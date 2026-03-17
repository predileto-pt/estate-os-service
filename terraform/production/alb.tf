module "alb" {
  source = "../modules/alb"

  name            = "${var.prefix_name}-alb"
  vpc_id          = module.vpc.vpc_id
  subnet_ids      = module.vpc.presentation_subnets_ids
  security_groups = [module.alb_sg.security_group_id]
  target_id       = module.ec2.instance_id

  health_check_path = "/api/v1/health"

  listeners = [
    {
      port            = 443
      protocol        = "HTTPS"
      target_port     = 8000
      target_protocol = "HTTP"
      certificate_arn = module.acm.arn
    },
    {
      port            = 80
      protocol        = "HTTP"
      target_port     = 8000
      target_protocol = "HTTP"
    },
  ]
}
