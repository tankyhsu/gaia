#!/usr/bin/env bash
set -euo pipefail

STACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GAIA_ROOT="$(cd "$STACK_DIR/../../../.." && pwd)"
WORKSPACE_ROOT="$(cd "$GAIA_ROOT/.." && pwd)"

TEMPORAL_CHART_VERSION="1.6.0"
LANGFUSE_CHART_VERSION="1.5.41"
GAIA_PROFILE="${GAIA_PROFILE:-product-like}"

if [[ ! "$GAIA_PROFILE" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]]; then
  echo "GAIA_PROFILE must be a Kubernetes-compatible DNS label." >&2
  exit 1
fi

platform_namespace="gaia-platform-$GAIA_PROFILE"
temporal_namespace="temporal-$GAIA_PROFILE"
langfuse_namespace="langfuse-$GAIA_PROFILE"
gaia_namespace="gaia-$GAIA_PROFILE"
gaia_release="gaia-$GAIA_PROFILE"
temporal_workflow_namespace="gaia-$GAIA_PROFILE"
temporal_task_queue="gaia-hr-$GAIA_PROFILE"

for command in docker helm kubectl openssl; do
  command -v "$command" >/dev/null || {
    echo "Missing required command: $command" >&2
    exit 1
  }
done

if [[ "$(kubectl config current-context)" != "orbstack" ]]; then
  echo "Refusing to deploy local credentials outside the orbstack context." >&2
  exit 1
fi

apply_secret() {
  local namespace="$1"
  local name="$2"
  shift 2
  kubectl -n "$namespace" create secret generic "$name" "$@" \
    --dry-run=client -o yaml | kubectl apply -f -
}

for namespace in \
  "$platform_namespace" \
  "$temporal_namespace" \
  "$langfuse_namespace" \
  "$gaia_namespace"; do
  kubectl create namespace "$namespace" --dry-run=client -o yaml | kubectl apply -f -
done

apply_secret "$platform_namespace" platform-data-auth \
  --from-literal=temporal-postgres-password=temporal-local-password \
  --from-literal=gaia-postgres-password=gaia-local-postgres \
  --from-literal=redis-password=gaia-local-redis
apply_secret "$temporal_namespace" temporal-postgres-auth \
  --from-literal=password=temporal-local-password

apply_secret "$langfuse_namespace" langfuse-core-secrets \
  --from-literal=salt=local-langfuse-salt-32-bytes-value \
  --from-literal=encryption-key=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef \
  --from-literal=nextauth-secret=local-nextauth-secret-32-bytes-value
apply_secret "$langfuse_namespace" langfuse-postgres-auth \
  --from-literal=password=langfuse-local-postgres
apply_secret "$langfuse_namespace" langfuse-valkey-auth \
  --from-literal=password=langfuse-local-valkey
apply_secret "$langfuse_namespace" langfuse-clickhouse-auth \
  --from-literal=password=langfuse-local-clickhouse
apply_secret "$langfuse_namespace" langfuse-minio-auth \
  --from-literal=root-user=minio \
  --from-literal=root-password=langfuse-local-minio-secret
apply_secret "$langfuse_namespace" langfuse-bootstrap \
  --from-literal=LANGFUSE_INIT_ORG_ID=gaia-local-org \
  --from-literal=LANGFUSE_INIT_ORG_NAME="Gaia Local" \
  --from-literal=LANGFUSE_INIT_PROJECT_ID=gaia-local-project \
  --from-literal=LANGFUSE_INIT_PROJECT_NAME="Gaia Product Like" \
  --from-literal=LANGFUSE_INIT_PROJECT_PUBLIC_KEY=pk-lf-gaia-local \
  --from-literal=LANGFUSE_INIT_PROJECT_SECRET_KEY=sk-lf-gaia-local \
  --from-literal=LANGFUSE_INIT_USER_EMAIL=gaia@example.local \
  --from-literal=LANGFUSE_INIT_USER_NAME="Gaia Operator" \
  --from-literal=LANGFUSE_INIT_USER_PASSWORD='GaiaLocal123!'

helm repo add temporal https://go.temporal.io/helm-charts/ --force-update
helm repo add langfuse https://langfuse.github.io/langfuse-k8s --force-update
helm repo update temporal langfuse

helm upgrade --install gaia-local-dependencies \
  "$STACK_DIR/local-dependencies" \
  --namespace "$platform_namespace" \
  --wait \
  --timeout 10m

helm upgrade --install temporal temporal/temporal \
  --version "$TEMPORAL_CHART_VERSION" \
  --namespace "$temporal_namespace" \
  --values "$STACK_DIR/temporal-values-orbstack.yaml" \
  --set-string \
  "server.config.persistence.datastores.default.sql.connectAddr=temporal-postgres.$platform_namespace.svc.cluster.local:5432" \
  --set-string \
  "server.config.persistence.datastores.visibility.sql.connectAddr=temporal-postgres.$platform_namespace.svc.cluster.local:5432" \
  --wait \
  --timeout 15m

helm upgrade --install langfuse langfuse/langfuse \
  --version "$LANGFUSE_CHART_VERSION" \
  --namespace "$langfuse_namespace" \
  --values "$STACK_DIR/langfuse-values-orbstack.yaml" \
  --wait \
  --timeout 20m

# The MinIO subchart omits ``spec.replicas`` for its standalone Deployment.
# After operators scale the local stack to zero, Helm's three-way merge keeps
# that live value and incorrectly considers 0/0 ready. Restore the one local
# replica explicitly so OTLP ingestion has object storage before verification.
kubectl scale deployment/langfuse-s3 \
  --namespace "$langfuse_namespace" \
  --replicas=1
kubectl rollout status deployment/langfuse-s3 \
  --namespace "$langfuse_namespace" \
  --timeout=10m

if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
  cat <<'EOF'
Platform deployment is ready: data services, Temporal, and Langfuse are running.
Gaia and the live-model verification were skipped because DEEPSEEK_API_KEY is
not set. Export the key and run this command again to deploy the application.
EOF
  exit 0
fi

apply_secret "$gaia_namespace" gaia-production-like-secrets \
  --from-literal=postgres-url="postgresql://gaia:gaia-local-postgres@gaia-postgres.$platform_namespace.svc.cluster.local:5432/gaia" \
  --from-literal=redis-url="redis://:gaia-local-redis@gaia-redis.$platform_namespace.svc.cluster.local:6379/0" \
  --from-literal=api-key=gaia-local-api-key \
  --from-literal=langfuse-public-key=pk-lf-gaia-local \
  --from-literal=langfuse-secret-key=sk-lf-gaia-local \
  --from-literal=deepseek-api-key="$DEEPSEEK_API_KEY"

docker build -t gaia-framework:production-like "$GAIA_ROOT"
docker build -t gaia-console:production-like "$GAIA_ROOT/apps/web"
docker build -t gaia-framework:product-like-hr \
  -f "$STACK_DIR/Dockerfile.hr" "$WORKSPACE_ROOT"

gaia_secret_resource_version="$(
  kubectl get secret -n "$gaia_namespace" gaia-production-like-secrets \
    -o jsonpath='{.metadata.resourceVersion}'
)"
helm upgrade --install "$gaia_release" "$GAIA_ROOT/infra/production-like/helm/gaia" \
  --namespace "$gaia_namespace" \
  --values "$GAIA_ROOT/infra/production-like/helm/gaia/values-orbstack.yaml" \
  --values "$STACK_DIR/gaia-values-orbstack.yaml" \
  --set-string "gaia.config.gaia.profile=$GAIA_PROFILE" \
  --set-string \
  "gaia.config.gaia.runtime.execution.server_address=temporal-frontend.$temporal_namespace.svc.cluster.local:7233" \
  --set-string \
  "gaia.config.gaia.runtime.execution.namespace=$temporal_workflow_namespace" \
  --set-string \
  "gaia.config.gaia.runtime.execution.task_queue=$temporal_task_queue" \
  --set-string \
  "gaia.config.gaia.observability.base_url=http://langfuse-web.$langfuse_namespace.svc.cluster.local:3000" \
  --set-string "gaia.config.gaia.observability.environment=$GAIA_PROFILE" \
  --set-string \
  "podAnnotations.gaia-secret-resource-version=$gaia_secret_resource_version" \
  --wait \
  --timeout 10m

GAIA_PROFILE="$GAIA_PROFILE" "$STACK_DIR/verify-orbstack.sh"
