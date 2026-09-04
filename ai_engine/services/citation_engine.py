# ai_engine/services/citation_engine.py
"""
STEP 4 — Official-source citation engine.

Takes whatever grounding knowledge_base.get_grounded_context() found
(curated local documents + live web results, both already restricted
to official Ghana education domains) and turns it into:

  1. A numbered citation list for the AI system prompt, so the model
     can reference "[1]", "[2]" instead of inventing a source.
  2. A clean list of {title, url, source_name} dicts for the JSON
     response — this is exactly the shape templates/ai_engine's chat
     widgets already expect in `data.sources` (see role_command_center.html).

Design rules that make this an actual citation *engine* rather than
just string formatting:
  - Every citation must have a real URL. Nothing is cited without one.
  - Local (human-curated, verified) sources are listed before live
    web results, since they've been vetted.
  - Same URL never appears twice (first/best occurrence wins).
  - When there is nothing to cite, callers get an explicit "no
    grounding available" signal so the answer can say verification is
    needed instead of the model inventing a citation.
"""


def _dedupe_by_url(citations):
    seen = set()
    deduped = []
    for c in citations:
        url = c.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(c)
    return deduped


def build_citations(local_documents=None, live_sources=None, limit=8):
    """
    Merge local KB documents and live web sources into one ordered,
    deduplicated citation list.

    Returns a list of dicts:
        {"title", "url", "source_name", "kind": "local_kb"|"live_web"}
    """
    citations = []

    for doc in (local_documents or []):
        citations.append({
            "title": doc.title,
            "url": doc.source_url,
            "source_name": doc.get_source_name_display(),
            "kind": "local_kb",
        })

    for source in (live_sources or []):
        url = source.get("url")
        if not url:
            continue
        citations.append({
            "title": source.get("title") or url,
            "url": url,
            "source_name": "Live official source",
            "kind": "live_web",
        })

    return _dedupe_by_url(citations)[:limit]


def format_citations_for_prompt(citations):
    """
    Numbered, prompt-ready citation list. The Copilot's system prompt
    should instruct the model to reference these by number and never
    cite anything not in this list.
    """
    if not citations:
        return (
            "No official sources were retrieved for this question. "
            "Do not cite a source. Say clearly that verification against "
            "an official source (GES, NaCCA, MoE or WAEC) is recommended."
        )

    lines = [
        f"[{i}] {c['title']} — {c['source_name']} ({c['url']})"
        for i, c in enumerate(citations, start=1)
    ]
    return (
        "AVAILABLE OFFICIAL SOURCES (cite by number, e.g. '[1]', when you "
        "use one of these; never cite a source not listed here):\n"
        + "\n".join(lines)
    )


def format_citations_for_response(citations):
    """
    The shape the chat UI already expects in `sources` (see
    role_command_center.html: `s.title`, `s.url`).
    """
    return [{"title": c["title"], "url": c["url"]} for c in citations]
