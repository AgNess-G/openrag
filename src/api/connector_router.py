"""Connector router that automatically routes based on configuration settings."""

from config.settings import DISABLE_INGEST_WITH_LANGFLOW
from utils.logging_config import get_logger

logger = get_logger(__name__)


class ConnectorRouter:
    """
    Router that automatically chooses between LangflowConnectorService,
    traditional ConnectorService, or composable-pipeline ConnectorService.

    Priority: composable > DISABLE_INGEST_WITH_LANGFLOW > Langflow default.
    """

    def __init__(
        self,
        langflow_connector_service,
        openrag_connector_service,
        pipeline_service=None,
        pipeline_config=None,
    ):
        self.langflow_connector_service = langflow_connector_service
        self.openrag_connector_service = openrag_connector_service
        self._pipeline_service = pipeline_service
        self._pipeline_config = pipeline_config
        self._is_composable = (
            pipeline_config is not None
            and pipeline_config.ingestion_mode == "composable"
        )
        logger.debug(
            "ConnectorRouter initialized",
            disable_langflow_ingest=DISABLE_INGEST_WITH_LANGFLOW,
            composable=self._is_composable,
        )

    def get_active_service(self):
        """Get the currently active connector service based on configuration."""
        if self._is_composable:
            logger.debug("Using traditional OpenRAG connector service (composable mode)")
            return self.openrag_connector_service
        if DISABLE_INGEST_WITH_LANGFLOW:
            logger.debug("Using traditional OpenRAG connector service")
            return self.openrag_connector_service
        else:
            logger.debug("Using Langflow connector service")
            return self.langflow_connector_service

    # Proxy all connector service methods to the active service

    async def initialize(self):
        """Initialize the active connector service."""
        # Initialize OpenSearch index if using traditional OpenRAG connector service

        return await self.get_active_service().initialize()

    @property
    def connection_manager(self):
        """Get the connection manager from the active service."""
        return self.get_active_service().connection_manager

    async def get_connector(self, connection_id: str):
        """Get a connector instance from the active service."""
        return await self.get_active_service().get_connector(connection_id)

    async def sync_specific_files(
        self, connection_id: str, user_id: str, file_list: list, jwt_token: str = None, file_infos: list = None
    ):
        """Sync specific files using the active service."""
        return await self.get_active_service().sync_specific_files(
            connection_id, user_id, file_list, jwt_token, file_infos=file_infos
        )

    def __getattr__(self, name):
        """
        Proxy any other method calls to the active service.
        This ensures compatibility with any methods we might have missed.
        """
        active_service = self.get_active_service()
        if hasattr(active_service, name):
            return getattr(active_service, name)
        else:
            raise AttributeError(
                f"'{type(active_service).__name__}' object has no attribute '{name}'"
            )
