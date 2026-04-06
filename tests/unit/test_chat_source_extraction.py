from types import SimpleNamespace

import pytest

import agent


class _ResponseWithModelDump:
    def __init__(self, payload):
        self._payload = payload

    def model_dump(self):
        return self._payload


@pytest.mark.asyncio
async def test_async_langflow_chat_extracts_nested_tool_sources(monkeypatch):
    response_payload = {
        "outputs": {
            "message": {
                "data": {
                    "content_blocks": [
                        {
                            "contents": [
                                {
                                    "type": "tool_use",
                                    "name": "search_documents",
                                    "output": [
                                        {
                                            "text_key": "text",
                                            "data": {
                                                "text": "Purple elephants dancing in the moonlight.",
                                                "filename": "sdk_test_doc.md",
                                                "score": 0.98,
                                                "page": 1,
                                                "mimetype": "text/markdown",
                                            },
                                        }
                                    ],
                                }
                            ]
                        }
                    ]
                }
            }
        }
    }

    async def fake_async_response(*args, **kwargs):
        return (
            'The document mentions "purple elephants dancing."',
            "response-123",
            _ResponseWithModelDump(response_payload),
        )

    monkeypatch.setattr(agent, "async_response", fake_async_response)

    response_text, response_id, sources = await agent.async_langflow_chat(
        langflow_client=SimpleNamespace(),
        flow_id="flow-id",
        prompt="What color are the dancing animals?",
        user_id="test-user",
        store_conversation=False,
    )

    assert response_id == "response-123"
    assert "purple elephants" in response_text
    assert sources == [
        {
            "filename": "sdk_test_doc.md",
            "text": "Purple elephants dancing in the moonlight.",
            "score": 0.98,
            "page": 1,
            "mimetype": "text/markdown",
        }
    ]
