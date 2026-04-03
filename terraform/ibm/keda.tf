# ── KEDA ─────────────────────────────────────────────────────────────────────

resource "helm_release" "keda" {
  name             = "keda"
  repository       = "https://kedacore.github.io/charts"
  chart            = "keda"
  version          = var.keda_version
  namespace        = "keda"
  create_namespace = true

  set {
    name  = "resources.operator.requests.memory"
    value = "64Mi"
  }
  set {
    name  = "resources.operator.limits.memory"
    value = "128Mi"
  }

  wait    = true
  timeout = 300

  depends_on = [ibm_container_vpc_cluster.cluster]
}

# ── KEDA TriggerAuthentication (Redis TLS cert) ───────────────────────────────

resource "kubernetes_manifest" "keda_redis_auth" {
  manifest = {
    apiVersion = "keda.sh/v1alpha1"
    kind       = "TriggerAuthentication"
    metadata = {
      name      = "openrag-redis-auth"
      namespace = kubernetes_namespace.openrag.metadata[0].name
    }
    spec = {
      secretTargetRef = [
        {
          parameter = "password"
          name      = kubernetes_secret.openrag.metadata[0].name
          key       = "REDIS_PASSWORD"
        }
      ]
    }
  }

  depends_on = [helm_release.keda]
}

# ── KEDA ScaledJob ────────────────────────────────────────────────────────────

resource "kubernetes_manifest" "pipeline_scaledjob" {
  manifest = {
    apiVersion = "keda.sh/v1alpha1"
    kind       = "ScaledJob"
    metadata = {
      name      = "openrag-pipeline-worker"
      namespace = kubernetes_namespace.openrag.metadata[0].name
    }
    spec = {
      jobTargetRef = {
        parallelism            = 1
        completions            = 1
        activeDeadlineSeconds  = 3600
        backoffLimit           = 0
        template = {
          metadata = {
            labels = { app = "openrag-pipeline-worker" }
          }
          spec = {
            restartPolicy = "Never"

            # Pin to spot pool for cost savings
            nodeSelector = {
              "openrag/pool" = "pipeline-workers"
            }

            containers = [{
              name    = "pipeline-worker"
              image   = "langflowai/openrag-backend:${var.openrag_version}"
              command = ["python", "-m", "pipeline.worker.job_worker"]

              resources = {
                requests = { cpu = "1", memory = "2Gi" }
                limits   = { cpu = "2", memory = "4Gi" }
              }

              env = [
                {
                  name = "REDIS_HOST"
                  valueFrom = {
                    secretKeyRef = {
                      name = kubernetes_secret.openrag.metadata[0].name
                      key  = "REDIS_HOST"
                    }
                  }
                },
                {
                  name = "REDIS_PORT"
                  valueFrom = {
                    secretKeyRef = {
                      name = kubernetes_secret.openrag.metadata[0].name
                      key  = "REDIS_PORT"
                    }
                  }
                },
                {
                  name = "REDIS_PASSWORD"
                  valueFrom = {
                    secretKeyRef = {
                      name = kubernetes_secret.openrag.metadata[0].name
                      key  = "REDIS_PASSWORD"
                    }
                  }
                },
                {
                  name = "OPENSEARCH_HOST"
                  valueFrom = {
                    secretKeyRef = {
                      name = kubernetes_secret.openrag.metadata[0].name
                      key  = "OPENSEARCH_HOST"
                    }
                  }
                },
                {
                  name = "OPENSEARCH_PASSWORD"
                  valueFrom = {
                    secretKeyRef = {
                      name = kubernetes_secret.openrag.metadata[0].name
                      key  = "OPENSEARCH_PASSWORD"
                    }
                  }
                },
                {
                  name = "OPENAI_API_KEY"
                  valueFrom = {
                    secretKeyRef = {
                      name     = kubernetes_secret.openrag.metadata[0].name
                      key      = "OPENAI_API_KEY"
                      optional = true
                    }
                  }
                },
                {
                  name  = "REDIS_WORKER_MODE"
                  value = "worker"
                },
                {
                  name  = "PIPELINE_EXECUTION_BACKEND"
                  value = "redis"
                },
                {
                  name  = "WORKER_IDLE_TIMEOUT"
                  value = "15"
                },
                {
                  name  = "PIPELINE_CONFIG_FILE"
                  value = "src/pipeline/presets/composable-redis.yaml"
                },
                {
                  name  = "LOG_FORMAT"
                  value = "json"
                }
              ]
            }]
          }
        }
      }

      triggers = [{
        type = "redis"
        authenticationRef = {
          name = "openrag-redis-auth"
        }
        metadata = {
          address       = "${local.redis_host}:${local.redis_port}"
          listName      = "pipeline:queue"
          listLength    = tostring(var.worker_target_queue_length)
          enableTLS     = "true"
          unsafeSsl     = "false"
        }
      }]

      pollingInterval              = 15
      maxReplicaCount              = var.worker_max_replicas
      successfulJobsHistoryLimit   = 3
      failedJobsHistoryLimit       = 5
      scalingStrategy = {
        strategy = "accurate"
      }
    }
  }

  depends_on = [
    helm_release.keda,
    kubernetes_manifest.keda_redis_auth,
  ]
}

# ── Backend ScaledObject ──────────────────────────────────────────────────────
# Scales the backend API on two signals:
#   1. CPU utilisation (handles general API load)
#   2. Redis queue depth (scales with upload/progress-poll surge during ingestion)
#
# Both signals are OR'd — whichever triggers first wins.
# minReplicaCount=2 ensures the API is never taken to zero.

resource "kubernetes_manifest" "backend_scaledobject" {
  manifest = {
    apiVersion = "keda.sh/v1alpha1"
    kind       = "ScaledObject"
    metadata = {
      name      = "openrag-backend"
      namespace = kubernetes_namespace.openrag.metadata[0].name
    }
    spec = {
      scaleTargetRef = {
        name = "openrag-backend"
      }

      minReplicaCount = var.backend_min_replicas
      maxReplicaCount = var.backend_max_replicas
      pollingInterval = 15
      cooldownPeriod  = 120   # wait 2 min before scaling back down

      triggers = [
        # Signal 1: CPU — general API traffic
        {
          type = "cpu"
          metricType = "Utilization"
          metadata = {
            value = tostring(var.backend_cpu_target)
          }
        },
        # Signal 2: Redis queue depth — ingestion upload/progress-poll surge
        # 1 extra backend pod per backend_queue_scale_ratio items in queue
        {
          type = "redis"
          authenticationRef = {
            name = "openrag-redis-auth"
          }
          metadata = {
            address    = "${local.redis_host}:${local.redis_port}"
            listName   = "pipeline:queue"
            listLength = tostring(var.backend_queue_scale_ratio)
            enableTLS  = "true"
            unsafeSsl  = "false"
          }
        }
      ]
    }
  }

  depends_on = [
    helm_release.keda,
    kubernetes_manifest.keda_redis_auth,
    kubernetes_deployment.backend,
  ]
}

# ── PodDisruptionBudgets ──────────────────────────────────────────────────────
# Ensure rolling upgrades never take all pods down simultaneously.

resource "kubernetes_pod_disruption_budget_v1" "backend" {
  metadata {
    name      = "openrag-backend-pdb"
    namespace = kubernetes_namespace.openrag.metadata[0].name
  }
  spec {
    min_available = 1
    selector {
      match_labels = { app = "openrag-backend" }
    }
  }
}

resource "kubernetes_pod_disruption_budget_v1" "frontend" {
  metadata {
    name      = "openrag-frontend-pdb"
    namespace = kubernetes_namespace.openrag.metadata[0].name
  }
  spec {
    min_available = 1
    selector {
      match_labels = { app = "openrag-frontend" }
    }
  }
}
