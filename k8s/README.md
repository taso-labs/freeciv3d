# FreeCiv3D Kubernetes Manifests

Kubernetes manifests for deploying FreeCiv3D to GKE using Kustomize.

## Architecture

**Monolithic deployment**: The `fciv-net` container runs all services:

- Tomcat webapp (freeciv-web) on port 8080
- FreeCiv proxy for LLM on port 8002
- LLM Gateway API on port 8003
- Per-game proxies (7001-7009) managed by publite2

## Directory Structure

```text
k8s/
├── base/                    # Base manifests
│   ├── namespace.yaml       # freeciv namespace
│   ├── kustomization.yaml   # Kustomize base config
│   ├── fciv-net/            # FreeCiv Network service
│   │   ├── deployment.yaml  # Main container with Cloud SQL Proxy sidecar
│   │   ├── service.yaml     # ClusterIP service (8080, 8002, 8003)
│   │   ├── configmap.yaml   # Configuration
│   │   └── hpa.yaml         # Horizontal Pod Autoscaler
│   ├── redis/               # Redis cache
│   ├── rbac/                # Service accounts with Workload Identity
│   ├── network-policies/    # Network security policies
│   ├── pdb.yaml             # Pod Disruption Budget
│   ├── resource-quota.yaml  # Resource quotas
│   └── external-secrets.yaml # External Secrets for GCP Secret Manager
├── overlays/
│   ├── staging/             # Staging environment patches
│   └── production/          # Production environment patches
└── README.md
```

## Services

### fciv-net

- **Purpose**: FreeCiv 3D game server (Tomcat, proxies, LLM gateway)
- **Ports**:
  - 8080: Tomcat webapp (freeciv-web)
  - 8002: FreeCiv proxy for LLM Gateway
  - 8003: LLM Gateway API
- **Type**: ClusterIP (internal only)
- **Scaling**: HPA with configurable replicas

### redis

- **Purpose**: Session cache and rate limiting
- **Port**: 6379
- **Type**: ClusterIP

## Deployment

### Using Kustomize

```bash
# Preview staging manifests
kubectl kustomize k8s/overlays/staging

# Apply to staging
kubectl apply -k k8s/overlays/staging

# Apply to production
kubectl apply -k k8s/overlays/production
```

### Verify Deployment

```bash
# Check deployments
kubectl get deployments -n freeciv

# Check pods (expect 2/2 containers: fciv-net + cloud-sql-proxy)
kubectl get pods -n freeciv

# Check services
kubectl get services -n freeciv

# Check logs
kubectl logs -n freeciv -l app=fciv-net -c fciv-net --tail=100
```

## Integration with LLM Agent Clients

FreeCiv3D services are accessed internally by LLM agent clients via Kubernetes DNS:

- `fciv-net.freeciv.svc.cluster.local:8080` - Web interface
- `fciv-net.freeciv.svc.cluster.local:8002` - FreeCiv proxy
- `fciv-net.freeciv.svc.cluster.local:8003` - LLM Gateway API

## CI/CD

Deployment is automated via GitHub Actions:

1. `build-docker.yml` - Builds and pushes to staging registry on release
2. `deploy-staging.yml` - Deploys to staging after build succeeds
3. `deploy-production.yml` - Promotes image to production on release publish

## Security Notes

- All services use **ClusterIP** (not LoadBalancer) - internal only
- Network policies restrict traffic to allowed namespaces
- Workload Identity Federation used for GCP authentication
- Cloud SQL Proxy sidecar handles secure database connections
- TODO: Refactor container to run as non-root (currently requires sudo)
