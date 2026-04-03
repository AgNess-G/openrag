# ── IBM Databases for Redis ───────────────────────────────────────────────────

resource "ibm_database" "redis" {
  name              = "${var.prefix}-redis"
  plan              = var.redis_plan
  location          = var.region
  service           = "databases-for-redis"
  resource_group_id = data.ibm_resource_group.rg.id
  version           = var.redis_version

  group {
    group_id = "member"
    memory {
      allocation_mb = var.redis_memory_mb
    }
    cpu {
      allocation_count = 0   # shared CPU on standard plan
    }
    disk {
      allocation_mb = 2048
    }
  }

  # Enable TLS (always on for IBM Databases)
  # Connection string is available in ibm_database_connection data source
}

# Fetch connection credentials
data "ibm_database_connection" "redis_conn" {
  deployment_id = ibm_database.redis.id
  user_type     = "database"
  user_id       = "admin"
  endpoint_type = "private"   # private endpoint stays within IBM Cloud network
}

locals {
  redis_host     = data.ibm_database_connection.redis_conn.redis[0].hosts[0].hostname
  redis_port     = data.ibm_database_connection.redis_conn.redis[0].hosts[0].port
  redis_password = data.ibm_database_connection.redis_conn.redis[0].authentication.password
  redis_cert     = data.ibm_database_connection.redis_conn.redis[0].certificate.certificate_base64
}
