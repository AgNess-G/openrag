import asyncio
import os
import random
import yaml
from opensearchpy import AsyncOpenSearch
from utils.logging_config import get_logger

logger = get_logger(__name__)

DISK_SPACE_ERROR_MESSAGE = (
    "OpenSearch has run out of available disk space. "
    "Search and indexing operations are blocked. "
    "Please free up disk space to restore OpenRAG functionality."
)

# Error strings emitted by OpenSearch when disk watermark thresholds are breached
_DISK_SPACE_INDICATORS = [
    "disk watermark",
    "flood_stage",
    "flood stage",
    "disk usage exceeded",
    "index read-only",
    "no space left on device",
    "cluster_block_exception",
    "forbidden/12",
    "too_many_requests/12",
]


class OpenSearchNotReadyError(Exception):
    """Raised when OpenSearch fails to become ready within the retry limit."""


class OpenSearchDiskSpaceError(Exception):
    """Raised when OpenSearch operations fail due to insufficient disk space."""


def is_disk_space_error(error: Exception) -> bool:
    """Check whether an exception is caused by OpenSearch disk space constraints.

    OpenSearch blocks write and search operations when disk usage crosses
    the high-watermark or flood-stage watermark thresholds.
    This function detects those error signatures.

    Args:
        error: The exception to inspect.

    Returns:
        True if the error is disk-space related, False otherwise.
    """
    error_str = str(error).lower()
    return any(indicator in error_str for indicator in _DISK_SPACE_INDICATORS)

async def wait_for_opensearch(
    opensearch_client: AsyncOpenSearch,
    max_retries: int = 15,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
) -> None:
    """Wait for OpenSearch to be ready with exponential backoff and jitter.

    Args:
        opensearch_client: The OpenSearch client to use for health checks.
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay in seconds before the first retry.
        max_delay: Upper bound in seconds for the retry delay.

    Raises:
        OpenSearchNotReadyError: If OpenSearch fails to become ready within the retry limit.
    """
    for attempt in range(max_retries):
        display_attempt: int = attempt + 1

        logger.info(
            "Verifying whether OpenSearch is ready...",
            attempt=display_attempt,
            max_retries=max_retries,
        )

        try:
            # Simple ping to check connection
            if await opensearch_client.ping():
                # Also check cluster health
                health = await opensearch_client.cluster.health()
                status = health.get("status")
                if status in ["green", "yellow"]:
                    logger.info(
                        "Successfully verified that OpenSearch is ready.",
                        attempt=display_attempt,
                        status=status,
                    )
                    return
                else:
                    logger.warning(
                        "OpenSearch is up but cluster health is red.",
                        attempt=display_attempt,
                        status=status,
                    )
            else:
                logger.warning(
                    "OpenSearch ping failed.",
                    attempt=display_attempt,
                )
        except Exception as e:
            logger.warning(
                "OpenSearch is not ready.",
                attempt=display_attempt,
                error=str(e),
            )

        if attempt < max_retries - 1:
            delay = min(base_delay * (2 ** attempt), max_delay)
            delay = random.uniform(delay / 2, delay)

            logger.debug(
                "Retry OpenSearch readiness check after a delay (seconds).",
                attempt=display_attempt,
                delay=delay,
            )

            await asyncio.sleep(delay)

    message: str = "Failed to verify whether OpenSearch is ready."
    logger.error(message)
    raise OpenSearchNotReadyError(message)


async def setup_opensearch_security(opensearch_client: AsyncOpenSearch) -> None:
    """Setup OpenSearch roles and roles mapping.

    The setup involves:
    1. GET /_plugins/_security/api/rolesmapping (check existing)
    2. GET /_cluster/health
    3. PUT /_plugins/_security/api/roles/openrag_user_role (create role)
    4. PUT /_plugins/_security/api/rolesmapping/openrag_user_role (create mapping)
    5. PUT /_plugins/_security/api/rolesmapping/all_access (merge admin mapping)
    6. Verify with final GETs.

    This should be called during initial setup.
    """
    logger.info("Initializing OpenSearch security configuration...")

    # Define base security config directory relative to src root or current file
    # We'll use the project root if it exists, or look for securityconfig in the parent of src
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    security_config_dir = os.path.join(base_dir, "securityconfig")

    roles_file = os.path.join(security_config_dir, "roles.yml")
    roles_mapping_file = os.path.join(security_config_dir, "roles_mapping.yml")

    try:
        # 1. & 2. Readiness checks
        logger.debug("[OpenSearch Security] Performing readiness checks...")
        await opensearch_client.transport.perform_request("GET", "/_plugins/_security/api/rolesmapping")
        await opensearch_client.cluster.health()

        # Load role definitions from YAML
        if not os.path.exists(roles_file):
            logger.error(f"[OpenSearch Security] Roles configuration file not found: {roles_file}")
            raise FileNotFoundError(f"Roles configuration file not found: {roles_file}")

        with open(roles_file, "r") as f:
            roles_config = yaml.safe_load(f)

        # 3. Create openrag_user_role
        if "openrag_user_role" in roles_config:
            role_body = roles_config["openrag_user_role"]
            logger.info("[OpenSearch Security] Creating 'openrag_user_role' role...")
            resp = await opensearch_client.transport.perform_request(
                "PUT",
                "/_plugins/_security/api/roles/openrag_user_role",
                body=role_body,
                headers={"Content-Type": "application/json"}
            )
            logger.debug("[OpenSearch Security] Role creation response", status=resp.get("status"), message=resp.get("message"))
        else:
            logger.warning("[OpenSearch Security] 'openrag_user_role' not found in roles.yml")

        # Load roles mapping from YAML
        if not os.path.exists(roles_mapping_file):
            logger.error(f"[OpenSearch Security] Roles mapping file not found: {roles_mapping_file}")
            raise FileNotFoundError(f"Roles mapping file not found: {roles_mapping_file}")

        with open(roles_mapping_file, "r") as f:
            mapping_config = yaml.safe_load(f)

        # 4. Create openrag_user_role mapping
        if "openrag_user_role" in mapping_config:
            mapping_body = mapping_config["openrag_user_role"]
            logger.info("[OpenSearch Security] Creating 'openrag_user_role' mapping...")
            resp = await opensearch_client.transport.perform_request(
                "PUT",
                "/_plugins/_security/api/rolesmapping/openrag_user_role",
                body=mapping_body,
                headers={"Content-Type": "application/json"}
            )
            logger.debug("[OpenSearch Security] Role mapping update response", status=resp.get("status"), message=resp.get("message"))

        # 5. Create all_access mapping (merges with existing admin user)
        if "all_access" in mapping_config:
            all_access_body = mapping_config["all_access"]

            # Ensure backend_roles are present as required by some IBM environments
            if "backend_roles" not in all_access_body:
                all_access_body["backend_roles"] = ["admin", "all_access"]
            if "description" not in all_access_body:
                all_access_body["description"] = "Maps admin to all_access"

            logger.info("[OpenSearch Security] Updating 'all_access' mapping...")
            resp = await opensearch_client.transport.perform_request(
                "PUT",
                "/_plugins/_security/api/rolesmapping/all_access",
                body=all_access_body,
                headers={"Content-Type": "application/json"}
            )
            logger.debug("[OpenSearch Security] All access mapping update response", status=resp.get("status"), message=resp.get("message"))

        # 6. Final verification
        logger.info("[OpenSearch Security] Verifying security configuration...")
        await opensearch_client.transport.perform_request("GET", "/_plugins/_security/api/roles/openrag_user_role")
        await opensearch_client.transport.perform_request("GET", "/_plugins/_security/api/rolesmapping/openrag_user_role")

        logger.info("Successfully completed OpenSearch security configuration.")

    except Exception as e:
        # Check for authentication errors or if the security plugin is missing
        error_str = str(e).lower()
        if any(code in error_str for code in ["401", "403", "404", "security_exception", "not_found"]):
            logger.warning(
                "Skipping OpenSearch security configuration: "
                "The cluster may not have the security plugin enabled or "
                "the provided credentials do not have administrative permissions."
            )
            return

        logger.error("Failed to setup OpenSearch security configuration", error=str(e))
        # Re-raise for non-auth/non-security errors to ensure visibility
        raise
