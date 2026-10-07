#!/usr/bin/env python3
"""Generates k8s/*.yaml. Run `python scripts/gen_k8s.py` after editing; the generated files are committed."""
import os, textwrap

OUT = os.path.join(os.path.dirname(__file__), "..", "k8s")
NS = "aiops"
SERVICES = ["gateway", "user-service", "order-service", "payment-service", "notification-service"]
ENV = """\
            - {name: KAFKA_BOOTSTRAP, value: "kafka:9092"}
            - {name: REDIS_URL, value: "redis://redis:6379/0"}
            - {name: MEM_LIMIT_MB, value: "256"}"""


def w(name, text):
    with open(os.path.join(OUT, name), "w") as f:
        f.write(textwrap.dedent(text).lstrip())


def deploy(name, image, port=None, env="", cmd="", extra="", sa=""):
    ports = f"\n          ports: [{{containerPort: {port}}}]" if port else ""
    svc = f"""---
apiVersion: v1
kind: Service
metadata: {{name: {name}, namespace: {NS}}}
spec:
  selector: {{app: {name}}}
  ports: [{{port: {port}, targetPort: {port}}}]
""" if port else ""
    return f"""---
apiVersion: apps/v1
kind: Deployment
metadata: {{name: {name}, namespace: {NS}, labels: {{app: {name}}}}}
spec:
  replicas: 1
  selector: {{matchLabels: {{app: {name}}}}}
  template:
    metadata: {{labels: {{app: {name}}}}}
    spec:{sa}
      containers:
        - name: {name}
          image: {image}
          imagePullPolicy: IfNotPresent{cmd}{ports}
          env:
{env}
          resources: {{limits: {{memory: 384Mi}}}}{extra}
{svc}"""


w("00-namespace.yaml", f"apiVersion: v1\nkind: Namespace\nmetadata: {{name: {NS}}}\n")

w("10-infra.yaml", f"""\
---
apiVersion: apps/v1
kind: Deployment
metadata: {{name: redis, namespace: {NS}}}
spec:
  replicas: 1
  selector: {{matchLabels: {{app: redis}}}}
  template:
    metadata: {{labels: {{app: redis}}}}
    spec:
      containers:
        - {{name: redis, image: "redis:7-alpine", ports: [{{containerPort: 6379}}]}}
---
apiVersion: v1
kind: Service
metadata: {{name: redis, namespace: {NS}}}
spec: {{selector: {{app: redis}}, ports: [{{port: 6379}}]}}
---
apiVersion: apps/v1
kind: Deployment
metadata: {{name: kafka, namespace: {NS}}}
spec:
  replicas: 1
  selector: {{matchLabels: {{app: kafka}}}}
  template:
    metadata: {{labels: {{app: kafka}}}}
    spec:
      containers:
        - name: kafka
          image: apache/kafka:3.8.0
          ports: [{{containerPort: 9092}}]
          env:
            - {{name: KAFKA_NODE_ID, value: "1"}}
            - {{name: KAFKA_PROCESS_ROLES, value: "broker,controller"}}
            - {{name: KAFKA_LISTENERS, value: "PLAINTEXT://:9092,CONTROLLER://:9093"}}
            - {{name: KAFKA_ADVERTISED_LISTENERS, value: "PLAINTEXT://kafka:9092"}}
            - {{name: KAFKA_CONTROLLER_LISTENER_NAMES, value: CONTROLLER}}
            - {{name: KAFKA_LISTENER_SECURITY_PROTOCOL_MAP, value: "CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT"}}
            - {{name: KAFKA_CONTROLLER_QUORUM_VOTERS, value: "1@localhost:9093"}}
            - {{name: KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR, value: "1"}}
            - {{name: KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR, value: "1"}}
            - {{name: KAFKA_TRANSACTION_STATE_LOG_MIN_ISR, value: "1"}}
            - {{name: KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS, value: "0"}}
          readinessProbe: {{tcpSocket: {{port: 9092}}, initialDelaySeconds: 15, periodSeconds: 5}}
---
apiVersion: v1
kind: Service
metadata: {{name: kafka, namespace: {NS}}}
spec: {{selector: {{app: kafka}}, ports: [{{port: 9092}}]}}
""")

apps = "".join(deploy(s, "aiops/svc:latest", 8000, ENV + f'\n            - {{name: SERVICE_NAME, value: "{s}"}}') for s in SERVICES)
apps += deploy("loadgen", "aiops/svc:latest", None,
               '            - {name: TARGET, value: "http://gateway:8000"}\n            - {name: LOAD_RPS, value: "6"}',
               cmd='\n          command: ["python", "/app/loadgen.py"]')
apps += deploy("processor", "aiops/processor:latest", None, ENV)
w("20-apps.yaml", apps)

ctrl_env = ENV + """
            - {name: EXECUTOR_BACKEND, value: "k8s"}
            - {name: K8S_NAMESPACE, value: "aiops"}
            - {name: DB_PATH, value: "/data/aiops.db"}
            - {name: REMEDIATION_MODE, value: "auto"}
            - {name: LLM_PROVIDER, value: "mistral"}
            - {name: MISTRAL_API_KEY, valueFrom: {secretKeyRef: {name: aiops-llm, key: MISTRAL_API_KEY, optional: true}}}"""
w("30-controller.yaml", f"""\
---
apiVersion: v1
kind: ServiceAccount
metadata: {{name: aiops-controller, namespace: {NS}}}
---
# The only cluster permissions the remediation executor has: list/delete pods, patch/scale deployments in this namespace.
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata: {{name: aiops-remediator, namespace: {NS}}}
rules:
  - {{apiGroups: [""], resources: [pods], verbs: [get, list, delete]}}
  - {{apiGroups: [apps], resources: [deployments], verbs: [get, list, patch]}}
  - {{apiGroups: [apps], resources: [deployments/scale], verbs: [get, patch]}}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata: {{name: aiops-remediator, namespace: {NS}}}
subjects: [{{kind: ServiceAccount, name: aiops-controller, namespace: {NS}}}]
roleRef: {{kind: Role, name: aiops-remediator, apiGroup: rbac.authorization.k8s.io}}
""" + deploy("controller", "aiops/controller:latest", 8080, ctrl_env, sa="\n      serviceAccountName: aiops-controller",
             extra="""
          volumeMounts: [{name: data, mountPath: /data}]
      volumes: [{name: data, emptyDir: {}}]""").replace("        - name: controller\n", "        - name: controller\n", 1)
  )
# uvicorn command for the controller image is the Dockerfile CMD; dashboard below
w("40-dashboard.yaml", deploy("dashboard", "aiops/dashboard:latest", 80).replace(
    "ports: [{port: 80, targetPort: 80}]", "type: NodePort\n  ports: [{port: 80, targetPort: 80, nodePort: 30080}]"))

w("50-prometheus.yaml", f"""\
---
apiVersion: v1
kind: ConfigMap
metadata: {{name: prometheus-config, namespace: {NS}}}
data:
  prometheus.yml: |
    global: {{scrape_interval: 5s}}
    scrape_configs:
      - job_name: services
        static_configs:
          - targets: [{", ".join(f'"{s}:8000"' for s in SERVICES)}]
---
apiVersion: apps/v1
kind: Deployment
metadata: {{name: prometheus, namespace: {NS}}}
spec:
  replicas: 1
  selector: {{matchLabels: {{app: prometheus}}}}
  template:
    metadata: {{labels: {{app: prometheus}}}}
    spec:
      containers:
        - name: prometheus
          image: prom/prometheus:v2.54.1
          ports: [{{containerPort: 9090}}]
          volumeMounts: [{{name: cfg, mountPath: /etc/prometheus}}]
      volumes: [{{name: cfg, configMap: {{name: prometheus-config}}}}]
---
apiVersion: v1
kind: Service
metadata: {{name: prometheus, namespace: {NS}}}
spec: {{selector: {{app: prometheus}}, ports: [{{port: 9090}}]}}
""")
print("generated:", sorted(os.listdir(OUT)))
