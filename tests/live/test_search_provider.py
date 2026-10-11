import os

import pytest
from pydantic import SecretStr

from gridlens.providers.tavily import TavilySearchProvider


@pytest.mark.live
def test_explicit_tavily_smoke():
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key:
        pytest.skip("TAVILY_API_KEY is not configured")
    results = TavilySearchProvider(SecretStr(key)).search("New Zealand grid connection policy", 3)
    assert len(results) <= 3
