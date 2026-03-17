# --> Route Table - Public
resource "aws_route_table" "this-public-rt" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = {
    Name = "${var.network_name}-public-rt"
  }
}

resource "aws_route_table_association" "public_route_association" {
  count          = 3
  subnet_id      = aws_subnet.this-presentation-subnets[count.index].id
  route_table_id = aws_route_table.this-public-rt.id
}

# --> Route Table - Private
resource "aws_route_table" "private_route_table" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name = "${var.network_name}-private-rt"
  }
}

resource "aws_route" "private_route" {
  count                  = var.enable_nat_gateway ? 1 : var.enable_ec2_nat_gateway ? 1 : 0
  route_table_id         = aws_route_table.private_route_table.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = var.enable_nat_gateway ? aws_nat_gateway.this-natgateway[0].id : null
  network_interface_id   = var.enable_ec2_nat_gateway ? var.ec2_nat_gateway_id : null
}

resource "aws_route_table_association" "private_route_association" {
  count          = length(var.logic_subnets)
  subnet_id      = aws_subnet.this-logic-subnets[count.index].id
  route_table_id = aws_route_table.private_route_table.id
}

resource "aws_route_table_association" "private_data_route_association" {
  count          = length(var.data_subnets)
  subnet_id      = aws_subnet.this-data-subnets[count.index].id
  route_table_id = aws_route_table.private_route_table.id
}