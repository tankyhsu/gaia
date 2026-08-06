# Gaia production-like on Kubernetes

This Helm chart deploys the workloads Gaia owns:

- database migration Job
- Temporal namespace and Search Attribute bootstrap Job
- replicated Gaia API Deployment and Service
- replicated Temporal Worker Deployment
- optional developer Console Deployment and Service
- optional Ingress, HPA, PodDisruptionBudget, and NetworkPolicy

PostgreSQL, Redis, Temporal, and Langfuse are independent stateful platforms.
Production environments should operate them through managed services, database
operators, or their upstream charts rather than hiding their lifecycle inside
the Gaia release.

Production defaults disable Console and Ingress. Gaia does not install an
Nginx gateway in production; the customer platform exposes the business API
through its existing Ingress controller, API gateway, service mesh, or private
Service. Demo and documentation surfaces belong only to `dev-full`.

## Complete OrbStack stack

The `stack/` profile deploys the complete topology into OrbStack Kubernetes:

- `gaia-local-dependencies`: local-only PostgreSQL instances for Gaia and
  Temporal, plus Gaia Valkey
- `temporal/temporal` `1.6.0`: Frontend, History, Matching, internal Worker,
  Web UI, schema Jobs, and PostgreSQL persistence
- `langfuse/langfuse` `1.5.41`: Web, Worker, PostgreSQL, Valkey, ClickHouse,
  and MinIO
- `gaia-product-like`: Gaia API, Temporal Worker, Console, migration Job, and
  namespace bootstrap Job

Every application connection uses Kubernetes Service DNS. No workload depends
on Compose, `host.internal`, or a process running on the host.

`GAIA_PROFILE` scopes every namespace. The default `product-like` profile uses
`gaia-product-like`, `temporal-product-like`, `langfuse-product-like`, and
`gaia-platform-product-like`. Another profile can coexist without sharing
Secrets, releases, or state:

```bash
GAIA_PROFILE=staging ./infra/production-like/helm/stack/deploy-orbstack.sh
```

Set the live model credential and deploy:

```bash
export DEEPSEEK_API_KEY='...'
./infra/production-like/helm/stack/deploy-orbstack.sh
```

The deployment ends by running `verify-orbstack.sh`. It asks the HR assistant a
real question, requires a successful DeepSeek invocation, confirms the same Run
completed in Temporal, and loads its Trace from Langfuse.

The model credential is not required to bootstrap the platform. Without
`DEEPSEEK_API_KEY`, the same command deploys PostgreSQL, Valkey, Temporal,
Langfuse, ClickHouse, and MinIO, then stops before the Gaia application release
and live-model verification. Export the credential and rerun the command to
complete the deployment. Missing platform Secrets still fail their owning
release instead of producing a falsely healthy Pod.

Open the three operator surfaces:

```bash
kubectl -n gaia-product-like port-forward \
  svc/gaia-product-like-gaia-production-like-console 4180:80
kubectl -n temporal-product-like port-forward svc/temporal-web 8081:8080
kubectl -n langfuse-product-like port-forward svc/langfuse-web 3001:3000
```

The local dependency Chart and its fixed credentials are acceptance fixtures,
not production defaults. A production values set keeps the four Helm release
boundaries but replaces single-replica local disks with managed services or
HA operators, external Secrets, TLS, backups, and production capacity values.

## External dependencies

- Temporal: use the official `temporalio/helm-charts` chart and external
  persistence.
- Langfuse: use the official `langfuse/langfuse-k8s` chart and external or
  chart-managed PostgreSQL, ClickHouse, Redis, and object storage.
- Gaia PostgreSQL: use a managed PostgreSQL service or your platform's
  PostgreSQL operator.
- Redis is optional for the current production-like controlled-task profile.

Create the namespace and its externally managed Secret before installing Gaia:

```bash
kubectl create namespace gaia
kubectl -n gaia create secret generic gaia-production-like-secrets \
  --from-literal=postgres-url='postgresql://USER:PASSWORD@HOST:5432/gaia' \
  --from-literal=api-key='REPLACE_ME' \
  --from-literal=langfuse-public-key='REPLACE_ME' \
  --from-literal=langfuse-secret-key='REPLACE_ME'
```

Adjust `gaia.config.gaia.runtime.execution.server_address` and
`gaia.config.gaia.observability.base_url`, then deploy:

```bash
helm upgrade --install gaia-production-like \
  ./infra/production-like/helm/gaia \
  --namespace gaia \
  --values ./infra/production-like/helm/gaia/values.yaml \
  --values ./infra/production-like/helm/gaia/values-external.example.yaml \
  --wait \
  --timeout 10m
```

The migration and Temporal bootstrap Jobs are `pre-install`/`pre-upgrade`
hooks. A failed dependency or schema migration stops the release before API
and Worker rollout.

## Gaia-only OrbStack acceptance

Enable Kubernetes in OrbStack and load the locally built images:

```bash
orb config set k8s.enable true
docker build -t gaia-framework:production-like .
docker build -t gaia-console:production-like ./apps/web
```

When the external dependencies already exist, use the single-replica Gaia-only
override:

```bash
helm upgrade --install gaia-production-like \
  ./infra/production-like/helm/gaia \
  --namespace gaia \
  --create-namespace \
  --values ./infra/production-like/helm/gaia/values-orbstack.yaml \
  --wait \
  --timeout 10m
```

Open the Console:

```bash
kubectl -n gaia port-forward \
  svc/gaia-production-like-gaia-production-like-console 4180:80
```

`values-orbstack.yaml` is a local acceptance override, not a production values
file. It disables PDB and NetworkPolicy and uses one replica per workload.
