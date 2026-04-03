variable "ibmcloud_api_key" {
  description = "IBM Cloud API key"
  type        = string
  sensitive   = true
}

variable "region" {
  description = "IBM Cloud region"
  type        = string
  default     = "us-south"
}

variable "resource_group" {
  description = "IBM Cloud resource group name"
  type        = string
  default     = "openrag-rg"
}

variable "prefix" {
  description = "Prefix for all resource names"
  type        = string
  default     = "openrag"
}

# ── IKS Cluster ───────────────────────────────────────────────────────────────

variable "cluster_name" {
  description = "IKS cluster name"
  type        = string
  default     = "openrag-cluster"
}

variable "kubernetes_version" {
  description = "Kubernetes version for IKS"
  type        = string
  default     = "1.31"
}

variable "worker_pool_flavor" {
  description = "Worker node machine type"
  type        = string
  default     = "bx2.4x16"   # 4 vCPU, 16GB RAM
}

variable "worker_count" {
  description = "Number of worker nodes per zone"
  type        = number
  default     = 2
}

variable "vpc_name" {
  description = "VPC name (created if not existing)"
  type        = string
  default     = "openrag-vpc"
}

variable "zone" {
  description = "VPC zone"
  type        = string
  default     = "us-south-1"
}

# ── IBM Databases for Redis ───────────────────────────────────────────────────

variable "redis_plan" {
  description = "IBM Databases for Redis plan"
  type        = string
  default     = "standard"   # standard | enterprise
}

variable "redis_version" {
  description = "Redis version"
  type        = string
  default     = "7.2"
}

variable "redis_memory_mb" {
  description = "Redis memory allocation in MB per member"
  type        = number
  default     = 1024
}

# ── OpenSearch ────────────────────────────────────────────────────────────────

variable "opensearch_replicas" {
  description = "Number of OpenSearch pods"
  type        = number
  default     = 1
}

variable "opensearch_storage_gb" {
  description = "OpenSearch persistent volume size (GB)"
  type        = number
  default     = 50
}

variable "opensearch_password" {
  description = "OpenSearch admin password"
  type        = string
  sensitive   = true
}

variable "opensearch_image" {
  description = "OpenSearch image"
  type        = string
  default     = "langflowai/openrag-opensearch:latest"
}

# ── OpenRAG Application ───────────────────────────────────────────────────────

variable "openrag_version" {
  description = "OpenRAG image tag"
  type        = string
  default     = "latest"
}

variable "openai_api_key" {
  description = "OpenAI API key"
  type        = string
  sensitive   = true
  default     = ""
}

variable "watsonx_api_key" {
  description = "WatsonX API key"
  type        = string
  sensitive   = true
  default     = ""
}

variable "watsonx_project_id" {
  description = "WatsonX project ID"
  type        = string
  default     = ""
}

variable "watsonx_endpoint" {
  description = "WatsonX endpoint URL"
  type        = string
  default     = ""
}

variable "session_secret" {
  description = "Session secret for OpenRAG"
  type        = string
  sensitive   = true
}

variable "encryption_key" {
  description = "Encryption key for OpenRAG"
  type        = string
  sensitive   = true
}

# ── KEDA Scaling ──────────────────────────────────────────────────────────────

variable "keda_version" {
  description = "KEDA Helm chart version"
  type        = string
  default     = "2.15.1"
}

variable "worker_max_replicas" {
  description = "Maximum concurrent pipeline worker Jobs"
  type        = number
  default     = 20
}

variable "worker_target_queue_length" {
  description = "Queue items per worker Job"
  type        = number
  default     = 5
}

# ── Backend scaling ───────────────────────────────────────────────────────────

variable "backend_min_replicas" {
  description = "Minimum backend pods (always running)"
  type        = number
  default     = 2
}

variable "backend_max_replicas" {
  description = "Maximum backend pods under load"
  type        = number
  default     = 10
}

variable "backend_cpu_target" {
  description = "Target CPU utilisation % to trigger HPA scale-out"
  type        = number
  default     = 70
}

variable "backend_queue_scale_ratio" {
  description = "Add 1 backend pod per this many queued items (handles upload/poll traffic surge)"
  type        = number
  default     = 50
}

# ── IBM Container Registry ────────────────────────────────────────────────────

variable "registry_namespace" {
  description = "IBM Container Registry namespace"
  type        = string
  default     = "openrag"
}
