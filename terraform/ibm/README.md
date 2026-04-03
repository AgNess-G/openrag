# OpenRAG — IBM Cloud Terraform

Deploys the full OpenRAG stack on IBM Cloud:

| Resource | IBM Service |
|---|---|
| Kubernetes | IKS VPC cluster |
| Redis | IBM Databases for Redis |
| Object Storage | IBM Cloud Object Storage |
| Container Registry | IBM Container Registry |
| Autoscaling | KEDA ScaledJob |
| Networking | VPC + Public Gateway |

## Architecture

```
Internet
  │
  ▼
VPC Load Balancer (public IP)
  │
  ▼
openrag-frontend (2 pods)  ──►  openrag-backend (2 pods)
                                  │
                          ┌───────┴────────┐
                          ▼                ▼
                    OpenSearch        IBM Databases
                  (StatefulSet)       for Redis
                                          │
                                    KEDA polls queue
                                          │
                                          ▼
                                 pipeline-worker Jobs
                                 (0 → 20, spot nodes)
```

## Prerequisites

```bash
# IBM Cloud CLI
brew install --cask ibm-cloud-cli
ibmcloud plugin install container-service
ibmcloud plugin install container-registry
ibmcloud plugin install vpc-infrastructure

# Terraform
brew install terraform

# Login
ibmcloud login --apikey YOUR_API_KEY -r us-south
```

## Quick start

```bash
# 1. Create resource group
ibmcloud resource group-create openrag-rg

# 2. Configure variables
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your values

# 3. Push images to IBM Container Registry
ibmcloud cr login
podman tag langflowai/openrag-backend:latest us.icr.io/openrag/openrag-backend:latest
podman tag langflowai/openrag-frontend:latest us.icr.io/openrag/openrag-frontend:latest
podman push us.icr.io/openrag/openrag-backend:latest
podman push us.icr.io/openrag/openrag-frontend:latest

# 4. Deploy
terraform init
terraform plan
terraform apply

# 5. Access the UI
terraform output frontend_url

# 6. Configure kubectl
$(terraform output -raw kubeconfig_command)
```

## Verify deployment

```bash
# All pods running
kubectl get pods -n openrag

# KEDA ScaledJob ready
kubectl get scaledjob -n openrag

# Queue depth (should be 0 at rest)
REDIS_HOST=$(terraform output -raw redis_host)
# Use redis-cli or kubectl exec into a pod to check

# Watch workers spawn during ingestion
kubectl get jobs -n openrag -w
kubectl get pods -n openrag -l app=openrag-pipeline-worker -w
```

## Scaling

KEDA spawns one Job per `worker_target_queue_length` items in the queue, up to `worker_max_replicas`. Workers run on the `pipeline-spot` worker pool.

Tune in `terraform.tfvars`:
```hcl
worker_max_replicas        = 20   # hard ceiling on concurrent Jobs
worker_target_queue_length = 5    # files per Job
```

## Cost optimisation

- Workers run on the `pipeline-spot` worker pool (add spot/preemptible label to the pool in IKS console)
- `minReplicaCount` is implicitly 0 — no idle worker cost
- IBM Databases for Redis `standard` plan: ~$45/month for 1GB
- IKS worker nodes: only pay for what runs; pipeline pool starts at 0

## Teardown

```bash
terraform destroy
```

> **Note:** The IKS cluster, IBM Databases for Redis, and COS bucket will be deleted. Make sure to export any data first.
