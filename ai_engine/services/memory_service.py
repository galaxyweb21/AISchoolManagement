# ai_engine/services/memory_service.py
"""
STEP 2 — School AI Memory.

Gives the AI copilot persistent, explicit memory across conversations:

  - SCHOOL-scope memories: durable facts about how the school itself
    operates (term calendar quirks, reporting chains, standing
    policies) that should inform every user's chat, not just one.

  - USER-scope memories: durable facts about one staff member's
    working style/preferences (e.g. preferred report tone) that
    should only affect that person's chat.

This is intentionally NOT a vector database / embeddings layer — for
a school-scale deployment (a few thousand short memory entries per
school) a keyword + recency + importance ranking is fast, has zero
extra infrastructure, and is easy to audit. If the school later wants
semantic recall over a much larger memory store, `recall()` is the
single place to swap in an embedding-based search without touching
any caller.

Nothing is written to memory silently — every write goes through
`remember()`, so what the AI "knows" about a school is always visible
and editable (see AIMemoryAdmin / the memory management view).
"""

import logging
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

MAX_CONTEXT_MEMORIES = 12
MAX_CONTEXT_CHARS = 2000


class SchoolMemoryService:

    # ------------------------------------------------------------------
    # WRITE
    # ------------------------------------------------------------------

    @staticmethod
    def remember(*, school, content, memory_type="FACT", scope="SCHOOL",
                  user=None, key="", importance=2, source="chat",
                  created_by=None, expires_at=None):
        """
        Store (or update, if `key` already exists for this school/scope/user)
        a memory. Returns the SchoolAIMemory instance.
        """
        from ai_engine.models import SchoolAIMemory

        if scope == "USER" and user is None:
            raise ValueError("USER-scope memories require a `user`.")

        defaults = dict(
            memory_type=memory_type,
            content=content.strip(),
            importance=max(1, min(3, importance)),
            source=source,
            created_by=created_by,
            expires_at=expires_at,
            is_active=True,
        )

        if key:
            memory, _created = SchoolAIMemory.objects.update_or_create(
                school=school,
                scope=scope,
                user=user if scope == "USER" else None,
                key=key,
                defaults=defaults,
            )
            return memory

        return SchoolAIMemory.objects.create(
            school=school,
            scope=scope,
            user=user if scope == "USER" else None,
            key=key,
            **defaults,
        )

    @staticmethod
    def forget(memory_id, *, school=None):
        """Soft-delete a memory (kept for audit, excluded from recall)."""
        from ai_engine.models import SchoolAIMemory
        qs = SchoolAIMemory.objects.filter(pk=memory_id)
        if school is not None:
            qs = qs.filter(school=school)
        return qs.update(is_active=False)

    # ------------------------------------------------------------------
    # READ
    # ------------------------------------------------------------------

    @staticmethod
    def recall(*, school, user=None, scope=None, query="", limit=MAX_CONTEXT_MEMORIES):
        """
        Return active, non-expired memories for this school (and,
        if `user` is given, that user's USER-scope memories too),
        ranked by importance then recency. If `query` is given,
        results are filtered to memories whose content or key contains
        any significant word from the query (simple keyword recall —
        see module docstring).
        """
        from ai_engine.models import SchoolAIMemory

        now = timezone.now()
        qs = SchoolAIMemory.objects.filter(school=school, is_active=True).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=now)
        )

        if scope:
            qs = qs.filter(scope=scope)
        elif user is not None:
            qs = qs.filter(Q(scope="SCHOOL") | Q(scope="USER", user=user))
        else:
            qs = qs.filter(scope="SCHOOL")

        if query:
            words = [w for w in query.lower().split() if len(w) > 3][:6]
            if words:
                word_filter = Q()
                for w in words:
                    word_filter |= Q(content__icontains=w) | Q(key__icontains=w)
                qs = qs.filter(word_filter)

        return list(qs.order_by("-importance", "-updated_at")[:limit])

    @staticmethod
    def get_context_block(*, school, user=None, query=""):
        """
        Build a short, prompt-ready text block of the most relevant
        memories for this school/user, for injection into the AI
        copilot's context (see copilot_context.build_context). Returns
        "" when there is nothing worth injecting, so callers can skip
        the section entirely rather than adding an empty header.
        """
        memories = SchoolMemoryService.recall(school=school, user=user, query=query)
        if not memories:
            return ""

        lines = []
        used = 0
        for m in memories:
            line = f"- ({m.get_memory_type_display()}) {m.content}"
            if used + len(line) > MAX_CONTEXT_CHARS:
                break
            lines.append(line)
            used += len(line)

        if not lines:
            return ""

        return "\n".join(lines)
