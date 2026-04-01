# Ray Deployment Guide for OpenRAG

This guide covers three deployment paths for the composable ingestion pipeline with Ray as the execution backend.

---

## Path 1: Docker Compose (Single Server / VM)

Best for: Up to ~100K documents on a single machine.

### Start with Ray

```bash
# Start all services including Ray head + workers
docker compose --profile ray up -d

# Scale workers for more throughput
docker compose --profile ray up -d --scale ray-worker=4
```

### Configure the pipeline

Edit `config/pipeline.yaml`:

```yaml
ingestion_mode: composable
execution:
  backend: ray
  ray:
    address: ray://ray-head:10001
```

Or set environment variables in `.env`:

```
RAY_ADDRESS=ray://ray-head:10001
PIPELINE_EXECUTION_BACKEND=ray
```

### Monitor

- Ray Dashboard: http://localhost:8265
- View active tasks, cluster resources, and logs.

### Without Ray (default)

```bash
# Standard startup — Ray services are NOT started
docker compose up -d
```

---

## Path 2: IBM Cloud Kubernetes Service (IKS) + KubeRay

Best for: 1M+ documents, production workloads requiring autoscaling.

### 1. Create IKS Cluster

```bash
ibmcloud ks cluster create vpc-gen2 \
  --name openrag-cluster \
  --zone us-south-1 \
  --flavor bx2.8x32 \
  --workers 4
```

Optional GPU worker pool:

```bash
ibmcloud ks worker-pool create vpc-gen2 \
  --name gpu-pool \
  --cluster openrag-cluster \
  --flavor gx3.16x80x1v100 \
  --size-per-zone 2
```

### 2. Install KubeRay Operator

```bash
helm repo add kuberay https://ray-project.github.io/kuberay-helm/
helm install kuberay-operator kuberay/kuberay-operator
```

### 3. Deploy Ray Cluster

```bash
kubectl apply -f kubernetes/ray/ray-cluster.yaml
```

### 4. Deploy OpenRAG with Ray

```bash
helm install openrag ./charts/openrag \
  -f kubernetes/ray/values-ray.yaml \
  --set opensearch.password=$OPENSEARCH_PASSWORD
```

### Notes

- Use IBM Cloud Ingress to expose the Ray Dashboard externally.
- Use IBM Block Storage CSI driver for OpenSearch persistent volumes.
- Worker autoscaling is handled by KubeRay based on pending tasks.

---

## Path 3: IBM Code Engine (Serverless)

Best for: Bursty workloads, pay-per-use, auto-scale to zero.

### 1. Create Project

```bash
ibmcloud ce project create --name openrag-pipeline
ibmcloud ce project select --name openrag-pipeline
```

### 2. Deploy Ray Head

```bash
ibmcloud ce app create \
  --name ray-head \
  --image rayproject/ray:2.44.1-py311 \
  --min-scale 1 --max-scale 1 \
  --cpu 4 --memory 8G \
  --port 6379 \
  --command "ray start --head --port=6379 --dashboard-host=0.0.0.0 --block"
```

### 3. Deploy Ray Workers

```bash
ibmcloud ce job create \
  --name ray-worker \
  --image rayproject/ray:2.44.1-py311 \
  --cpu 2 --memory 4G \
  --array-size 4 \
  --command "ray start --address=ray-head:6379 --block"
```

### Notes

- Integrate with IBM Cloud Object Storage (COS) for document staging.
- Connect to watsonx.ai for embedding generation.
- Use IBM Cloud Databases for managed OpenSearch.
- Workers scale to zero when idle; head node stays active.

---

## Common Operations

### Scaling Workers

```bash
# Docker Compose
docker compose --profile ray up -d --scale ray-worker=8

# Kubernetes
kubectl patch raycluster openrag-ray --type merge \
  -p '{"spec":{"workerGroupSpecs":[{"groupName":"cpu-workers","replicas":8}]}}'
```

### Monitoring

Access the Ray Dashboard at port 8265 to view:
- Active and pending tasks
- Cluster resource utilization (CPU, GPU, memory)
- Task logs and error traces
- Worker node status

### GPU vs CPU Placement

Tasks are automatically scheduled based on resource requirements:
- Set `execution.ray.num_gpus_per_task: 1` for GPU-accelerated embedding
- CPU workers handle parsing, chunking, and indexing
- KubeRay will autoscale GPU workers based on demand

### Troubleshooting

| Issue | Solution |
|-------|----------|
| Workers not connecting | Check `ray-head` service is reachable; verify network/port 6379 |
| OOM on workers | Increase memory limits or reduce `execution.concurrency` |
| Slow embedding | Increase `embedder.batch_size` or add GPU workers |
| Tasks stuck pending | Check `ray status` for available resources |
