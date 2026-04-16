"""Centralized path helpers for OpenRAG.

This module is the single source of truth for the OPENRAG_*_PATH environment variables.
Variables are read directly via ``os.getenv`` here to avoid circular imports
(settings → config_manager → paths → settings).
"""

import os
from utils.logging_config import get_logger
logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Documents directory
# ---------------------------------------------------------------------------
def get_documents_path() -> str:
    """Return the path to the documents directory.

    Environment variable: OPENRAG_DOCUMENTS_PATH
    Default: ``openrag-documents``  (relative to the working directory)
    """
    logger.debug(f"OPENRAG_DOCUMENTS_PATH: {os.getenv('OPENRAG_DOCUMENTS_PATH')}")
    return os.getenv("OPENRAG_DOCUMENTS_PATH") or "openrag-documents"


# ---------------------------------------------------------------------------
# JWT keys directory
# ---------------------------------------------------------------------------
def get_keys_path() -> str:
    """Return the path to the JWT keys directory.

    Environment variable: OPENRAG_KEYS_PATH
    Default: ``keys``  (relative to the working directory)
    """
    logger.debug(f"OPENRAG_KEYS_PATH: {os.getenv('OPENRAG_KEYS_PATH')}")
    return os.getenv("OPENRAG_KEYS_PATH") or "keys"


# ---------------------------------------------------------------------------
# Flows directory
# ---------------------------------------------------------------------------
def get_flows_path() -> str:
    """Return the path to the flows directory.

    Environment variable: OPENRAG_FLOWS_PATH
    Default: ``flows``  (relative to the working directory)
    """
    logger.debug(f"OPENRAG_FLOWS_PATH: {os.getenv('OPENRAG_FLOWS_PATH')}")
    return os.getenv("OPENRAG_FLOWS_PATH") or "flows"


def get_flows_backup_path() -> str:
    """Return the path to the flows backup directory.

    Environment variable: OPENRAG_FLOWS_BACKUP_PATH
    Default: ``<flows_path>/backup``
    """
    logger.debug(f"OPENRAG_FLOWS_BACKUP_PATH: {os.getenv('OPENRAG_FLOWS_BACKUP_PATH')}")
    return os.getenv("OPENRAG_FLOWS_BACKUP_PATH") or os.path.join(get_flows_path(), "backup")


# ---------------------------------------------------------------------------
# Config directory (holds config.yaml)
# ---------------------------------------------------------------------------
def get_config_path() -> str:
    """Return the path to the configuration directory.

    Environment variable: OPENRAG_CONFIG_PATH
    Default: ``config``  (relative to the working directory)
    """

    logger.debug(f"OPENRAG_CONFIG_PATH: {os.getenv('OPENRAG_CONFIG_PATH')}")
    return os.getenv("OPENRAG_CONFIG_PATH") or "config"


def get_config_file_path() -> str:
    """Return the full path to the config.yaml file."""
    logger.debug(f"get_config_file_path: {os.path.join(get_config_path(), 'config.yaml')}")
    return os.path.join(get_config_path(), "config.yaml")


# ---------------------------------------------------------------------------
# Data directory (conversations, tokens, connections, etc.)
# ---------------------------------------------------------------------------
def get_data_path() -> str:
    """Return the path to the data directory.

    Environment variable: OPENRAG_DATA_PATH
    Default: ``data``  (relative to the working directory)
    """
    logger.debug(f"OPENRAG_DATA_PATH: {os.getenv('OPENRAG_DATA_PATH')}")
    return os.getenv("OPENRAG_DATA_PATH") or "data"


def get_data_file(filename: str) -> str:
    """Return a full path for a file inside the data directory.

    Example::

        get_data_file("conversations.json")
        # → "data/conversations.json"  (or $OPENRAG_DATA_PATH/conversations.json)
    """
    logger.debug(f"get_data_file: {os.path.join(get_data_path(), filename)}")
    return os.path.join(get_data_path(), filename)
