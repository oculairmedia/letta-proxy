"""
Pytest configuration for poller tests.
"""
import sys
from unittest.mock import MagicMock, patch

# Create mock for config module
mock_config = MagicMock()
mock_graphiti = MagicMock()
mock_graphiti.add_messages.return_value = True
mock_config.init_graphiti.return_value = mock_graphiti

# Insert mock before any imports
sys.modules['config'] = mock_config

# Also patch requests at module level to prevent any actual HTTP calls
import requests
original_get = requests.get

def safe_get(*args, **kwargs):
    """Fail-safe that prevents real HTTP calls during tests."""
    raise RuntimeError(f"Unmocked HTTP GET call to {args}")

# We don't apply this globally - tests should mock explicitly
