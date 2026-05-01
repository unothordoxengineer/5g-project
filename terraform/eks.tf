###############################################################################
# eks.tf — EKS cluster + managed node group + add-ons
#
# Uses the official terraform-aws-modules/eks/aws module (v20.x) which
# abstracts away the aws_eks_cluster + aws_eks_node_group boilerplate while
# remaining fully auditable.
###############################################################################

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  # ── Cluster identity ───────────────────────────────────────────────────────
  cluster_name    = var.cluster_name
  cluster_version = var.kubernetes_version

  # ── Networking ────────────────────────────────────────────────────────────
  vpc_id     = aws_vpc.main.id
  subnet_ids = aws_subnet.private[*].id

  # Public endpoint — accessible from your workstation; restrict in prod
  cluster_endpoint_public_access  = true
  cluster_endpoint_private_access = true

  # ── IAM ───────────────────────────────────────────────────────────────────
  iam_role_arn = aws_iam_role.eks_cluster.arn
  # OIDC issuer is used by iam.tf to wire IRSA roles
  enable_irsa  = true

  # ── Core EKS add-ons ──────────────────────────────────────────────────────
  cluster_addons = {
    coredns = {
      most_recent = true
    }
    kube-proxy = {
      most_recent = true
    }
    vpc-cni = {
      most_recent    = true
      before_compute = true   # ENI warm-up before nodes join
    }
    aws-ebs-csi-driver = {
      most_recent              = true
      service_account_role_arn = aws_iam_role.ebs_csi_driver.arn
    }
  }

  # ── Managed node groups ────────────────────────────────────────────────────
  eks_managed_node_groups = {
    # General-purpose group — runs all Open5GS NFs + UERANSIM
    core = {
      name           = "${var.project_name}-workers"
      instance_types = [var.node_instance_type]
      ami_type       = "AL2_x86_64"

      min_size     = var.node_group_min
      max_size     = var.node_group_max
      desired_size = var.node_group_desired

      disk_size = var.node_disk_size_gb

      iam_role_arn = aws_iam_role.eks_node_group.arn

      # Spread across all private subnets (two AZs)
      subnet_ids = aws_subnet.private[*].id

      vpc_security_group_ids = [aws_security_group.eks_nodes.id]

      labels = {
        role        = "general"
        "node.kubernetes.io/5g-workload" = "true"
      }

      # Enable Cluster Autoscaler discovery tags
      tags = {
        "k8s.io/cluster-autoscaler/enabled"               = "true"
        "k8s.io/cluster-autoscaler/${var.cluster_name}"   = "owned"
      }
    }
  }

  tags = {
    Name = var.cluster_name
  }
}

###############################################################################
# EBS CSI Driver IRSA role (required for PersistentVolumes in EKS 1.23+)
###############################################################################

data "aws_iam_policy_document" "ebs_csi_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.eks.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${replace(module.eks.cluster_oidc_issuer_url, "https://", "")}:sub"
      values   = ["system:serviceaccount:kube-system:ebs-csi-controller-sa"]
    }
  }
}

resource "aws_iam_role" "ebs_csi_driver" {
  name               = "${var.project_name}-ebs-csi-driver"
  assume_role_policy = data.aws_iam_policy_document.ebs_csi_assume.json

  tags = { Name = "${var.project_name}-ebs-csi-driver" }
}

resource "aws_iam_role_policy_attachment" "ebs_csi_policy" {
  role       = aws_iam_role.ebs_csi_driver.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}

###############################################################################
# StorageClass — gp3 default (replaces hostPath used in kind)
###############################################################################

resource "kubernetes_storage_class" "gp3" {
  metadata {
    name = "gp3"
    annotations = {
      "storageclass.kubernetes.io/is-default-class" = "true"
    }
  }

  storage_provisioner    = "ebs.csi.aws.com"
  reclaim_policy         = "Delete"
  volume_binding_mode    = "WaitForFirstConsumer"
  allow_volume_expansion = true

  parameters = {
    type      = "gp3"
    encrypted = "true"
  }

  depends_on = [module.eks]
}

###############################################################################
# Cluster Autoscaler — Helm chart
###############################################################################

resource "helm_release" "cluster_autoscaler" {
  name       = "cluster-autoscaler"
  repository = "https://kubernetes.github.io/autoscaler"
  chart      = "cluster-autoscaler"
  namespace  = "kube-system"
  version    = "9.37.0"

  set {
    name  = "autoDiscovery.clusterName"
    value = var.cluster_name
  }
  set {
    name  = "awsRegion"
    value = var.aws_region
  }
  set {
    name  = "rbac.serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn"
    value = aws_iam_role.cluster_autoscaler.arn
  }
  set {
    name  = "resources.requests.cpu"
    value = "100m"
  }
  set {
    name  = "resources.requests.memory"
    value = "300Mi"
  }

  depends_on = [module.eks]
}

###############################################################################
# AWS Load Balancer Controller — replaces NodePort for production ingress
###############################################################################

resource "helm_release" "aws_load_balancer_controller" {
  name       = "aws-load-balancer-controller"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  namespace  = "kube-system"
  version    = "1.7.2"

  set {
    name  = "clusterName"
    value = var.cluster_name
  }
  set {
    name  = "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn"
    value = aws_iam_role.aws_lbc.arn
  }

  depends_on = [module.eks]
}

# IRSA for AWS LBC
data "aws_iam_policy_document" "aws_lbc_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.eks.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${replace(module.eks.cluster_oidc_issuer_url, "https://", "")}:sub"
      values   = ["system:serviceaccount:kube-system:aws-load-balancer-controller"]
    }
  }
}

resource "aws_iam_role" "aws_lbc" {
  name               = "${var.project_name}-aws-lbc"
  assume_role_policy = data.aws_iam_policy_document.aws_lbc_assume.json

  tags = { Name = "${var.project_name}-aws-lbc" }
}

# AWS-managed policy for LBC (must exist in the account)
resource "aws_iam_policy" "aws_lbc" {
  name        = "${var.project_name}-AWSLoadBalancerControllerIAMPolicy"
  description = "IAM policy for AWS Load Balancer Controller"

  # Full policy JSON from https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/main/docs/install/iam_policy.json
  policy = file("${path.module}/files/aws-lbc-iam-policy.json")
}

resource "aws_iam_role_policy_attachment" "aws_lbc" {
  role       = aws_iam_role.aws_lbc.name
  policy_arn = aws_iam_policy.aws_lbc.arn
}
