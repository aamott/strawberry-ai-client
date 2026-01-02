"""News skill with clear configuration status."""

import logging
import os
from typing import Any, Dict

import requests

logger = logging.getLogger(__name__)


class NewsSkill:
    """Provides news with clear configuration status."""

    def __init__(self):
        self._api_key = os.environ.get("NEWS_API_KEY")
        self._base_url = "https://newsapi.org/v2"

    def get_top_headlines(self, category: str = None, country: str = "us") -> Dict[str, Any]:
        """Get news headlines with configuration check."""
        if not self._api_key:
            return {
                "success": False,
                "error": "News API not configured",
                "message": "Please set NEWS_API_KEY environment variable",
                "documentation": "https://newsapi.org/docs"
            }

        try:
            return self._fetch_news_data(category, country)
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": "News retrieval failed",
                "category": category,
                "country": country,
                "suggested_action": "Verify API key and try again"
            }

    def _fetch_news_data(self, category: str, country: str) -> Dict[str, Any]:
        """Fetch real news data."""
        params = {
            'country': country,
            'apiKey': self._api_key,
            'pageSize': 10
        }

        if category:
            params['category'] = category

        response = requests.get(
            f"{self._base_url}/top-headlines",
            params=params,
            timeout=10
        )
        response.raise_for_status()
        data = response.json()

        if data.get('status') != 'ok':
            raise Exception(f"API error: {data.get('message', 'Unknown error')}")

        return {
            "success": True,
            "articles": [{
                "title": article['title'],
                "description": article['description'],
                "url": article['url'],
                "source": article['source']['name'],
                "published_at": article['publishedAt']
            } for article in data['articles']],
            "source": "NewsAPI",
            "category": category,
            "country": country,
            "count": len(data['articles'])
        }

    def search_news(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """Search for news articles."""
        if not self._api_key:
            return {
                "success": False,
                "error": "News API not configured",
                "message": "Please set NEWS_API_KEY environment variable",
                "documentation": "https://newsapi.org/docs"
            }

        try:
            return self._search_news_data(query, max_results)
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": "News search failed",
                "query": query,
                "suggested_action": "Check API configuration and try again"
            }

    def _search_news_data(self, query: str, max_results: int) -> Dict[str, Any]:
        """Search using NewsAPI."""
        params = {
            'q': query,
            'apiKey': self._api_key,
            'pageSize': min(max_results, 10),
            'sortBy': 'publishedAt'
        }

        response = requests.get(
            f"{self._base_url}/everything",
            params=params,
            timeout=10
        )
        response.raise_for_status()
        data = response.json()

        if data.get('status') != 'ok':
            raise Exception(f"API error: {data.get('message', 'Unknown error')}")

        return {
            "success": True,
            "articles": [{
                "title": article['title'],
                "description": article['description'],
                "url": article['url'],
                "source": article['source']['name'],
                "published_at": article['publishedAt'],
                "relevance": self._calculate_relevance(
                    article["title"] + " " + article["description"],
                    query,
                ),
            } for article in data['articles'][:max_results]],
            "source": "NewsAPI",
            "query": query,
            "count": len(data['articles'])
        }

    def _calculate_relevance(self, text: str, query: str) -> float:
        """Calculate relevance score."""
        text_lower = text.lower()
        query_lower = query.lower()
        query_words = [word.strip() for word in query_lower.split() if word.strip()]

        if not query_words:
            return 0.0

        exact_matches = sum(1 for word in query_words if word in text_lower)
        base_score = exact_matches / len(query_words)

        if query_lower in text_lower[:100]:
            base_score += 0.3
        elif any(word in text_lower[:100] for word in query_words):
            base_score += 0.15

        if exact_matches >= len(query_words):
            base_score += 0.2

        return min(max(base_score, 0.1), 1.0)
