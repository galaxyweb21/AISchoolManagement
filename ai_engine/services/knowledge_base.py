# ai_engine/services/knowledge_base.py
"""
STEP 3 — Ghana Education RAG / Knowledge Base.

This is the retrieval half of retrieval-augmented generation for
Ghana-education questions. It is deliberately simple and offline:

  - `GhanaEducationKnowledgeDocument` (ai_engine.models) holds curated,
    human-verified excerpts, each tied to a real official source
    (GES/NaCCA/MoE/WAEC) via source_name + source_url.
  - `search_local()` does keyword ranking over that table — fast, free,
    and works even when no live-research API key is configured.
  - `get_grounded_context()` is the single function the Copilot engine
    calls: it searches the local library first (vetted, stable), and
    only reaches for live web research (research_service, official
    domains only) when the local library doesn't have enough to say,
    or the question looks time-sensitive (dates, "latest", "current").

Nothing here invents facts: if neither local documents nor live
research return anything relevant, `get_grounded_context()` says so
explicitly, and the citation engine (Step 4) will not fabricate a
source for that answer.
"""

import logging

from django.db.models import Q

logger = logging.getLogger(__name__)

TIME_SENSITIVE_TERMS = (
    "latest", "current", "this year", "deadline", "registration date",
    "when is", "when does", "what date", "circular", "new policy",
    "recently", "update",
)


def _is_time_sensitive(question):
    text = (question or "").lower()
    return any(term in text for term in TIME_SENSITIVE_TERMS)


def search_local(query, domain=None, limit=5):
    """
    Keyword-ranked search over the curated local knowledge library.
    Returns a list of GhanaEducationKnowledgeDocument, best match first.
    """
    from ai_engine.models import GhanaEducationKnowledgeDocument

    if not query:
        return []

    qs = GhanaEducationKnowledgeDocument.objects.filter(is_active=True)
    if domain:
        qs = qs.filter(domain=domain)

    words = [w for w in str(query).lower().split() if len(w) > 2][:8]
    if not words:
        return []

    match_filter = Q()
    for w in words:
        match_filter |= Q(title__icontains=w) | Q(content__icontains=w) | Q(domain__icontains=w)
    qs = qs.filter(match_filter)

    # Rank in Python: count how many distinct query words actually hit
    # each document, favouring documents that match more of the query
    # over documents that happen to repeat one word many times.
    scored = []
    for doc in qs[:200]:
        haystack = f"{doc.title} {doc.content} {doc.domain}".lower()
        score = sum(1 for w in words if w in haystack)
        if score:
            scored.append((score, doc))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [doc for _score, doc in scored[:limit]]


def get_grounded_context(question, domain=None, allow_live=True):
    """
    The single retrieval entry point for the Copilot engine.

    Returns:
        {
            "local_documents": [GhanaEducationKnowledgeDocument, ...],
            "live_sources": [{"title", "url", "snippet"}, ...],
            "live_attempted": bool,
            "has_grounding": bool,
        }
    """
    local_documents = search_local(question, domain=domain, limit=5)

    live_sources = []
    live_attempted = False

    needs_live = allow_live and (
        _is_time_sensitive(question) or len(local_documents) == 0
    )

    if needs_live:
        try:
            from ai_engine.services.research_service import EducationResearchService
            live_attempted = True
            research = EducationResearchService.research(question)
            live_sources = research.get("sources", []) if research.get("live") else []
        except Exception:
            logger.exception("Live research lookup failed for grounded context")

    return {
        "local_documents": local_documents,
        "live_sources": live_sources,
        "live_attempted": live_attempted,
        "has_grounding": bool(local_documents or live_sources),
    }


def format_local_documents_for_prompt(documents):
    """Render local KB documents as numbered, prompt-ready text blocks."""
    if not documents:
        return ""
    blocks = []
    for i, doc in enumerate(documents, start=1):
        verified = f", verified {doc.last_verified_at}" if doc.last_verified_at else ""
        blocks.append(
            f"[{i}] {doc.title} ({doc.get_source_name_display()}{verified})\n{doc.content}"
        )
    return "\n\n".join(blocks)
