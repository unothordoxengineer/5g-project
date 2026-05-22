"""
config.py — NEF service configuration (env-driven, AWS-ready).

Local defaults match the KinD cluster.  On EKS the same env vars are injected
via Kubernetes Secrets / AWS Parameter Store (see terraform/nef.tf).
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── Service identity ───────────────────────────────────────────────────
    service_name: str = "5G-NEF"
    version: str = "1.0.0"
    environment: str = "local"           # local | staging | production

    # ── JWT / Auth ─────────────────────────────────────────────────────────
    # Local: symmetric HMAC-256 secret.
    # AWS:   set JWT_SECRET to a Secrets Manager ARN and swap auth.py logic
    #        to decode Cognito RS256 tokens using the JWKS endpoint instead.
    jwt_secret: str = "change-me-in-production-use-aws-secrets-manager"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # Cognito config — unused locally, populated by Terraform on AWS
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""
    cognito_region: str = "us-east-1"
    # If set, validate RS256 Cognito tokens instead of local HS256
    cognito_jwks_url: str = ""

    # ── Rate limiting ──────────────────────────────────────────────────────
    rate_limit_per_minute: int = 100   # maps to API Gateway throttle on AWS

    # ── Open5GS internal endpoints ─────────────────────────────────────────
    # Local KinD: plain ClusterIP service names
    mongodb_uri: str = "mongodb://mongodb.open5gs.svc.cluster.local:27017/open5gs"
    amf_sbi_url: str = "http://amf.open5gs.svc.cluster.local:80"
    pcf_sbi_url: str = "http://pcf.open5gs.svc.cluster.local:80"
    smf_sbi_url: str = "http://smf.open5gs.svc.cluster.local:80"

    # ── Webhook delivery ──────────────────────────────────────────────────
    webhook_timeout_s: int = 5
    webhook_max_retries: int = 3

    # ── Observability ─────────────────────────────────────────────────────
    log_level: str = "INFO"
    metrics_enabled: bool = True

    class Config:
        env_prefix = "NEF_"
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
