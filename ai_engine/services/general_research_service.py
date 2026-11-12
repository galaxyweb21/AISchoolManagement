"""General live web-research adapter for EduAI Copilot.

Tavily is optional. When TAVILY_API_KEY is configured, this service performs
broad web research for staff/student research questions. When it is not
configured, the Copilot falls back to its language model and clearly avoids
claiming that live web research was completed.
"""

import requests
from django.conf import settings


class GeneralResearchService:
    ENDPOINT = "https://api.tavily.com/search"

    @classmethod
    def research(cls, question):
        api_key = (
            getattr(settings, "TAVILY_API_KEY", "")
            or ""
        ).strip()

        if not api_key:
            return {
                "live": False,
                "sources": [],
                "context": (
                    "No live web research provider is configured. "
                    "Answer from the model's knowledge, and do not claim "
                    "that current web research was completed."
                ),
            }

        try:
            response = requests.post(
                cls.ENDPOINT,
                json={
                    "api_key": api_key,
                    "query": str(question).strip(),
                    "search_depth": "advanced",
                    "max_results": 7,
                    "include_answer": False,
                    "include_raw_content": False,
                },
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()
            results = data.get("results", []) or []

            sources = []
            for item in results:
                url = item.get("url")
                if not url:
                    continue
                sources.append({
                    "title": item.get("title") or "Web source",
                    "url": url,
                    "snippet": (item.get("content") or "")[:1800],
                })

            context = "\n\n".join(
                "SOURCE: {title}\nURL: {url}\nCONTENT: {snippet}".format(**source)
                for source in sources
            )

            return {
                "live": bool(sources),
                "sources": sources,
                "context": context or (
                    "The web research provider returned no usable sources. "
                    "Do not claim that current web research was completed."
                ),
            }

        except Exception as exc:
            return {
                "live": False,
                "sources": [],
                "context": (
                    "Live web research was unavailable for this request. "
                    "Do not claim that current web research was completed."
                ),
                "error": str(exc)[:300],
            }
