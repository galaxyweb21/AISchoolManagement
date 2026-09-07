# ai_engine/views/copilot.py

"""
AI School Copilot views.

Responsibilities:
    - Render the Copilot UI.
    - Securely load conversations for the current user/school.
    - Securely load conversation messages.
    - Securely delete conversations.
    - Create new conversations when the browser sends a stale ID.
    - Pass chat requests to SchoolCopilotEngine.
    - Persist user/assistant messages.
    - Persist AI audit records.

Conversation security boundary:

    school + authenticated user + conversation id

IMPORTANT:

The frontend can legitimately hold a stale conversation ID.

For example:

    1. User opens conversation A.
    2. Conversation A is deleted in another tab/session.
    3. Browser still has conversation A selected.
    4. User sends another message.

The API must NOT break the Copilot in this situation.

Instead, the stale conversation is treated as a request
to start a fresh conversation.
"""

import json
import logging
import time
import uuid

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from ai_engine.models import AIConversation, AIMessage, AIRequest
from ai_engine.services.copilot_engine import SchoolCopilotEngine


logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

COPILOT_MODEL_NAME = "openai/gpt-oss-120b"  # llama-3.3-70b-versatile was retired by Groq on 08/16/26

MAX_HISTORY_MESSAGES = 8

MAX_CONVERSATION_TITLE_LENGTH = 80

MAX_CONVERSATIONS_ON_PAGE = 30

MAX_QUESTION_LENGTH = 4000


# =============================================================================
# BASIC HELPERS
# =============================================================================

def _get_school(request):
    """
    Safely return the school attached to the authenticated user.
    """
    return getattr(request.user, "school", None)


def _json_error(message, status=400, **extra):
    """
    Consistent JSON error response.
    """
    payload = {
        "success": False,
        "error": str(message),
    }

    payload.update(extra)

    return JsonResponse(
        payload,
        status=status,
    )


def _json_success(**data):
    """
    Consistent JSON success response.
    """
    payload = {
        "success": True,
    }

    payload.update(data)

    return JsonResponse(payload)


def _normalise_uuid(value):
    """
    Safely normalize a UUID supplied by the browser.

    Returns:
        UUID instance or None.

    Invalid/stale IDs are intentionally treated as None so the
    Copilot can recover instead of crashing.
    """

    if value in (None, "", "null", "undefined"):
        return None

    try:
        return uuid.UUID(str(value))
    except (
        ValueError,
        TypeError,
        AttributeError,
    ):
        return None


def _conversation_queryset(request):
    """
    SINGLE authorization boundary for Copilot conversations.

    A user can only access conversations belonging to:

        - their current school
        - their own user account
        - non-archived conversations

    Never bypass this helper for normal conversation access.
    """

    school = _get_school(request)

    if not school:
        return AIConversation.objects.none()

    return (
        AIConversation.objects
        .filter(
            school=school,
            user=request.user,
            is_archived=False,
        )
    )


def _get_conversation(request, conversation_id):
    """
    Safely retrieve an authorized conversation.

    Returns:
        AIConversation or None

    Invalid UUIDs and missing conversations both return None.
    """

    normalized_id = _normalise_uuid(
        conversation_id
    )

    if not normalized_id:
        return None

    return (
        _conversation_queryset(request)
        .filter(
            id=normalized_id,
        )
        .first()
    )


def _create_conversation(
    request,
    school,
    title="",
):
    """
    Create a new conversation owned by the current user
    and school.
    """

    clean_title = (
        str(title or "").strip()
        [:MAX_CONVERSATION_TITLE_LENGTH]
    )

    return AIConversation.objects.create(
        school=school,
        user=request.user,
        title=clean_title,
    )


def _conversation_title(question):
    """
    Build a clean initial conversation title.
    """

    title = (
        str(question or "")
        .strip()
        .replace("\r", " ")
        .replace("\n", " ")
    )

    title = " ".join(
        title.split()
    )

    if not title:
        return "New conversation"

    if len(title) <= MAX_CONVERSATION_TITLE_LENGTH:
        return title

    words = title.split()

    shortened = " ".join(
        words[:10]
    ).strip()

    if len(shortened) > 70:
        shortened = shortened[:70].rstrip()

    return shortened + "..."


# =============================================================================
# COPILOT PAGE
# =============================================================================

@login_required
@require_GET
def ai_copilot_page(request):
    """
    Render the AI School Copilot.

    Only the current user's conversations for the current
    school are displayed.
    """

    school = _get_school(request)

    if not school:
        return render(
            request,
            "ai_engine/copilot.html",
            {
                "conversations": AIConversation.objects.none(),
                "staff_profile": None,
                "active_tab": "ai",
                "copilot_access_error": (
                    "Your account is not linked to a school."
                ),
            },
        )

    conversations = (
        _conversation_queryset(request)
        .prefetch_related("messages")
        .order_by(
            "-updated_at",
            "-id",
        )[:MAX_CONVERSATIONS_ON_PAGE]
    )

    try:
        from staff.models import StaffProfile

        staff_profile = (
            StaffProfile.objects
            .filter(
                user=request.user,
                school=school,
            )
            .select_related(
                "staff_grade",
                "department",
            )
            .first()
        )

    except Exception:
        logger.exception(
            "Could not load StaffProfile for Copilot user %s.",
            request.user.pk,
        )

        staff_profile = None

    return render(
        request,
        "ai_engine/copilot.html",
        {
            "conversations": conversations,
            "staff_profile": staff_profile,
            "active_tab": "ai",
            "copilot_access_error": None,
        },
    )


# =============================================================================
# LOAD CONVERSATION
# =============================================================================

@login_required
@require_GET
def get_conversation_messages(
    request,
    conversation_id,
):
    """
    Return messages for an authorized conversation.

    A missing conversation returns 404.

    The frontend is responsible for treating that 404 as a
    stale conversation and resetting itself.
    """

    school = _get_school(request)

    if not school:
        return _json_error(
            "Your account is not linked to a school.",
            403,
        )

    normalized_id = _normalise_uuid(
        conversation_id
    )

    if not normalized_id:
        return _json_error(
            "Conversation not found.",
            404,
            conversation_id=str(
                conversation_id or ""
            ),
            stale_conversation=True,
        )

    conversation = (
        _conversation_queryset(request)
        .filter(
            id=normalized_id,
        )
        .first()
    )

    if conversation is None:
        return _json_error(
            "Conversation not found.",
            404,
            conversation_id=str(
                normalized_id
            ),
            stale_conversation=True,
        )

    try:

        messages = (
            conversation.messages
            .order_by(
                "created_at",
                "id",
            )
            .values(
                "id",
                "role",
                "content",
                "created_at",
            )
        )

        formatted = []

        for message in messages:

            role = message.get(
                "role"
            )

            if role == "USER":
                ui_role = "user"

            elif role == "AI":
                ui_role = "assistant"

            else:
                continue

            formatted.append(
                {
                    "id": str(
                        message["id"]
                    ),
                    "role": ui_role,
                    "content": (
                        message["content"]
                        or ""
                    ),
                    "created_at": (
                        message["created_at"].isoformat()
                        if message["created_at"]
                        else None
                    ),
                }
            )

        return _json_success(
            conversation_id=str(
                conversation.id
            ),
            title=(
                conversation.title
                or "Conversation"
            ),
            messages=formatted,
            count=len(formatted),
        )

    except Exception:

        logger.exception(
            "Failed loading Copilot conversation %s for user %s.",
            normalized_id,
            request.user.pk,
        )

        return _json_error(
            "The conversation could not be loaded. Please try again.",
            500,
        )


# =============================================================================
# DELETE CONVERSATION
# =============================================================================

@login_required
@require_POST
def delete_conversation(
    request,
    conversation_id,
):
    """
    Permanently delete one conversation belonging to the
    authenticated user and current school.

    Deleting a conversation also deletes its messages because
    AIMessage.conversation uses CASCADE.
    """

    school = _get_school(request)

    if not school:
        return _json_error(
            "Your account is not linked to a school.",
            403,
        )

    normalized_id = _normalise_uuid(
        conversation_id
    )

    if not normalized_id:
        # From the UI perspective, an already-invalid conversation
        # is effectively already deleted.
        return _json_success(
            conversation_id=str(
                conversation_id or ""
            ),
            deleted=True,
            already_missing=True,
            message="Conversation was already removed.",
        )

    try:

        conversation = (
            _conversation_queryset(request)
            .filter(
                id=normalized_id,
            )
            .first()
        )

        if conversation is None:

            # IMPORTANT:
            #
            # If another tab already deleted it,
            # do not make the UI think deletion failed.
            return _json_success(
                conversation_id=str(
                    normalized_id
                ),
                deleted=True,
                already_missing=True,
                message="Conversation was already removed.",
            )

        conversation.delete()

        return _json_success(
            conversation_id=str(
                normalized_id
            ),
            deleted=True,
            already_missing=False,
            message="Conversation deleted successfully.",
        )

    except Exception:

        logger.exception(
            "Failed deleting Copilot conversation %s for user %s.",
            normalized_id,
            request.user.pk,
        )

        return _json_error(
            "The conversation could not be deleted. Please try again.",
            500,
        )


# =============================================================================
# MAIN COPILOT API
# =============================================================================

@login_required
@require_POST
def ai_copilot_api(request):
    """
    Main conversational API.

    IMPORTANT RECOVERY BEHAVIOUR:

    If the browser sends a conversation ID which no longer
    exists, we DO NOT return an error.

    Instead:

        stale conversation ID
                ↓
        create new conversation
                ↓
        process question normally
                ↓
        return new conversation ID

    This makes the Copilot resilient to:
        - deleted conversations
        - archived conversations
        - stale browser state
        - multiple tabs
        - expired pages
        - malformed conversation IDs
    """

    started = time.monotonic()

    school = None
    conversation = None
    question = ""

    try:

        # =================================================================
        # PARSE REQUEST
        # =================================================================

        try:

            raw_body = request.body or b"{}"

            if isinstance(
                raw_body,
                bytes,
            ):
                raw_body = raw_body.decode(
                    "utf-8",
                    errors="replace",
                )

            data = json.loads(
                raw_body
            )

        except (
            json.JSONDecodeError,
            UnicodeDecodeError,
            TypeError,
            ValueError,
        ):

            return _json_error(
                "Invalid JSON format received.",
                400,
            )

        if not isinstance(
            data,
            dict,
        ):
            return _json_error(
                "Invalid request payload.",
                400,
            )

        question = (
            str(
                data.get("question")
                or ""
            )
            .strip()
        )

        requested_conversation_id = (
            data.get("conversation_id")
        )

        # =================================================================
        # VALIDATE QUESTION
        # =================================================================

        if not question:
            return _json_error(
                "Please provide a question.",
                400,
            )

        if len(question) > MAX_QUESTION_LENGTH:
            return _json_error(
                (
                    "Your question is too long. "
                    "Please keep it below 4,000 characters."
                ),
                400,
            )

        # =================================================================
        # SCHOOL SECURITY
        # =================================================================

        school = _get_school(request)

        if not school:
            return _json_error(
                "Your account is not linked to a school.",
                403,
            )

        # =================================================================
        # FIND EXISTING CONVERSATION
        # =================================================================

        normalized_conversation_id = (
            _normalise_uuid(
                requested_conversation_id
            )
        )

        if normalized_conversation_id:

            conversation = (
                _conversation_queryset(request)
                .filter(
                    id=normalized_conversation_id,
                )
                .first()
            )

            if conversation is None:

                logger.info(
                    (
                        "Stale Copilot conversation detected. "
                        "Creating a new conversation. "
                        "user=%s school=%s old_conversation=%s"
                    ),
                    request.user.pk,
                    school.pk,
                    normalized_conversation_id,
                )

                conversation = None

        # =================================================================
        # CREATE NEW CONVERSATION
        # =================================================================

        if conversation is None:

            conversation = _create_conversation(
                request=request,
                school=school,
                title=_conversation_title(
                    question
                ),
            )

        # =================================================================
        # LOAD HISTORY
        # =================================================================

        history_rows = list(
            conversation.messages
            .order_by(
                "-created_at",
                "-id",
            )
            .values(
                "role",
                "content",
            )[
                :MAX_HISTORY_MESSAGES
            ]
        )

        history_rows.reverse()

        history = []

        for row in history_rows:

            role = row.get(
                "role"
            )

            content = (
                str(
                    row.get("content")
                    or ""
                )
                .strip()
            )

            if not content:
                continue

            if role == "USER":
                history_role = "user"

            elif role == "AI":
                history_role = "assistant"

            else:
                continue

            history.append(
                {
                    "role": history_role,
                    "content": content,
                }
            )

        # =================================================================
        # SAVE USER MESSAGE
        # =================================================================

        AIMessage.objects.create(
            conversation=conversation,
            role="USER",
            content=question,
        )

        # =================================================================
        # RUN AI ENGINE
        # =================================================================

        engine = SchoolCopilotEngine(
            request.user
        )

        result = engine.answer(
            school=school,
            question=question,
            history=history,
        )

        elapsed = (
            time.monotonic()
            - started
        )

        # =================================================================
        # NORMALIZE ENGINE RESPONSE
        # =================================================================

        if isinstance(
            result,
            dict,
        ):

            answer = str(
                result.get("answer")
                or ""
            ).strip()

            mode = (
                result.get("mode")
                or "chat"
            )

            sources = (
                result.get("sources")
                or []
            )

            scope = result.get(
                "scope"
            )

            role = result.get(
                "role"
            )

        else:

            answer = str(
                result or ""
            ).strip()

            mode = "chat"
            sources = []
            scope = None
            role = None

        # =================================================================
        # EMPTY AI RESPONSE
        # =================================================================

        if not answer:

            logger.warning(
                (
                    "Copilot returned an empty answer. "
                    "user=%s school=%s question=%r"
                ),
                request.user.pk,
                school.pk,
                question[:300],
            )

            answer = (
                "I could not generate a complete answer "
                "for that question. Please try again."
            )

            mode = "error"

        # =================================================================
        # SAVE ASSISTANT RESPONSE
        # =================================================================

        AIMessage.objects.create(
            conversation=conversation,
            role="AI",
            content=answer,
            execution_time=elapsed,
            model_name=COPILOT_MODEL_NAME,
        )

        # =================================================================
        # UPDATE TITLE
        # =================================================================

        if not conversation.title:

            conversation.title = (
                _conversation_title(
                    question
                )
            )

        # Improve a long first-question title.
        if (
            len(
                conversation.title
                or ""
            ) > 55
            and conversation.messages.count() <= 2
        ):

            improved_title = (
                _conversation_title(
                    question
                )
            )

            if improved_title:
                conversation.title = improved_title

        conversation.updated_at = (
            timezone.now()
        )

        conversation.save(
            update_fields=[
                "title",
                "updated_at",
            ]
        )

        # =================================================================
        # AI AUDIT
        # =================================================================

        try:

            AIRequest.objects.create(
                school=school,
                user=request.user,
                engine="GENERAL",
                prompt=question,
                response=answer,
                model_name=COPILOT_MODEL_NAME,
                execution_time=elapsed,
                status="SUCCESS",
            )

        except Exception:

            logger.exception(
                "Failed to save AIRequest audit record."
            )

        # =================================================================
        # RESPONSE
        # =================================================================

        return _json_success(
            answer=answer,
            mode=mode,
            sources=(
                sources
                if isinstance(
                    sources,
                    list,
                )
                else []
            ),
            scope=scope,
            role=role,
            conversation_id=str(
                conversation.id
            ),
            conversation_title=(
                conversation.title
                or "Conversation"
            ),
            recovered_from_stale_conversation=(
                bool(
                    normalized_conversation_id
                    and normalized_conversation_id
                    != conversation.id
                )
            ),
        )

    except Exception:

        elapsed = (
            time.monotonic()
            - started
        )

        logger.exception(
            (
                "AI School Copilot error. "
                "user=%s school=%s question=%r"
            ),
            getattr(
                request.user,
                "pk",
                None,
            ),
            getattr(
                school,
                "pk",
                None,
            ),
            question[:300],
        )

        # ==============================================================
        # FAILED AUDIT
        # ==============================================================

        try:

            if school and question:

                AIRequest.objects.create(
                    school=school,
                    user=request.user,
                    engine="GENERAL",
                    prompt=question,
                    response="",
                    model_name=COPILOT_MODEL_NAME,
                    execution_time=elapsed,
                    status="FAILED",
                )

        except Exception:

            logger.exception(
                "Failed to save failed AIRequest audit record."
            )

        return _json_error(
            (
                "The AI School Copilot could not "
                "process your request. Please try again."
            ),
            500,
        )