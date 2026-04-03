# ── IKS VPC Cluster ───────────────────────────────────────────────────────────

resource "ibm_container_vpc_cluster" "cluster" {
  name              = var.cluster_name
  vpc_id            = ibm_is_vpc.vpc.id
  flavor            = var.worker_pool_flavor
  worker_count      = var.worker_count
  kubernetes_version = var.kubernetes_version
  resource_group_id = data.ibm_resource_group.rg.id
  wait_till         = "IngressReady"

  zones {
    subnet_id = ibm_is_subnet.subnet.id
    name      = var.zone
  }

  # Enable logging and monitoring
  lifecycle {
    ignore_changes = [kubernetes_version]
  }
}

# ── Spot worker pool for pipeline workers (cost optimisation) ─────────────────
# KEDA Jobs are scheduled onto this pool via node selector / taint.

resource "ibm_container_vpc_worker_pool" "spot_pool" {
  cluster           = ibm_container_vpc_cluster.cluster.id
  worker_pool_name  = "pipeline-spot"
  flavor            = var.worker_pool_flavor
  vpc_id            = ibm_is_vpc.vpc.id
  worker_count      = 0    # starts at 0; cluster autoscaler/KEDA fills it
  resource_group_id = data.ibm_resource_group.rg.id

  zones {
    subnet_id = ibm_is_subnet.subnet.id
    name      = var.zone
  }

  labels = {
    "openrag/pool" = "pipeline-workers"
  }
}

# ── IBM Container Registry namespace ─────────────────────────────────────────

resource "ibm_cr_namespace" "registry" {
  name              = var.registry_namespace
  resource_group_id = data.ibm_resource_group.rg.id
}

# IAM policy: allow cluster to pull from registry
resource "ibm_iam_authorization_policy" "cluster_to_registry" {
  source_service_name         = "containers-kubernetes"
  source_resource_instance_id = ibm_container_vpc_cluster.cluster.id
  target_service_name         = "container-registry"
  roles                       = ["Reader", "Writer"]
}
