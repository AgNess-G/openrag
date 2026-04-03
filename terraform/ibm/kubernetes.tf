# ── Namespace ─────────────────────────────────────────────────────────────────

resource "kubernetes_namespace" "openrag" {
  metadata {
    name = "openrag"
    labels = {
      "app.kubernetes.io/managed-by" = "terraform"
    }
  }
}

# ── Secrets ───────────────────────────────────────────────────────────────────

resource "kubernetes_secret" "openrag" {
  metadata {
    name      = "openrag-secrets"
    namespace = kubernetes_namespace.openrag.metadata[0].name
  }

  data = {
    OPENSEARCH_HOST             = "opensearch.openrag.svc.cluster.local"
    OPENSEARCH_PORT             = "9200"
    OPENSEARCH_USERNAME         = "admin"
    OPENSEARCH_PASSWORD         = var.opensearch_password
    OPENAI_API_KEY              = var.openai_api_key
    WATSONX_API_KEY             = var.watsonx_api_key
    WATSONX_PROJECT_ID          = var.watsonx_project_id
    WATSONX_ENDPOINT            = var.watsonx_endpoint
    REDIS_HOST                  = local.redis_host
    REDIS_PORT                  = tostring(local.redis_port)
    REDIS_PASSWORD              = local.redis_password
    REDIS_TLS_CERT_BASE64       = local.redis_cert
    # IBM_COS_* vars are NOT platform infrastructure.
    # They are user-provided connector credentials entered via the UI.
    # Set them here only if pre-configuring a shared IBM COS connector.
    SESSION_SECRET              = var.session_secret
    OPENRAG_ENCRYPTION_KEY      = var.encryption_key
  }
}

# ── OpenSearch StatefulSet ────────────────────────────────────────────────────

resource "kubernetes_stateful_set" "opensearch" {
  metadata {
    name      = "opensearch"
    namespace = kubernetes_namespace.openrag.metadata[0].name
  }

  spec {
    service_name = "opensearch"
    replicas     = var.opensearch_replicas

    selector {
      match_labels = { app = "opensearch" }
    }

    template {
      metadata {
        labels = { app = "opensearch" }
      }

      spec {
        container {
          name  = "opensearch"
          image = var.opensearch_image

          env {
            name  = "discovery.type"
            value = "single-node"
          }
          env {
            name = "OPENSEARCH_INITIAL_ADMIN_PASSWORD"
            value_from {
              secret_key_ref {
                name = kubernetes_secret.openrag.metadata[0].name
                key  = "OPENSEARCH_PASSWORD"
              }
            }
          }

          port { container_port = 9200 }
          port { container_port = 9600 }

          resources {
            requests = { memory = "2Gi", cpu = "500m" }
            limits   = { memory = "4Gi", cpu = "2" }
          }

          volume_mount {
            name       = "data"
            mount_path = "/usr/share/opensearch/data"
          }
        }
      }
    }

    volume_claim_template {
      metadata { name = "data" }
      spec {
        access_modes       = ["ReadWriteOnce"]
        storage_class_name = "ibmc-vpc-block-10iops-tier"
        resources {
          requests = { storage = "${var.opensearch_storage_gb}Gi" }
        }
      }
    }
  }
}

resource "kubernetes_service" "opensearch" {
  metadata {
    name      = "opensearch"
    namespace = kubernetes_namespace.openrag.metadata[0].name
  }
  spec {
    selector = { app = "opensearch" }
    port {
      name        = "rest"
      port        = 9200
      target_port = 9200
    }
    type = "ClusterIP"
  }
}

# ── Backend Deployment ────────────────────────────────────────────────────────

resource "kubernetes_deployment" "backend" {
  metadata {
    name      = "openrag-backend"
    namespace = kubernetes_namespace.openrag.metadata[0].name
  }

  spec {
    replicas = 2

    selector {
      match_labels = { app = "openrag-backend" }
    }

    template {
      metadata {
        labels = { app = "openrag-backend" }
      }

      spec {
        container {
          name  = "backend"
          image = "langflowai/openrag-backend:${var.openrag_version}"

          port { container_port = 8000 }

          env_from {
            secret_ref {
              name = kubernetes_secret.openrag.metadata[0].name
            }
          }

          env {
            name  = "PIPELINE_INGESTION_MODE"
            value = "composable"
          }
          env {
            name  = "PIPELINE_EXECUTION_BACKEND"
            value = "redis"
          }
          env {
            name  = "REDIS_WORKER_MODE"
            value = "worker"   # enqueue only; K8s Jobs drain
          }
          env {
            name  = "DISABLE_LANGFLOW"
            value = "true"
          }
          env {
            name  = "PIPELINE_CONFIG_FILE"
            value = "src/pipeline/presets/composable-redis.yaml"
          }
          env {
            name  = "LOG_FORMAT"
            value = "json"
          }

          resources {
            requests = { memory = "512Mi", cpu = "250m" }
            limits   = { memory = "2Gi",   cpu = "1" }
          }

          liveness_probe {
            http_get {
              path = "/health"
              port = 8000
            }
            initial_delay_seconds = 30
            period_seconds        = 15
          }

          readiness_probe {
            http_get {
              path = "/health"
              port = 8000
            }
            initial_delay_seconds = 15
            period_seconds        = 10
          }
        }
      }
    }
  }
}

resource "kubernetes_service" "backend" {
  metadata {
    name      = "openrag-backend"
    namespace = kubernetes_namespace.openrag.metadata[0].name
  }
  spec {
    selector = { app = "openrag-backend" }
    port {
      port        = 8000
      target_port = 8000
    }
    type = "ClusterIP"
  }
}

# ── Frontend Deployment ───────────────────────────────────────────────────────

resource "kubernetes_deployment" "frontend" {
  metadata {
    name      = "openrag-frontend"
    namespace = kubernetes_namespace.openrag.metadata[0].name
  }

  spec {
    replicas = 2

    selector {
      match_labels = { app = "openrag-frontend" }
    }

    template {
      metadata {
        labels = { app = "openrag-frontend" }
      }

      spec {
        container {
          name  = "frontend"
          image = "langflowai/openrag-frontend:${var.openrag_version}"

          port { container_port = 3000 }

          env {
            name  = "OPENRAG_BACKEND_HOST"
            value = "openrag-backend"
          }

          resources {
            requests = { memory = "256Mi", cpu = "100m" }
            limits   = { memory = "512Mi", cpu = "500m" }
          }
        }
      }
    }
  }
}

resource "kubernetes_service" "frontend" {
  metadata {
    name      = "openrag-frontend"
    namespace = kubernetes_namespace.openrag.metadata[0].name
    annotations = {
      # IBM Cloud VPC load balancer
      "service.kubernetes.io/ibm-load-balancer-cloud-provider-ip-type" = "public"
    }
  }
  spec {
    selector = { app = "openrag-frontend" }
    port {
      port        = 80
      target_port = 3000
    }
    type = "LoadBalancer"
  }
}
