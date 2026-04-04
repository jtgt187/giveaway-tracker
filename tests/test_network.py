"""Tests for utils/network.py -- HTTP header generation and delay utilities.

Covers:
  - get_random_headers (User-Agent rotation, Referer inclusion)
  - random_delay (delay range, sleep call)
"""

from unittest.mock import patch

import pytest


# ===========================================================================
# get_random_headers
# ===========================================================================

class TestGetRandomHeaders:
    def test_returns_dict(self):
        from utils.network import get_random_headers
        headers = get_random_headers()
        assert isinstance(headers, dict)

    def test_contains_required_keys(self):
        from utils.network import get_random_headers
        headers = get_random_headers()
        assert "User-Agent" in headers
        assert "Accept" in headers
        assert "Accept-Language" in headers
        assert "Connection" in headers

    def test_user_agent_from_pool(self):
        from utils.network import get_random_headers, _USER_AGENTS
        headers = get_random_headers()
        assert headers["User-Agent"] in _USER_AGENTS

    def test_referer_included_when_provided(self):
        from utils.network import get_random_headers
        headers = get_random_headers(referer="https://example.com")
        assert headers["Referer"] == "https://example.com"

    def test_referer_absent_when_not_provided(self):
        from utils.network import get_random_headers
        headers = get_random_headers()
        assert "Referer" not in headers

    def test_does_not_mutate_common_headers(self):
        from utils.network import get_random_headers, COMMON_HEADERS
        original_keys = set(COMMON_HEADERS.keys())
        get_random_headers(referer="https://example.com")
        assert set(COMMON_HEADERS.keys()) == original_keys
        assert "Referer" not in COMMON_HEADERS

    def test_multiple_calls_may_differ(self):
        """User-Agent should be randomly selected (may vary across calls)."""
        from utils.network import get_random_headers
        agents = {get_random_headers()["User-Agent"] for _ in range(50)}
        # With 5 agents and 50 calls, we should see at least 2 different ones
        assert len(agents) >= 2


# ===========================================================================
# random_delay
# ===========================================================================

class TestRandomDelay:
    @patch("utils.network.time.sleep")
    def test_returns_value_in_range(self, mock_sleep):
        from utils.network import random_delay
        delay = random_delay(1, 5)
        assert 1.0 <= delay <= 5.0
        mock_sleep.assert_called_once_with(delay)

    @patch("utils.network.time.sleep")
    def test_default_args(self, mock_sleep):
        from utils.network import random_delay
        delay = random_delay()
        assert 3.0 <= delay <= 10.0
        mock_sleep.assert_called_once()

    @patch("utils.network.time.sleep")
    def test_custom_range(self, mock_sleep):
        from utils.network import random_delay
        delay = random_delay(0, 1)
        assert 0.0 <= delay <= 1.0

    @patch("utils.network.time.sleep")
    def test_accepts_string_numbers(self, mock_sleep):
        """min/max are cast via float(), so string numbers should work."""
        from utils.network import random_delay
        delay = random_delay("2", "6")
        assert 2.0 <= delay <= 6.0
