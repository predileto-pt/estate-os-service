module "eip" {
  source = "../modules/eip"

  instance_id = module.ec2.instance_id
}
