resource "aws_lb" "this" {
  name                   = var.name
  load_balancer_type     = var.load_balancer_type
  ip_address_type        = var.ip_address_type
  desync_mitigation_mode = var.desync_mitigation_mode

  idle_timeout                     = 60
  drop_invalid_header_fields       = false
  enable_cross_zone_load_balancing = true
  enable_deletion_protection       = true
  enable_http2                     = true
  enable_waf_fail_open             = false
  internal                         = false
  preserve_host_header             = false

  security_groups = var.security_groups
  subnets         = var.subnet_ids

  dynamic "access_logs" {
    for_each = length(var.access_logs) > 0 ? [var.access_logs] : []

    content {
      bucket  = access_logs.value.bucket
      enabled = try(access_logs.value.enabled, true)
      prefix  = try(access_logs.value.prefix, null)
    }
  }

  dynamic "subnet_mapping" {
    for_each = var.subnet_mappings
    content {
      subnet_id     = subnet_mapping.value.subnet_id
      allocation_id = subnet_mapping.value.allocation_id
    }
  }
}

# --> target group dynamic port
resource "aws_lb_target_group" "this" {
  for_each = {
    for l in var.listeners : "${l.port}" => l
  }

  name        = "${var.tg_name}-${each.value.port}"
  port        = each.value.target_port
  protocol    = each.value.target_protocol
  vpc_id      = var.vpc_id
  target_type = "instance"

  health_check {
    enabled             = true
    path                = var.health_check_path
    port                = "traffic-port"
    protocol            = "HTTP"
    healthy_threshold   = 2
    unhealthy_threshold = 2
    timeout             = 5
    interval            = 10
    matcher             = "200"
  }
}

# --> target group attachment dynamic port
resource "aws_lb_target_group_attachment" "this" {
  for_each = {
    for l in var.listeners : "${l.port}" => l
  }

  target_group_arn = aws_lb_target_group.this[each.key].arn
  target_id        = var.target_id
  port             = each.value.target_port
}

# --> listener dynamic port
resource "aws_lb_listener" "this" {
  for_each = {
    for l in var.listeners : "${l.port}" => l
  }

  load_balancer_arn = aws_lb.this.arn
  port              = each.value.port
  protocol          = each.value.protocol

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this[each.key].arn
  }

  ssl_policy      = each.value.protocol == "HTTPS" ? "ELBSecurityPolicy-2016-08" : null
  certificate_arn = each.value.protocol == "HTTPS" ? each.value.certificate_arn : null
}
