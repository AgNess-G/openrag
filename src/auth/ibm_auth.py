"""IBM AMS JWT validation helper.

Validates JWTs from IBM Watsonx Data session cookies, including the fixed
`ibm-lh-console-session` name and dynamic `ibm-lh-console-session-*` variants.
The public key is fetched from IBM_JWT_PUBLIC_KEY_URL at startup and cached
in-process. On validation failure the key is re-fetched once to handle key
rotation.
"""
import httpx
import jwt
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from utils.logging_config import get_logger

logger = get_logger(__name__)

# Module-level cache; populated by fetch_ibm_public_key() at startup.
_cached_public_key = None


async def fetch_ibm_public_key(url: str):
    """Fetch IBM's JWT public key PEM from *url* and cache it.

    Returns the loaded public key object.
    """
    global _cached_public_key
    logger.info("Fetching IBM JWT public key", url=url)
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
        public_key_pem = data.get("public_key")
        if not public_key_pem:
            logger.error("IBM JWT public key not found in response")
            raise ValueError("IBM JWT public key not found in response")
        if isinstance(public_key_pem, str):
            public_key_pem = public_key_pem.encode("utf-8")
        _cached_public_key = load_pem_public_key(public_key_pem)
    logger.info("IBM JWT public key cached successfully")
    return _cached_public_key


def validate_ibm_jwt(token: str, public_key) -> dict | None:
    """Validate *token* with *public_key*.

    Returns the decoded claims dict on success, or ``None`` on any failure
    (expired, bad signature, missing claims, etc.).
    """
    if public_key is None:
        logger.warning("IBM JWT validation skipped — no public key loaded")
        return None
    try:
        return jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience="AMS-UI",
            issuer="IBMLH",
            options={"verify_exp": True},
        )
    except jwt.ExpiredSignatureError:
        logger.warning("IBM JWT has expired")
        return None
    except jwt.InvalidTokenError as exc:
        logger.warning("IBM JWT validation failed", error=str(exc))
        return None
