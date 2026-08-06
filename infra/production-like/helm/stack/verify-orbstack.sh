#!/usr/bin/env bash
set -euo pipefail

for command in curl jq kubectl; do
  command -v "$command" >/dev/null || {
    echo "Missing required command: $command" >&2
    exit 1
  }
done

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

for namespace in \
  "$platform_namespace" \
  "$temporal_namespace" \
  "$langfuse_namespace" \
  "$gaia_namespace"; do
  kubectl wait --for=condition=Ready pod --all \
    --namespace "$namespace" \
    --timeout=10m
done

admin_pod="$(
  kubectl get pod -n "$temporal_namespace" \
    -l app.kubernetes.io/component=admintools \
    -o jsonpath='{.items[0].metadata.name}'
)"
namespace_ready=false
for _ in $(seq 1 60); do
  if kubectl exec -n "$temporal_namespace" "$admin_pod" -- \
    temporal operator namespace describe \
    --namespace "$temporal_workflow_namespace" >/dev/null 2>&1; then
    namespace_ready=true
    break
  fi
  sleep 2
done
if [[ "$namespace_ready" != true ]]; then
  echo "Temporal namespace $temporal_workflow_namespace did not become queryable." >&2
  exit 1
fi

if kubectl get configmap --namespace "$gaia_namespace" -o yaml |
  grep -E 'host\.internal|localhost:[0-9]'; then
  echo "Gaia contains a host-only dependency instead of cluster DNS." >&2
  exit 1
fi

api_port="${GAIA_VERIFY_API_PORT:-18182}"
langfuse_port="${GAIA_VERIFY_LANGFUSE_PORT:-13002}"
kubectl -n "$gaia_namespace" port-forward \
  "svc/$gaia_release-gaia-production-like-api" "$api_port:8000" \
  >/tmp/gaia-product-like-api-port-forward.log 2>&1 &
api_forward_pid=$!
kubectl -n "$langfuse_namespace" port-forward \
  svc/langfuse-web "$langfuse_port:3000" \
  >/tmp/gaia-product-like-langfuse-port-forward.log 2>&1 &
langfuse_forward_pid=$!
trap 'kill "$api_forward_pid" "$langfuse_forward_pid" 2>/dev/null || true' EXIT

for _ in $(seq 1 60); do
  if curl --fail --silent "http://127.0.0.1:$api_port/health/ready" >/dev/null &&
    curl --fail --silent "http://127.0.0.1:$langfuse_port/api/public/health" >/dev/null; then
    break
  fi
  sleep 1
done

idempotency_key="orbstack-live-$(date +%s)"
run_request='{
  "scenario_id": "hr.handbook.answer",
  "mode": "sandbox",
  "user": {
    "id": "E-1042",
    "organization": "gaia-local-org",
    "roles": ["employee"]
  },
  "request": {
    "text": "我今年有几天年假？",
    "metadata": {"employee_id": "E-1042"}
  }
}'

snapshot=""
for _ in $(seq 1 30); do
  if snapshot="$(
    curl --fail --silent \
      --request POST "http://127.0.0.1:$api_port/v1/runs" \
      --header 'Content-Type: application/json' \
      --header 'X-Gaia-Api-Key: gaia-local-api-key' \
      --header "Idempotency-Key: $idempotency_key" \
      --data "$run_request"
  )"; then
    break
  fi
  sleep 2
done
if [[ -z "$snapshot" ]]; then
  echo "Gaia did not accept a Run after Temporal became queryable." >&2
  exit 1
fi
run_id="$(jq -r '.run_id' <<<"$snapshot")"

for _ in $(seq 1 90); do
  snapshot="$(
    curl --fail --silent \
      --header 'X-Gaia-Api-Key: gaia-local-api-key' \
      "http://127.0.0.1:$api_port/v1/runs/$run_id"
  )"
  status="$(jq -r '.status' <<<"$snapshot")"
  case "$status" in
    succeeded) break ;;
    failed | blocked | cancelled)
      jq . <<<"$snapshot"
      exit 1
      ;;
  esac
  sleep 2
done

jq -e '
  .status == "succeeded" and
  .result.model_stage.model_id == "deepseek-chat" and
  .trace_id != null
' <<<"$snapshot" >/dev/null
trace_id="$(jq -r '.trace_id' <<<"$snapshot")"

workflow_description="$(
kubectl exec -n "$temporal_namespace" "$admin_pod" -- \
    temporal workflow describe \
    --namespace "$temporal_workflow_namespace" \
    --workflow-id "$run_id"
)"
grep -q 'Status.*COMPLETED' <<<"$workflow_description"

trace_verified=false
for _ in $(seq 1 60); do
  if curl --fail --silent \
    --user 'pk-lf-gaia-local:sk-lf-gaia-local' \
    "http://127.0.0.1:$langfuse_port/api/public/traces/$trace_id" |
    jq -e --arg trace_id "$trace_id" \
      --arg environment "$GAIA_PROFILE" \
      '.id == $trace_id and .environment == $environment' >/dev/null; then
    trace_verified=true
    break
  fi
  sleep 2
done
if [[ "$trace_verified" != true ]]; then
  echo "Langfuse did not expose Trace $trace_id before the timeout." >&2
  exit 1
fi

echo "Verified complete Kubernetes stack"
echo "Run: $run_id"
echo "Trace: $trace_id"
echo "Model: $(jq -r '.result.model_stage.model_id' <<<"$snapshot")"
