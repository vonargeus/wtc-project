# File: infra/aws.tf

# Configure the AWS Provider
provider "aws" {
  region = "us-west-2"
}

# Create a VPC
resource "aws_vpc" "gaming_assistant_vpc" {
  cidr_block = "10.0.0.0/16"
  tags = {
    Name = "gaming-assistant-vpc"
  }
}

# Create a subnet
resource "aws_subnet" "gaming_assistant_subnet" {
  vpc_id            = aws_vpc.gaming_assistant_vpc.id
  cidr_block        = "10.0.1.0/24"
  availability_zone = "us-west-2a"
  tags = {
    Name = "gaming-assistant-subnet"
  }
}

# Create a security group
resource "aws_security_group" "gaming_assistant_sg" {
  vpc_id = aws_vpc.gaming_assistant_vpc.id
  name        = "gaming-assistant-sg"
  description = "Security group for gaming assistant"

  # Inbound rules
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Outbound rules
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "gaming-assistant-sg"
  }
}