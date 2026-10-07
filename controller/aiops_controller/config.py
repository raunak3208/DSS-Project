"""Environment-driven settings plus the static service inventory the safety gate trusts (not telemetry)."""
import os


def _env(key, default):
    return type(default)(os.getenv(key, default))


REDIS_URL = _env("REDIS_URL", "redis://redis:6379/0")
KAFKA_BOOTSTRAP = _env("KAFKA_BOOTSTRAP", "kafka:9092")
DB_PATH = _env("DB_PATH", "/data/aiops.db")
BACKEND = _env("EXECUTOR_BACKEND", "docker")            # docker | k8s | sim
K8S_NAMESPACE = _env("K8S_NAMESPACE", "aiops")

# --- agent / verification timing ---------------------------------------------------------------
DEBOUNCE_S = _env("DEBOUNCE_S", 6.0)                    # wait for correlated anomalies before opening an incident
MAX_ITERATIONS = _env("MAX_ITERATIONS", 3)
VERIFY_SETTLE_S = _env("VERIFY_SETTLE_S", 6.0)
VERIFY_POLL_S = _env("VERIFY_POLL_S", 3.0)
VERIFY_TIMEOUT_S = _env("VERIFY_TIMEOUT_S", 45.0)
VERIFY_STREAK = _env("VERIFY_STREAK", 3)
APPROVAL_TIMEOUT_S = _env("APPROVAL_TIMEOUT_S", 300.0)

# --- safety gate policy ------------------------------------------------------------------------
REMEDIATION_MODE = _env("REMEDIATION_MODE", "auto")     # auto | approve_all
AUTO_MAX_RISK = _env("AUTO_MAX_RISK", 2)                # 1 low, 2 medium, 3 high
MIN_CONFIDENCE = _env("MIN_CONFIDENCE", 0.7)
COOLDOWN_S = _env("COOLDOWN_S", 60.0)
MAX_AUTO_PER_10MIN = _env("MAX_AUTO_PER_10MIN", 6)
MAX_REPLICAS = _env("MAX_REPLICAS", 4)

INVENTORY = {
    "gateway": {"critical": True},
    "user-service": {"critical": False},
    "order-service": {"critical": False},
    "payment-service": {"critical": True},
    "notification-service": {"critical": False},
}
STATIC_TOPOLOGY = [("gateway", "user-service"), ("gateway", "order-service"), ("order-service", "user-service"),
                   ("order-service", "payment-service"), ("order-service", "notification-service")]
