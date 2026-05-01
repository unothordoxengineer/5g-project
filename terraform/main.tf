###############################################################################
# main.tf — Provider configuration and Terraform backend
# Cloud-Native 5G SA Core — Phase 8 AWS Migration
###############################################################################

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.50"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.30"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.13"
    }
  }

  # ── Uncomment once an S3 bucket + DynamoDB lock table exist ────────────────
  # backend "s3" {
  #   bucket         = "5g-project-tfstate"
  #   key            = "phase8/terraform.tfstate"
  #   region         = "us-east-1"
  #   encrypt        = true
  #   dynamodb_table = "5g-project-tflock"
  # }
}

###############################################################################
# AWS provider — region + default tags applied to every resource
###############################################################################
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "5g-core"
      Phase       = "8"
      ManagedBy   = "terraform"
      Owner       = "nigelkadzinga91@gmail.com"
      Environment = var.environment
    }
  }
}

###############################################################################
# Kubernetes & Helm providers — wired to the EKS cluster created in eks.tf
###############################################################################
provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)

  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args = [
      "eks", "get-token",
      "--cluster-name", module.eks.cluster_name,
      "--region", var.aws_region,
    ]
  }
}

provider "helm" {
  kubernetes {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)

    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args = [
        "eks", "get-token",
        "--cluster-name", module.eks.cluster_name,
        "--region", var.aws_region,
      ]
    }
  }
}
