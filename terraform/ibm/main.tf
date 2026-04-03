terraform {
  required_version = ">= 1.5"

  required_providers {
    ibm = {
      source  = "IBM-Cloud/ibm"
      version = "~> 1.67"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.30"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.14"
    }
  }

  # Uncomment to use IBM Cloud Object Storage as Terraform backend
  # backend "s3" {
  #   bucket                      = "openrag-tfstate"
  #   key                         = "openrag/terraform.tfstate"
  #   region                      = "us-south"
  #   endpoint                    = "s3.us-south.cloud-object-storage.appdomain.cloud"
  #   skip_credentials_validation = true
  #   skip_metadata_api_check     = true
  #   skip_region_validation      = true
  #   force_path_style            = true
  # }
}

provider "ibm" {
  ibmcloud_api_key = var.ibmcloud_api_key
  region           = var.region
}

# ── Resource group ────────────────────────────────────────────────────────────

data "ibm_resource_group" "rg" {
  name = var.resource_group
}

# ── Kubernetes provider (wired to IKS cluster) ────────────────────────────────

data "ibm_container_cluster_config" "cluster" {
  cluster_name_id = ibm_container_vpc_cluster.cluster.id
  admin           = true
}

provider "kubernetes" {
  host                   = data.ibm_container_cluster_config.cluster.host
  token                  = data.ibm_container_cluster_config.cluster.token
  cluster_ca_certificate = data.ibm_container_cluster_config.cluster.ca_certificate
}

provider "helm" {
  kubernetes {
    host                   = data.ibm_container_cluster_config.cluster.host
    token                  = data.ibm_container_cluster_config.cluster.token
    cluster_ca_certificate = data.ibm_container_cluster_config.cluster.ca_certificate
  }
}
