###############################################################################
# monitoring.tf — AWS Managed Prometheus (AMP) + AWS Managed Grafana (AMG)
#
# Mirrors the local Prometheus + Grafana stack from Phase 4, running managed
# by AWS so there's nothing to operate.
#
# Data flow:
#   EKS nodes (Prometheus Agent)
#     → AMP workspace (remote_write)
#       → AMG dashboard (data source = AMP)
###############################################################################

###############################################################################
# AWS Managed Prometheus (AMP)
###############################################################################

resource "aws_prometheus_workspace" "main" {
  alias = "${var.project_name}-amp"

  logging_configuration {
    log_group_arn = "${aws_cloudwatch_log_group.amp.arn}:*"
  }

  tags = {
    Name = "${var.project_name}-amp"
  }
}

resource "aws_cloudwatch_log_group" "amp" {
  name              = "/aws/prometheus/${var.project_name}"
  retention_in_days = var.amp_retention_days

  tags = {
    Name = "${var.project_name}-amp-logs"
  }
}

# ── Alert manager definition (mirrors Phase 4 AlertManager rules) ──────────

resource "aws_prometheus_alert_manager_definition" "main" {
  workspace_id = aws_prometheus_workspace.main.id

  definition = <<-YAML
    alertmanager_config: |
      route:
        receiver: default
        group_by: ['alertname', 'namespace']
        group_wait:      30s
        group_interval:  5m
        repeat_interval: 12h
      receivers:
        - name: default
          sns_configs:
            - topic_arn: ${aws_sns_topic.alerts.arn}
              sigv4:
                region: ${var.aws_region}
              message: |
                {{ range .Alerts }}
                Alert: {{ .Labels.alertname }}
                Description: {{ .Annotations.description }}
                {{ end }}
  YAML
}

# ── Recording + alerting rules (Phase 4 equivalents) ─────────────────────────

resource "aws_prometheus_rule_group_namespace" "five_g_rules" {
  workspace_id = aws_prometheus_workspace.main.id
  name         = "5g-core-rules"

  data = <<-YAML
    groups:
      - name: 5g-core-alerts
        interval: 30s
        rules:

          # CPU saturation on any Open5GS NF
          - alert: NF_CPU_High
            expr: |
              avg by(pod, namespace) (
                rate(container_cpu_usage_seconds_total{namespace="open5gs"}[2m])
              ) > 0.8
            for: 1m
            labels:
              severity: warning
            annotations:
              summary: "High CPU on {{ $labels.pod }}"
              description: "{{ $labels.pod }} CPU > 80% for 1m"

          # UPF pod restarts
          - alert: UPF_PodRestart
            expr: |
              increase(kube_pod_container_status_restarts_total{
                namespace="open5gs", pod=~"open5gs-upf.*"
              }[5m]) > 0
            for: 0m
            labels:
              severity: critical
            annotations:
              summary: "UPF pod restarted"
              description: "{{ $labels.pod }} restarted in the last 5m"

          # HPA at max replicas
          - alert: HPA_MaxReplicas
            expr: |
              kube_horizontalpodautoscaler_status_current_replicas{namespace="open5gs"}
              >= kube_horizontalpodautoscaler_spec_max_replicas{namespace="open5gs"}
            for: 2m
            labels:
              severity: warning
            annotations:
              summary: "HPA at max replicas for {{ $labels.horizontalpodautoscaler }}"
              description: "HPA {{ $labels.horizontalpodautoscaler }} has been at max for 2m"

          # Anomaly detection alert from ML API
          - alert: ML_AnomalyDetected
            expr: |
              ml_serving_anomaly_score > 0.6022
            for: 0m
            labels:
              severity: warning
            annotations:
              summary: "ML anomaly detected (score={{ $value }})"
              description: "IsolationForest score exceeded threshold 0.6022"
  YAML
}

###############################################################################
# SNS topic for alerts
###############################################################################

resource "aws_sns_topic" "alerts" {
  name = "${var.project_name}-alerts"

  tags = { Name = "${var.project_name}-alerts" }
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.grafana_admin_email
}

###############################################################################
# AWS Managed Grafana (AMG)
###############################################################################

resource "aws_grafana_workspace" "main" {
  name                     = "${var.project_name}-amg"
  account_access_type      = "CURRENT_ACCOUNT"
  authentication_providers = ["AWS_SSO"]
  permission_type          = "SERVICE_MANAGED"
  grafana_version          = var.amg_grafana_version
  role_arn                 = aws_iam_role.grafana.arn

  data_sources              = ["PROMETHEUS", "CLOUDWATCH"]
  notification_destinations = ["SNS"]

  tags = {
    Name = "${var.project_name}-amg"
  }
}

# AMG IAM role
data "aws_iam_policy_document" "grafana_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["grafana.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "grafana" {
  name               = "${var.project_name}-grafana-role"
  assume_role_policy = data.aws_iam_policy_document.grafana_assume.json

  tags = { Name = "${var.project_name}-grafana-role" }
}

resource "aws_iam_role_policy" "grafana_amp" {
  name = "${var.project_name}-grafana-amp-access"
  role = aws_iam_role.grafana.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "aps:ListWorkspaces",
          "aps:DescribeWorkspace",
          "aps:QueryMetrics",
          "aps:GetLabels",
          "aps:GetSeries",
          "aps:GetMetricMetadata",
        ]
        Resource = aws_prometheus_workspace.main.arn
      },
      {
        Effect = "Allow"
        Action = [
          "cloudwatch:DescribeAlarmsForMetric",
          "cloudwatch:DescribeAlarmHistory",
          "cloudwatch:DescribeAlarms",
          "cloudwatch:ListMetrics",
          "cloudwatch:GetMetricStatistics",
          "cloudwatch:GetMetricData",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "sns:Publish"
        ]
        Resource = aws_sns_topic.alerts.arn
      }
    ]
  })
}

# ── AMP data source wired to the Grafana workspace ───────────────────────────

resource "aws_grafana_workspace_api_key" "amp_datasource" {
  key_name        = "terraform-datasource-setup"
  key_role        = "ADMIN"
  seconds_to_live = 3600
  workspace_id    = aws_grafana_workspace.main.id
}

###############################################################################
# CloudWatch Container Insights — Helm chart
# Installs the CloudWatch agent + Fluent Bit as a DaemonSet on EKS nodes
###############################################################################

resource "helm_release" "cloudwatch_agent" {
  name       = "amazon-cloudwatch-observability"
  repository = "https://aws.github.io/eks-charts"
  chart      = "amazon-cloudwatch-observability"
  namespace  = "amazon-cloudwatch"
  version    = "1.4.0"

  create_namespace = true

  set {
    name  = "clusterName"
    value = var.cluster_name
  }
  set {
    name  = "region"
    value = var.aws_region
  }

  depends_on = [module.eks]
}
