"""Internet search skill with real API integration and proper error handling."""

import requests
import os
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


class InternetSearchSkill:
    """Provides internet search with clear error handling."""

    def __init__(self):
        self._api_key = os.environ.get("GOOGLE_API_KEY")
        self._search_engine_id = os.environ.get("GOOGLE_SEARCH_ENGINE_ID")

    def search_web(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """Search the web with clear status reporting."""
        if not self._api_key or not self._search_engine_id:
            return {
                "success": False,
                "error": "Google search not configured",
                "message": "Please set GOOGLE_API_KEY and GOOGLE_SEARCH_ENGINE_ID environment variables",
                "documentation": "https://developers.google.com/custom-search/v1/overview"
            }

        try:
            return self._perform_google_search(query, max_results)
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": "Google search failed",
                "query": query,
                "suggested_action": "Check API configuration and network connection"
            }

    def _perform_google_search(self, query: str, max_results: int) -> Dict[str, Any]:
        """Perform actual Google search."""
        try:
            url = "https://www.googleapis.com/customsearch/v1"
            params = {
                'key': self._api_key,
                'cx': self._search_engine_id,
                'q': query,
                'num': min(max_results, 10)
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get('error'):
                raise Exception(f"Google API error: {data['error']['message']}")

            return {
                "success": True,
                "results": [{
                    "title": item.get('title', 'No title'),
                    "url": item.get('link', '#'),
                    "snippet": item.get('snippet', 'No description'),
                    "display_link": item.get('displayLink', '')
                } for item in data.get('items', [])],
                "source": "Google Custom Search",
                "query": query,
                "count": len(data.get('items', []))
            }

        except requests.exceptions.RequestException as e:
            raise Exception(f"Search request failed: {str(e)}")
        except Exception as e:
            raise Exception(f"Search error: {str(e)}")