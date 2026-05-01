###############################################################################
# variables.tf — All configurable inputs for the 5G Core AWS deployment
###############################################################################

# ── General ──────────────────────────────────────────────────────────────────

variable "aws_region" {
  description = "AWS region to deploy all resources into"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment label (dev | staging | prod)"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

variable "project_name" {
  description = "Short name used as a prefix for all resource names"
  type        = string
  default     = "5g-core"
}

# ── Networking ───────────────────────────────────────────────────────────────

variable "vpc_cidr" {
  description = "CIDR block for the project VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "List of AZs to use (must have at least 2 for EKS)"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

variable "public_subnet_cidrs" {
  description = "CIDRs for public subnets (one per AZ)"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "private_subnet_cidrs" {
  description = "CIDRs for private subnets (one per AZ) — EKS nodes live here"
  type        = list(string)
  default     = ["10.0.11.0/24", "10.0.12.0/24"]
}

# ── EKS Cluster ──────────────────────────────────────────────────────────────

variable "cluster_name" {
  description = "Name of the EKS cluster"
  type        = string
  default     = "5g-core-eks"
}

variable "kubernetes_version" {
  description = "Kubernetes version for the EKS cluster"
  type        = string
  default     = "1.30"
}

variable "node_instance_type" {
  description = "EC2 instance type for the EKS worker node group"
  type        = string
  default     = "t3.medium"
}

variable "node_group_desired" {
  description = "Desired number of worker nodes"
  type        = number
  default     = 3
}

variable "node_group_min" {
  description = "Minimum number of worker nodes (for cluster autoscaler)"
  type        = number
  default     = 1
}

variable "node_group_max" {
  description = "Maximum number of worker nodes (for cluster autoscaler)"
  type        = number
  default     = 6
}

variable "node_disk_size_gb" {
  description = "Root EBS disk size (GiB) per worker node"
  type        = number
  default     = 50
}

# ── ECR ──────────────────────────────────────────────────────────────────────

variable "ecr_image_retention_count" {
  description = "Number of tagged images to retain per ECR repository"
  type        = number
  default     = 10
}

variable "ecr_scan_on_push" {
  description = "Enable ECR vulnerability scanning on each image push"
  type        = bool
  default     = true
}

# ── SageMaker ────────────────────────────────────────────────────────────────

variable "sagemaker_instance_type" {
  description = "ML instance type for SageMaker real-time endpoints"
  type        = string
  default     = "ml.t2.medium"
}

variable "sagemaker_model_bucket" {
  description = "S3 bucket that contains the packaged ML model artifacts (model.tar.gz files)"
  type        = string
  default     = ""   # Set to your bucket name before applying
}

variable "sagemaker_container_image" {
  description = "ECR image URI for the SageMaker inference container (5g-serving-api)"
  type        = string
  default     = ""   # Populated from ecr.tf output after first push
}

# ── Monitoring ───────────────────────────────────────────────────────────────

variable "amp_retention_days" {
  description = "Metrics retention period for AWS Managed Prometheus (days)"
  type        = number
  default     = 30
}

variable "amg_grafana_version" {
  description = "Grafana version to use for the AMG workspace"
  type        = string
  default     = "10.4"
}

variable "grafana_admin_email" {
  description = "Email address for the Grafana admin/notification alerts"
  type        = string
  default     = "nigelkadzinga91@gmail.com"
}
