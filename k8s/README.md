# FreeCiv3D Kubernetes Manifests

This directory contains Kubernetes manifests for deploying FreeCiv3D services to GKE.

## Directory Structure

```
k8s/
├── llm-gateway/        # LLM Gateway service (port 8003)
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── hpa.yaml
│   └── configmap.yaml
├── fciv-net/           # FreeCiv Network service (port 5556)
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── hpa.yaml
│   └── configmap.yaml
├── rbac/               # Service accounts with Workload Identity
│   ├── llm-gateway-sa.yaml
│   └── fciv-net-sa.yaml
├── mariadb/            # MariaDB (placeholder - not yet implemented)
├── nginx/              # Nginx (placeholder - not yet implemented)
├── redis/              # Redis (placeholder - not yet implemented)
└── secrets/            # External Secrets Operator config (placeholder)
```

## Services

### LLM Gateway
- **Purpose**: AI/LLM integration gateway for FreeCiv agents
- **Port**: 8003
- **Type**: ClusterIP (internal only)
- **Scaling**: HPA with 1-4 replicas
- **Resources**: 200m-500m CPU, 256Mi-512Mi memory

### FreeCiv Network (fciv-net)
- **Purpose**: FreeCiv game server network interface
- **Port**: 5556
- **Type**: ClusterIP (internal only)
- **Scaling**: HPA with 1-4 replicas
- **Resources**: 200m-500m CPU, 256Mi-512Mi memory

## Deployment

### Prerequisites
- GKE cluster configured with Workload Identity
- Namespace `freeciv3d` created
- External Secrets Operator installed (for secrets)

### Apply Manifests

```bash
# Create namespace (if not exists)
kubectl apply -f ../k8s/namespaces/freeciv3d-namespace.yaml

# Apply RBAC (service accounts)
kubectl apply -f rbac/

# Apply ConfigMaps
kubectl apply -f llm-gateway/configmap.yaml
kubectl apply -f fciv-net/configmap.yaml

# Apply Services
kubectl apply -f llm-gateway/service.yaml
kubectl apply -f fciv-net/service.yaml

# Apply Deployments
kubectl apply -f llm-gateway/deployment.yaml
kubectl apply -f fciv-net/deployment.yaml

# Apply HPAs
kubectl apply -f llm-gateway/hpa.yaml
kubectl apply -f fciv-net/hpa.yaml
```

### Verify Deployment

```bash
# Check deployments
kubectl get deployments -n freeciv3d

# Check pods
kubectl get pods -n freeciv3d

# Check services
kubectl get services -n freeciv3d

# Check logs
kubectl logs -n freeciv3d -l app=llm-gateway --tail=100
kubectl logs -n freeciv3d -l app=fciv-net --tail=100
```

## Integration with AgentClash

FreeCiv3D services are accessed internally by the AgentClash `freeciv-gateway` service via Kubernetes DNS:

- `llm-gateway.freeciv3d.svc.cluster.local:8003`
- `fciv-net.freeciv3d.svc.cluster.local:5556`

## CI/CD

FreeCiv3D services should have their own deployment workflow in this repository. See `.github/workflows/` for CI/CD pipelines.

## Notes

- All services use **ClusterIP** (not LoadBalancer) - they are internal only
- External access is routed through `freeciv-gateway` in the `agent-clash` namespace
- Workload Identity Federation is used for GCP authentication (no service account keys)
- Resources are auto-scaled based on CPU utilization via HPA
