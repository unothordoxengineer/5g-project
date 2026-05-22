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
# Self-managed Grafana on EKS (Helm) — mirrors local Phase-4 setup
# AWS Managed Grafana (AMG) requires SSO which is not available on this account.
###############################################################################

resource "helm_release" "grafana" {
  name             = "grafana"
  repository       = "https://grafana.github.io/helm-charts"
  chart            = "grafana"
  namespace        = "monitoring"
  version          = "7.3.9"
  create_namespace = true

  set {
    name  = "adminPassword"
    value = "admin"   # Override via values file or Secrets Manager in production
  }

  # AMP remote-read data source wired automatically
  set {
    name  = "datasources.datasources\\.yaml.apiVersion"
    value = "1"
  }
  set {
    name  = "datasources.datasources\\.yaml.datasources[0].name"
    value = "AMP"
  }
  set {
    name  = "datasources.datasources\\.yaml.datasources[0].type"
    value = "prometheus"
  }
  set {
    name  = "datasources.datasources\\.yaml.datasources[0].url"
    value = aws_prometheus_workspace.main.prometheus_endpoint
  }
  set {
    name  = "datasources.datasources\\.yaml.datasources[0].isDefault"
    value = "true"
  }
  set {
    name  = "service.type"
    value = "ClusterIP"
  }

  depends_on = [module.eks]
}

# CloudWatch Container Insights helm chart commented out.
# Chart "amazon-cloudwatch-observability" was removed from eks-charts repo.
# Install manually after cluster is up:
#   aws eks create-addon --cluster-name <cluster> --addon-name amazon-cloudwatch-observability
# Or use the CloudWatch agent DaemonSet from:
#   https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Container-Insights-setup-EKS-quickstart.html
