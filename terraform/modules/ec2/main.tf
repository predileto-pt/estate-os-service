resource "aws_instance" "this" {
  
  ami           = var.ami
  instance_type = var.instance_type

  subnet_id                   = var.subnet_id
  vpc_security_group_ids      = var.security_groups
  associate_public_ip_address = var.associate_public_ip_address

  source_dest_check = var.source_dest_check

  key_name = var.key_name

  user_data_base64     = var.user_data
  iam_instance_profile = var.iam_instance_profile

  root_block_device {
    volume_type = var.volume_type
    volume_size = var.volume_size
  }

  tags = {
    Name = var.instance_name
  }
}