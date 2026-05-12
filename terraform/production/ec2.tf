# API EC2 in private (logic) subnet (ADR-018). No public IP — the ALB
# in the public subnets is the only internet-facing surface. Outbound
# traffic (ECR, Secrets Manager, SSM, dnf updates, GitHub releases)
# flows via the NAT EC2 in `nat.tf`. Operator shell access uses SSM
# Session Manager (`aws ssm start-session --target <id>`) — the EC2 has
# no public IP and no inbound SSH rule.
module "ec2" {
  source = "../modules/ec2"

  ami                         = data.aws_ami.amazon_linux_2023.id
  instance_type               = var.instance_type
  key_name                    = var.key_name
  volume_type                 = "gp3"
  volume_size                 = var.volume_size
  subnet_id                   = module.vpc.logic_subnets_ids[0]
  associate_public_ip_address = false
  security_groups             = [module.ec2_sg.security_group_id]
  instance_name               = "${var.prefix_name}-server"

  # `templatefile()` injects the infrastructure pointers Terraform owns
  # (queue URLs, topic ARN prefix, bucket name, region, ECR image) into
  # the boot script. The script merges these on top of the Secrets
  # Manager JSON so the operator's secret only holds true secrets.
  user_data = base64encode(templatefile("${path.module}/../../deploy/user_data.sh.tpl", {
    aws_region                         = var.aws_region
    secret_name                        = aws_secretsmanager_secret.app_secrets.name
    ecr_registry                       = "${local.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
    ecr_image                          = local.ecr_image
    s3_bucket_name                     = module.documents_bucket.name
    sns_domain_events_topic_arn_prefix = local.sns_domain_events_topic_arn_prefix
    sqs_property_extraction_queue_url  = module.extraction_queue.id
    sqs_property_enrichment_queue_url  = module.enrichment_queue.id
    sqs_listings_events_queue_url      = module.listings_events_queue.id
  }))

  iam_instance_profile = aws_iam_instance_profile.ec2_profile.name
}
