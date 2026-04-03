output "cluster_id" {
  description = "IKS cluster ID"
  value       = ibm_container_vpc_cluster.cluster.id
}

output "cluster_name" {
  description = "IKS cluster name"
  value       = ibm_container_vpc_cluster.cluster.name
}

output "frontend_url" {
  description = "Public URL of the OpenRAG frontend load balancer"
  value       = "http://${kubernetes_service.frontend.status[0].load_balancer[0].ingress[0].ip}"
}

output "redis_host" {
  description = "IBM Databases for Redis hostname"
  value       = local.redis_host
  sensitive   = true
}

output "redis_port" {
  description = "IBM Databases for Redis port"
  value       = local.redis_port
}

output "registry_namespace" {

  description = "IBM Container Registry namespace"
  value       = "us.icr.io/${ibm_cr_namespace.registry.name}"
}

output "kubeconfig_command" {
  description = "Command to configure kubectl for this cluster"
  value       = "ibmcloud ks cluster config --cluster ${ibm_container_vpc_cluster.cluster.name}"
}
