"""Optional live research adapter for AI School Copilot.

Tavily is optional. If no key is configured, the Copilot still answers using
its Ghana education knowledge guardrails, but it must not claim to have done
live web research.
"""

import requests
from django.conf import settings

from .ghana_education import OFFICIAL_SOURCES


class EducationResearchService:
    ENDPOINT = "https://api.tavily.com/search"

    @classmethod
    def research(cls, question):
        api_key = getattr(settings, "TAVILY_API_KEY", "")
        if not api_key:
            return {
                "live": False,
                "sources": [],
                "context": "No live research provider is configured. Use the Copilot's built-in Ghana education knowledge, and explicitly say when a current official source needs verification.",
            }

        try:
            response = requests.post(
                cls.ENDPOINT,
                json={
                    "api_key": api_key,
                    "query": question,
                    "search_depth": "advanced",
                    "max_results": 5,
                    "include_answer": False,
                    "include_raw_content": False,
                    "include_domains": [
                        "ges.gov.gh",
                        "nacca.gov.gh",
                        "moe.gov.gh",
                        "waecgh.org",
                    ],
                },
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
            results = data.get("results", [])
            sources = [
                {
                    "title": item.get("title", "Official source"),
                    "url": item.get("url", ""),
                    "snippet": item.get("content", "")[:1200],
                }
                for item in results
                if item.get("url")
            ]
            context = "\n\n".join(
                f"SOURCE: {s['title']}\nURL: {s['url']}\nCONTENT: {s['snippet']}"
                for s in sources
            )
            return {"live": True, "sources": sources, "context": context}
        except Exception:
            return {
                "live": False,
                "sources": [],
                "context": "Live official-source research was unavailable for this request. Do not claim that current web research was completed.",
            }
