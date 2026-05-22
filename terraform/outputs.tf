###############################################################################
# outputs.tf — Key values needed after deployment
###############################################################################

# ── EKS ──────────────────────────────────────────────────────────────────────

output "eks_cluster_name" {
  description = "Name of the EKS cluster"
  value       = module.eks.cluster_name
}

output "eks_cluster_endpoint" {
  description = "API server endpoint URL for the EKS cluster"
  value       = module.eks.cluster_endpoint
}

output "eks_cluster_version" {
  description = "Kubernetes version running on the EKS cluster"
  value       = module.eks.cluster_version
}

output "eks_cluster_certificate_authority" {
  description = "Base64-encoded CA certificate for kubectl configuration"
  value       = module.eks.cluster_certificate_authority_data
  sensitive   = true
}

output "configure_kubectl" {
  description = "Run this command to configure kubectl after deployment"
  value       = "aws eks update-kubeconfig --name ${module.eks.cluster_name} --region ${var.aws_region}"
}

# ── VPC ──────────────────────────────────────────────────────────────────────

output "vpc_id" {
  description = "ID of the project VPC"
  value       = aws_vpc.main.id
}

output "public_subnet_ids" {
  description = "IDs of public subnets (for ALB, NAT GW)"
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "IDs of private subnets (EKS nodes, SageMaker)"
  value       = aws_subnet.private[*].id
}

# ── ECR ──────────────────────────────────────────────────────────────────────

output "ecr_registry_url" {
  description = "ECR registry base URL (account.dkr.ecr.region.amazonaws.com)"
  value       = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
}

output "ecr_repository_urls" {
  description = "Map of image name → ECR repository URL for all 15 repositories"
  value       = { for name, repo in aws_ecr_repository.repos : name => repo.repository_url }
}

output "ecr_login_command" {
  description = "Docker login command for ECR"
  value       = "aws ecr get-login-password --region ${var.aws_region} | docker login --username AWS --password-stdin ${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
}

# ── SageMaker ────────────────────────────────────────────────────────────────

# SageMaker endpoint outputs commented out — endpoints not yet deployed.
# Uncomment after pushing ECR images and re-enabling sagemaker.tf resources.
#
# output "sagemaker_endpoint_names" { ... }
# output "sagemaker_endpoint_arns"  { ... }
# output "sagemaker_invoke_example" { ... }

# ── Monitoring ───────────────────────────────────────────────────────────────

output "amp_workspace_id" {
  description = "AWS Managed Prometheus workspace ID"
  value       = aws_prometheus_workspace.main.id
}

output "amp_workspace_endpoint" {
  description = "AMP remote_write URL for Prometheus Agent configuration"
  value       = "${aws_prometheus_workspace.main.prometheus_endpoint}api/v1/remote_write"
}

output "grafana_service_name" {
  description = "Self-managed Grafana Helm release name (access via kubectl port-forward)"
  value       = helm_release.grafana.name
}

# ── IAM ──────────────────────────────────────────────────────────────────────

output "github_actions_role_arn" {
  description = "IAM role ARN for GitHub Actions OIDC — add to repo secret AWS_ROLE_ARN"
  value       = aws_iam_role.github_actions.arn
}

output "sagemaker_execution_role_arn" {
  description = "SageMaker execution role ARN"
  value       = aws_iam_role.sagemaker_execution.arn
}

# ── Summary ───────────────────────────────────────────────────────────────────

output "deployment_summary" {
  description = "Human-readable summary of all deployed resources"
  value       = <<-EOT
    ╔══════════════════════════════════════════════════════════╗
    ║   5G Core Phase 8 — AWS Deployment Summary               ║
    ╠══════════════════════════════════════════════════════════╣
    ║  EKS Cluster : ${module.eks.cluster_name}
    ║  Region      : ${var.aws_region}
    ║  Nodes       : ${var.node_group_desired}x ${var.node_instance_type}
    ║  AMP         : ${aws_prometheus_workspace.main.id}
    ║  Grafana     : kubectl port-forward svc/grafana 3000:80 -n monitoring
    ╠══════════════════════════════════════════════════════════╣
    ║  Next step:
    ║    aws eks update-kubeconfig --name ${module.eks.cluster_name} --region ${var.aws_region}
    ╚══════════════════════════════════════════════════════════╝
  EOT
}
