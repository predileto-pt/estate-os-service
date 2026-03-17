resource "aws_eip" "this" {
  instance = var.instance_id
  lifecycle {
    prevent_destroy = true
  }
}