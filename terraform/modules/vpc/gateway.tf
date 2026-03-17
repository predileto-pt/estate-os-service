# --> Internet Gateway
resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = merge(
    {
      Name = "${var.network_name}-igw"
    }
  )
}

# --> Nat Gateway
resource "aws_nat_gateway" "this-natgateway" {
  count         = var.enable_nat_gateway ? 1 : 0
  allocation_id = aws_eip.this-eip.id
  subnet_id     = aws_subnet.this-presentation-subnets[0].id

  tags = merge(
    {
      Name = "${var.network_name}-natgw"
    },
  )

  depends_on = [aws_internet_gateway.this]
}