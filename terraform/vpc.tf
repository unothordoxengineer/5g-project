###############################################################################
# vpc.tf — VPC, subnets, routing and NAT for the 5G Core AWS deployment
#
# Topology
#   VPC  10.0.0.0/16
#   ├── public-1  10.0.1.0/24   (AZ-a)  — Load Balancers, NAT GW
#   ├── public-2  10.0.2.0/24   (AZ-b)  — Load Balancers, NAT GW
#   ├── private-1 10.0.11.0/24  (AZ-a)  — EKS nodes, SageMaker, RDS
#   └── private-2 10.0.12.0/24  (AZ-b)  — EKS nodes, SageMaker, RDS
###############################################################################

# ── VPC ──────────────────────────────────────────────────────────────────────

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true   # Required for EKS and ECR endpoints

  tags = {
    Name = "${var.project_name}-vpc"
  }
}

# ── Internet Gateway ─────────────────────────────────────────────────────────

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${var.project_name}-igw"
  }
}

# ── Public Subnets ───────────────────────────────────────────────────────────

resource "aws_subnet" "public" {
  count = length(var.availability_zones)

  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidrs[count.index]
  availability_zone       = var.availability_zones[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name                                          = "${var.project_name}-public-${count.index + 1}"
    "kubernetes.io/cluster/${var.cluster_name}"   = "shared"
    "kubernetes.io/role/elb"                      = "1"   # Required for AWS LBC
  }
}

# ── Private Subnets ──────────────────────────────────────────────────────────

resource "aws_subnet" "private" {
  count = length(var.availability_zones)

  vpc_id            = aws_vpc.main.id
  cidr_block        = var.private_subnet_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]

  tags = {
    Name                                          = "${var.project_name}-private-${count.index + 1}"
    "kubernetes.io/cluster/${var.cluster_name}"   = "shared"
    "kubernetes.io/role/internal-elb"             = "1"   # Required for AWS LBC internal
  }
}

# ── Elastic IPs for NAT Gateways ─────────────────────────────────────────────
# One NAT GW per AZ for AZ-level resilience

resource "aws_eip" "nat" {
  count  = length(var.availability_zones)
  domain = "vpc"

  tags = {
    Name = "${var.project_name}-nat-eip-${count.index + 1}"
  }

  depends_on = [aws_internet_gateway.main]
}

# ── NAT Gateways ─────────────────────────────────────────────────────────────

resource "aws_nat_gateway" "main" {
  count = length(var.availability_zones)

  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id

  tags = {
    Name = "${var.project_name}-nat-${count.index + 1}"
  }

  depends_on = [aws_internet_gateway.main]
}

# ── Route Tables — Public ─────────────────────────────────────────────────────

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "${var.project_name}-public-rt"
  }
}

resource "aws_route_table_association" "public" {
  count = length(var.availability_zones)

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# ── Route Tables — Private (one per AZ → own NAT GW) ─────────────────────────

resource "aws_route_table" "private" {
  count  = length(var.availability_zones)
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main[count.index].id
  }

  tags = {
    Name = "${var.project_name}-private-rt-${count.index + 1}"
  }
}

resource "aws_route_table_association" "private" {
  count = length(var.availability_zones)

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

# ── Security Group — EKS Node ─────────────────────────────────────────────────

resource "aws_security_group" "eks_nodes" {
  name        = "${var.project_name}-eks-nodes-sg"
  description = "Allow inter-node and node-to-control-plane communication"
  vpc_id      = aws_vpc.main.id

  # All traffic within the node SG (pod-to-pod)
  ingress {
    description = "All intra-cluster traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    self        = true
  }

  # Allow ALB health-check and ingress
  ingress {
    description = "HTTPS from VPC"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  ingress {
    description = "HTTP from VPC"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  # ML serving API NodePort (matches kind local NodePort 30800)
  ingress {
    description = "ML Serving API NodePort"
    from_port   = 30800
    to_port     = 30800
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-eks-nodes-sg"
  }
}
