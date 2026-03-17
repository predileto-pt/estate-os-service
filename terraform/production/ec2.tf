module "ec2" {
  source = "../modules/ec2"

  ami                         = data.aws_ami.amazon_linux_2023.id
  instance_type               = var.instance_type
  key_name                    = var.key_name
  volume_type                 = "gp3"
  volume_size                 = var.volume_size
  subnet_id                   = module.vpc.presentation_subnets_ids[0]
  associate_public_ip_address = true
  security_groups             = [module.ec2_sg.security_group_id]
  instance_name               = "${var.prefix_name}-server"

  user_data = base64encode(file("${path.module}/../../deploy/user_data.sh"))

  iam_instance_profile = aws_iam_instance_profile.ec2_profile.name
}
