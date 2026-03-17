resource "aws_security_group" "this" {
  name        = var.security_group_name
  description = var.security_group_description
  vpc_id      = var.vpc_id

  dynamic "ingress" {
    for_each = var.ingress_rules
    content {
      description     = ingress.value.description
      from_port       = ingress.value.from_port
      to_port         = ingress.value.to_port
      protocol        = ingress.value.protocol
      cidr_blocks     = try(coalesce(ingress.value.cidr_blocks), null)
      security_groups = try(coalesce(ingress.value.security_groups), null)
    }
  }

  dynamic "egress" {
    for_each = var.egress_rules
    content {
      from_port        = egress.value.from_port
      to_port          = egress.value.to_port
      protocol         = egress.value.protocol
      cidr_blocks      = try(coalesce(egress.value.cidr_blocks), null)
      ipv6_cidr_blocks = try(coalesce(egress.value.ipv6_cidr_blocks), null)
      security_groups  = try(coalesce(egress.value.security_groups), null)
    }
  }
}