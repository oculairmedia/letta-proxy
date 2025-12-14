"""
Tests for the Letta context poller message fetching functionality.

These tests cover the core polling logic including:
- Normal message fetching
- Handling stale/deleted message IDs (404 errors)
- Fallback behavior when 'after' param fails
- Skipping already-processed messages
- Agent exclusion logic
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import requests


class TestShouldExcludeAgent:
    """Tests for the agent exclusion logic."""

    def test_exclude_sleeptime_agent_by_name(self):
        """Test that sleeptime agents are excluded by name pattern."""
        from list_letta_agents import should_exclude_agent
        assert should_exclude_agent("agent-123", "Meridian-sleeptime") is True
        assert should_exclude_agent("agent-456", "sleeptime-agent") is True
        assert should_exclude_agent("agent-789", "my-SLEEPTIME-agent") is True

    def test_include_regular_agent(self):
        """Test that regular agents are not excluded."""
        from list_letta_agents import should_exclude_agent
        assert should_exclude_agent("agent-123", "Meridian") is False
        assert should_exclude_agent("agent-456", "BMO") is False
        assert should_exclude_agent("agent-789", "GraphitiExplorer") is False


class TestMessageTypeConstants:
    """Tests for message type constants."""

    def test_allowed_message_types(self):
        """Verify allowed message types are correct."""
        from list_letta_agents import ALLOWED_MESSAGE_TYPES
        assert "user_message" in ALLOWED_MESSAGE_TYPES
        assert "assistant_message" in ALLOWED_MESSAGE_TYPES
        assert "reasoning_message" in ALLOWED_MESSAGE_TYPES

    def test_skipped_message_types(self):
        """Verify skipped message types are correct."""
        from list_letta_agents import SKIPPED_MESSAGE_TYPES
        assert "tool_return_message" in SKIPPED_MESSAGE_TYPES


class TestFetchNewMessagesForAgent:
    """Tests for the fetch_new_messages_for_agent function."""

    @pytest.fixture
    def mock_headers(self):
        return {"Authorization": "Bearer test-password"}

    @pytest.fixture
    def api_url_base(self):
        return "http://localhost:8283/v1"

    def test_fetch_messages_no_prior_state(self, mock_headers, api_url_base):
        """Test fetching messages when there's no prior polling state."""
        from list_letta_agents import fetch_new_messages_for_agent

        # Mock returns 1 message, then empty (simulating end of messages)
        call_count = [0]

        def mock_get_side_effect(*args, **kwargs):
            call_count[0] += 1
            response = Mock()
            response.status_code = 200
            response.raise_for_status = Mock()
            if call_count[0] == 1:
                response.json.return_value = [
                    {"id": "message-001", "type": "user_message", "content": "Hello"},
                ]
            else:
                response.json.return_value = []  # No more messages
            return response

        with patch("list_letta_agents.requests.get", side_effect=mock_get_side_effect) as mock_get:
            messages = fetch_new_messages_for_agent(
                agent_id="agent-123",
                api_url_base=api_url_base,
                headers=mock_headers,
                last_message_id=None,
            )

            first_call_args = mock_get.call_args_list[0]
            first_params = first_call_args.kwargs.get("params", {})

            # No cursor on first call
            assert "after" not in first_params
            # Uses correct pagination direction
            assert first_params.get("order") == "asc"

            assert len(messages) == 1

    def test_fetch_messages_with_prior_state(self, mock_headers, api_url_base):
        """Test fetching messages with a valid last_message_id."""
        from list_letta_agents import fetch_new_messages_for_agent

        call_count = [0]
        captured_params = []

        def mock_get_side_effect(*args, **kwargs):
            call_count[0] += 1
            params = dict(kwargs.get("params", {}))
            captured_params.append(params)

            response = Mock()
            response.status_code = 200
            response.raise_for_status = Mock()

            # First call with original cursor returns one new message
            if call_count[0] == 1 and params.get("after") == "message-002":
                response.json.return_value = [
                    {"id": "message-003", "type": "user_message", "content": "New message"},
                ]
            else:
                response.json.return_value = []
            return response

        with patch("list_letta_agents.requests.get", side_effect=mock_get_side_effect):
            messages = fetch_new_messages_for_agent(
                agent_id="agent-123",
                api_url_base=api_url_base,
                headers=mock_headers,
                last_message_id="message-002",
            )

        assert captured_params[0].get("after") == "message-002"
        assert captured_params[0].get("order") == "asc"
        assert len(messages) == 1

    def test_fetch_messages_404_triggers_fallback(self, mock_headers, api_url_base):
        """Test that 404 errors trigger fallback to fetch without 'after' param."""
        from list_letta_agents import fetch_new_messages_for_agent
        
        call_count = [0]

        def mock_get_side_effect(*args, **kwargs):
            call_count[0] += 1
            response = Mock()
            
            if call_count[0] == 1:
                # First call with 'after' param - raise 404
                response.status_code = 404
                response.text = '{"detail": "Message not found"}'
                error = requests.exceptions.HTTPError(response=response)
                error.response = response
                response.raise_for_status.side_effect = error
                return response
            elif call_count[0] == 2:
                # Second call without 'after' - success with message
                response.status_code = 200
                response.json.return_value = [
                    {"id": "message-new", "type": "user_message", "content": "Latest"},
                ]
                response.raise_for_status = Mock()
                return response
            else:
                # Third call - no more messages
                response.status_code = 200
                response.json.return_value = []
                response.raise_for_status = Mock()
                return response

        with patch("list_letta_agents.requests.get", side_effect=mock_get_side_effect):
            messages = fetch_new_messages_for_agent(
                agent_id="agent-123",
                api_url_base=api_url_base,
                headers=mock_headers,
                last_message_id="message-deleted",
            )

            # Should have made at least 2 calls - first with 'after' (404), second without
            assert call_count[0] >= 2
            assert len(messages) == 1
            assert messages[0]["id"] == "message-new"

    def test_fetch_messages_empty_response_does_not_fallback(self, mock_headers, api_url_base):
        """Test that an empty response with a valid cursor returns no messages.

        With the correct pagination strategy (`order=asc` + `after`), an empty
        response simply means "no new messages" and should not trigger a fallback.
        """
        from list_letta_agents import fetch_new_messages_for_agent

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_response.raise_for_status = Mock()

        with patch("list_letta_agents.requests.get", return_value=mock_response) as mock_get:
            messages = fetch_new_messages_for_agent(
                agent_id="agent-123",
                api_url_base=api_url_base,
                headers=mock_headers,
                last_message_id="message-stale",
            )

        assert mock_get.call_count == 1
        assert messages == []

    def test_fetch_messages_no_retry_without_after_param(self, mock_headers, api_url_base):
        """Test that empty response without 'after' param doesn't retry infinitely."""
        from list_letta_agents import fetch_new_messages_for_agent
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_response.raise_for_status = Mock()

        with patch("list_letta_agents.requests.get", return_value=mock_response) as mock_get:
            messages = fetch_new_messages_for_agent(
                agent_id="agent-123",
                api_url_base=api_url_base,
                headers=mock_headers,
                last_message_id=None,  # No prior state
            )

            # Should only make 1 call
            assert mock_get.call_count == 1
            assert len(messages) == 0


class TestFormatMessageForGraphiti:
    """Tests for message formatting logic."""

    def test_format_user_message(self):
        """Test formatting a user message."""
        from list_letta_agents import format_message_for_graphiti
        
        message = {
            "id": "message-001",
            "type": "user_message",
            "content": [{"type": "text", "text": "Hello agent"}],
            "created_at": "2024-01-01T12:00:00Z",
            "user_id": "user-123",
        }
        
        result = format_message_for_graphiti(message)
        
        assert result is not None
        assert result["role_type"] == "user"
        assert "Hello agent" in result["content"]

    def test_format_assistant_message(self):
        """Test formatting an assistant message."""
        from list_letta_agents import format_message_for_graphiti
        
        message = {
            "id": "message-002",
            "type": "assistant_message",
            "content": [{"type": "text", "text": "Hello user"}],
            "created_at": "2024-01-01T12:00:01Z",
        }
        
        result = format_message_for_graphiti(message)
        
        assert result is not None
        assert result["role_type"] == "assistant"

    def test_format_message_with_message_type_field(self):
        """Test formatting when API returns 'message_type' instead of 'type'.
        
        The Letta API returns 'message_type' field but older code expected 'type'.
        This test ensures both field names are handled correctly.
        """
        from list_letta_agents import format_message_for_graphiti
        
        # This is the actual format returned by the Letta API
        message = {
            "id": "message-003",
            "message_type": "assistant_message",  # API uses 'message_type' not 'type'
            "content": "Test response from agent",
            "date": "2024-01-01T12:00:00Z",  # API uses 'date' not 'created_at'
            "sender_id": None,
        }
        
        result = format_message_for_graphiti(message)
        
        assert result is not None
        assert result["role_type"] == "assistant"
        assert "Test response" in result["content"]

    def test_format_user_message_with_api_fields(self):
        """Test formatting user message with actual API field names."""
        from list_letta_agents import format_message_for_graphiti
        
        message = {
            "id": "message-004",
            "message_type": "user_message",
            "content": "Hello from user",
            "date": "2024-01-01T12:00:00Z",
            "sender_id": "user-456",
        }
        
        result = format_message_for_graphiti(message)
        
        assert result is not None
        assert result["role_type"] == "user"
        assert "Hello from user" in result["content"]

    def test_skip_tool_return_message(self):
        """Test that tool return messages are skipped."""
        from list_letta_agents import format_message_for_graphiti
        
        message = {
            "id": "message-003",
            "type": "tool_return_message",
            "content": "tool output",
            "created_at": "2024-01-01T12:00:02Z",
        }
        
        result = format_message_for_graphiti(message)
        
        assert result is None

    def test_format_reasoning_message(self):
        """Test formatting a reasoning message."""
        from list_letta_agents import format_message_for_graphiti
        
        message = {
            "id": "message-004",
            "type": "reasoning_message",
            "reasoning": "Let me think about this...",
            "created_at": "2024-01-01T12:00:03Z",
        }
        
        result = format_message_for_graphiti(message)
        
        assert result is not None
        assert result["role_type"] == "system"  # reasoning messages use system role


class TestDuplicateMessagePrevention:
    """Tests for duplicate message prevention logic."""

    def test_skip_message_matching_last_id(self):
        """
        Test that messages matching last_message_id are skipped.
        This simulates the main() loop logic.
        """
        # Simulate fetched messages (what fetch_new_messages_for_agent returns)
        fetched_messages = [
            {"id": "message-already-processed", "type": "user_message", "content": "Old"},
        ]
        
        # Simulate the skip logic from main()
        last_message_id_for_agent = "message-already-processed"
        processed = []
        
        for msg in fetched_messages:
            # This is the actual skip logic from the code
            if last_message_id_for_agent and msg['id'] == last_message_id_for_agent:
                continue  # Skip already processed
            processed.append(msg)
        
        assert len(processed) == 0  # Should be skipped

    def test_process_new_messages(self):
        """Test that new messages (not matching last_id) are processed."""
        fetched_messages = [
            {"id": "message-new-1", "type": "user_message", "content": "New 1"},
            {"id": "message-new-2", "type": "assistant_message", "content": "New 2"},
        ]
        
        last_message_id_for_agent = "message-old"
        processed = []
        
        for msg in fetched_messages:
            if last_message_id_for_agent and msg['id'] == last_message_id_for_agent:
                continue
            processed.append(msg)
        
        assert len(processed) == 2  # Both should be processed


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
