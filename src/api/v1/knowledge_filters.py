"""
Public API v1 Knowledge Filters endpoints.

Provides knowledge filter management.
Uses API key authentication — delegates to the main api/knowledge_filter.py handlers
which now have all the Depends() wiring built in.
"""
from api import knowledge_filter


# Since the main handlers in api/knowledge_filter.py already use Depends(),
# the v1 endpoint routes in main.py can point directly to those handlers.
# This module exports thin aliases for backwards compatibility.

create_endpoint = knowledge_filter.create_knowledge_filter
search_endpoint = knowledge_filter.search_knowledge_filters
get_endpoint = knowledge_filter.get_knowledge_filter
update_endpoint = knowledge_filter.update_knowledge_filter
delete_endpoint = knowledge_filter.delete_knowledge_filter
