locals {
  presentation_subnets_cidrs = [for s in aws_subnet.this-presentation-subnets : s.cidr_block]
  presentation_subnets_ids   = [for s in aws_subnet.this-presentation-subnets : s.id]

  logic_subnets_cidrs = [for s in aws_subnet.this-logic-subnets : s.cidr_block]
  logic_subnets_ids   = [for s in aws_subnet.this-logic-subnets : s.id]

  data_subnets_cidrs = [for s in aws_subnet.this-data-subnets : s.cidr_block]
  data_subnets_ids   = [for s in aws_subnet.this-data-subnets : s.id]

  subnet_cidrs = concat(local.presentation_subnets_cidrs, local.logic_subnets_cidrs, local.data_subnets_cidrs)
  subnet_ids   = concat(local.presentation_subnets_ids, local.logic_subnets_ids, local.data_subnets_ids)
}