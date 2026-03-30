import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from utils.opensearch_utils import setup_opensearch_security_ibm

@pytest.mark.asyncio
async def test_setup_opensearch_security_ibm_success():
    """Test successful security setup with all expected calls."""
    mock_client = MagicMock()
    mock_client.transport.perform_request = AsyncMock(return_value={"status": "OK", "message": "Success"})
    mock_client.cluster.health = AsyncMock(return_value={"status": "green"})

    # Sample configurations
    roles_data = {
        "openrag_user_role": {
            "cluster_permissions": ["read"],
            "index_permissions": [{"index_patterns": ["*"], "allowed_actions": ["crud"]}]
        }
    }
    mapping_data = {
        "openrag_user_role": {"backend_roles": ["openrag_user"]},
        "all_access": {"users": ["admin"]}
    }

    # Mock file existence and content
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", MagicMock()), \
         patch("yaml.safe_load") as mock_yaml:
        
        mock_yaml.side_effect = [roles_data, mapping_data]

        await setup_opensearch_security_ibm(mock_client)

        # Verify calls
        # 1. GET /_plugins/_security/api/rolesmapping
        # 2. PUT /_plugins/_security/api/roles/openrag_user_role
        # 3. PUT /_plugins/_security/api/rolesmapping/openrag_user_role
        # 4. PUT /_plugins/_security/api/rolesmapping/all_access
        # 5. GET /_plugins/_security/api/roles/openrag_user_role
        # 6. GET /_plugins/_security/api/rolesmapping/openrag_user_role
        
        assert mock_client.transport.perform_request.call_count == 6
        mock_client.cluster.health.assert_called_once()

        # Check call order and endpoints
        calls = mock_client.transport.perform_request.call_args_list
        assert calls[0][0] == ("GET", "/_plugins/_security/api/rolesmapping")
        assert calls[1][0] == ("PUT", "/_plugins/_security/api/roles/openrag_user_role")
        assert calls[2][0] == ("PUT", "/_plugins/_security/api/rolesmapping/openrag_user_role")
        assert calls[3][0] == ("PUT", "/_plugins/_security/api/rolesmapping/all_access")
        assert calls[4][0] == ("GET", "/_plugins/_security/api/roles/openrag_user_role")
        assert calls[5][0] == ("GET", "/_plugins/_security/api/rolesmapping/openrag_user_role")

@pytest.mark.asyncio
async def test_setup_opensearch_security_ibm_missing_files():
    """Test that missing configuration files raise FileNotFoundError."""
    mock_client = MagicMock()
    mock_client.transport.perform_request = AsyncMock()
    mock_client.cluster.health = AsyncMock()
    
    with patch("os.path.exists", return_value=False):
        with pytest.raises(FileNotFoundError):
            await setup_opensearch_security_ibm(mock_client)
