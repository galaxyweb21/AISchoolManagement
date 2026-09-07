"""
Universal School Context
========================

Safe, tenant-aware context provider for the AI School Copilot.

IMPORTANT DESIGN PRINCIPLE
--------------------------

The LLM must NEVER receive raw Django model dumps.

This module therefore converts database information into:

    - facts
    - metrics
    - counts
    - percentages
    - date ranges
    - human-readable summaries
    - carefully selected evidence

It does NOT send arbitrary model rows to the LLM.

The database remains the source of truth.

The LLM is responsible for explaining the facts, not calculating
basic database facts from raw records.

Security principles:

    1. School is the tenant boundary.
    2. Role policy is the authorization boundary.
    3. Sensitive fields are excluded.
    4. Authentication/internal AI models are excluded.
    5. Face embeddings are NEVER exposed.
    6. IDs are NEVER exposed to the LLM.
    7. Raw model dumps are NEVER exposed.
    8. Database aggregation happens before LLM generation.
    9. New school models can be discovered dynamically.
   10. Question-specific routing prevents irrelevant data from entering
       the prompt.
"""

import logging
import re

from datetime import date, datetime, timedelta
from decimal import Decimal

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.db.models import (
    Model,
    Count,
    Q,
    Avg,
    Sum,
)

from .role_ai_policy import can_use


logger = logging.getLogger(__name__)


# ============================================================================
# LIMITS
# ============================================================================

MAX_MODELS = 12
MAX_FACTS = 80
MAX_EVIDENCE_ITEMS = 30
MAX_CONTEXT_CHARS = 30000
MAX_MODEL_CATALOG = 500

# We deliberately keep this low.
# The LLM should receive summaries, not database dumps.
MAX_DISPLAY_TEXT = 180


# ============================================================================
# BLOCKED MODELS
# ============================================================================

BLOCKED_MODEL_NAMES = {
    # Authentication
    "user",
    "permission",
    "group",
    "role",
    "rolepermission",
    "usersession",
    "session",

    # Django internals
    "logentry",
    "contenttype",

    # Activity/audit internals
    "activitylog",
    "notificationlog",

    # AI internals
    "aiconversation",
    "aimessage",
    "airequest",
    "aitask",
    "aiactivity",
    "aiconfiguration",
    "toolexecutionlog",
    "schoolaimemory",
    "airouter",
    "aiprompt",
    "aipromptlog",
    "aicache",

    # Security
    "passwordreset",
    "passwordresettoken",
    "emailverification",
    "emailverificationtoken",
}


BLOCKED_APP_LABELS = {
    "auth",
    "contenttypes",
    "sessions",
    "admin",
}


# ============================================================================
# SENSITIVE FIELDS
# ============================================================================

SENSITIVE_FIELD_NAMES = {
    "password",
    "password_hash",
    "token",
    "secret",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "private_key",
    "security_answer",
    "security_question",
    "default_password",

    # Financial/security information
    "account_number",
    "bank_account",
    "bank_account_number",
    "card_number",
    "cvv",
    "pin",

    # Government identity
    "id_card_number",
    "ghana_card_number",
    "national_id",
    "passport_number",

    # Biometric information
    "face_encoding",
    "face_embedding",
    "embedding",
    "biometric",
    "fingerprint",
    "fingerprint_data",

    # Private files
    "private_file",
    "private_document",
}


SENSITIVE_FIELD_PARTS = {
    "password",
    "token",
    "secret",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "private_key",
    "security_answer",
    "security_question",
    "face_encoding",
    "face_embedding",
    "embedding",
    "fingerprint",
    "biometric",
    "cvv",
    "pin",
}


# ============================================================================
# CAPABILITIES
# ============================================================================

CAPABILITY_BY_APP = {
    "students": "students",
    "attendance": "attendance",
    "assessments": "academics",
    "academics": "academics",
    "finance": "finance",
    "staff": "staff",
    "library": "school_intelligence",
    "communication": "school_intelligence",
    "school": "school_intelligence",
    "ai_engine": "school_intelligence",
    "core": "school_intelligence",
}


# ============================================================================
# COMMON SCHOOL RELATION PATHS
# ============================================================================

COMMON_SCHOOL_PATHS = (
    "school",
    "student__school",
    "staff__school",
    "teacher__school",
    "school_class__school",
    "assessment__school",
    "invoice__school",
    "payment__school",
    "payroll_period__school",
    "payroll_run__school",
    "leave_type__school",
    "staff_grade__school",
    "book__school",
    "borrowing__school",
    "academic_term__school",
    "academic_year__school",
    "department__school",
    "subject__school",
    "timetable__school",
    "room__school",
    "grade_level__school",
    "promotion_batch__school",
    "student_promotion__school",
)


# ============================================================================
# QUESTION ALIASES
# ============================================================================

ALIASES = {

    "students": {
        "student",
        "students",
        "learner",
        "learners",
        "pupil",
        "pupils",
        "children",
    },

    "staff": {
        "staff",
        "teacher",
        "teachers",
        "employee",
        "employees",
        "personnel",
        "hod",
        "head teacher",
        "headteacher",
    },

    "attendance": {
        "attendance",
        "attend",
        "absent",
        "absence",
        "present",
        "late",
        "lateness",
        "punctuality",
    },

    "academics": {
        "class",
        "classes",
        "subject",
        "subjects",
        "timetable",
        "teacher assignment",
        "promotion",
        "academic",
        "academic year",
        "academic term",
    },

    "assessments": {
        "assessment",
        "assessments",
        "grade",
        "grades",
        "mark",
        "marks",
        "score",
        "scores",
        "result",
        "results",
        "exam",
        "exams",
        "test",
        "tests",
        "performance",
    },

    "finance": {
        "fee",
        "fees",
        "invoice",
        "invoices",
        "payment",
        "payments",
        "finance",
        "financial",
        "arrears",
        "balance",
        "ledger",
        "billing",
        "transport",
        "revenue",
        "income",
        "expense",
        "expenses",
    },

    "staff_hr": {
        "leave",
        "leaves",
        "on leave",
        "payroll",
        "salary",
        "salaries",
        "allowance",
        "deduction",
        "department",
        "employment",
        "contract",
    },

    "library": {
        "book",
        "books",
        "library",
        "borrow",
        "borrowing",
        "borrowed",
        "overdue",
    },

    "communication": {
        "announcement",
        "announcements",
        "notification",
        "notifications",
        "message",
        "messages",
    },

    "school": {
        "school",
        "term",
        "academic year",
        "academic term",
        "calendar",
        "session",
    },
}


# ============================================================================
# TEXT HELPERS
# ============================================================================

def _normalize(value):
    value = str(value or "").lower()
    value = re.sub(r"[^a-z0-9_\s-]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _model_label(model):
    return "{}.{}".format(
        model._meta.app_label,
        model.__name__,
    )


def _field_is_sensitive(field_name):
    name = _normalize(field_name).replace(" ", "_")

    if name in SENSITIVE_FIELD_NAMES:
        return True

    for part in SENSITIVE_FIELD_PARTS:
        if part in name:
            return True

    return False


def _model_blocked(model):
    if model._meta.app_label.lower() in BLOCKED_APP_LABELS:
        return True

    return model.__name__.lower() in BLOCKED_MODEL_NAMES


def _safe_text(value, maximum=MAX_DISPLAY_TEXT):
    if value is None:
        return None

    try:
        value = str(value)
    except Exception:
        return None

    value = re.sub(r"\s+", " ", value).strip()

    if len(value) > maximum:
        return value[:maximum] + "..."

    return value


# ============================================================================
# MODEL CAPABILITY
# ============================================================================

def _capability_for_model(model):
    app_label = model._meta.app_label.lower()
    model_name = model.__name__.lower()

    if _model_blocked(model):
        return None

    if app_label in CAPABILITY_BY_APP:
        return CAPABILITY_BY_APP[app_label]

    # Unknown first-party models are treated as school intelligence,
    # but only when they can be proven to belong to this school.
    return "school_intelligence"


# ============================================================================
# SCHOOL RELATION DISCOVERY
# ============================================================================

def _find_school_paths(model):
    """
    Find safe ORM paths from a model to School.

    Example:

        Attendance -> Student -> School

    becomes:

        student__school
    """

    paths = []

    # ------------------------------------------------------------------
    # Direct school FK
    # ------------------------------------------------------------------

    try:
        field = model._meta.get_field("school")

        if getattr(field, "is_relation", False):
            paths.append("school")

    except FieldDoesNotExist:
        pass

    # ------------------------------------------------------------------
    # Known project paths
    # ------------------------------------------------------------------

    for path in COMMON_SCHOOL_PATHS:

        current = model
        valid = True

        for bit in path.split("__"):

            try:
                field = current._meta.get_field(bit)

            except FieldDoesNotExist:
                valid = False
                break

            if not getattr(field, "is_relation", False):
                valid = False
                break

            current = field.remote_field.model

        if (
            valid
            and getattr(current._meta, "model_name", "") == "school"
        ):
            paths.append(path)

    # ------------------------------------------------------------------
    # Dynamic relationship discovery
    # ------------------------------------------------------------------

    visited = {model}
    frontier = [(model, [])]

    for _ in range(3):

        next_frontier = []

        for current, prefix in frontier:

            for field in current._meta.get_fields():

                if not getattr(field, "is_relation", False):
                    continue

                remote = getattr(
                    field,
                    "remote_field",
                    None,
                )

                remote_model = getattr(
                    remote,
                    "model",
                    None,
                )

                if not isinstance(
                    remote_model,
                    type,
                ):
                    continue

                try:
                    if not issubclass(
                        remote_model,
                        Model,
                    ):
                        continue
                except TypeError:
                    continue

                if remote_model in visited:
                    continue

                visited.add(remote_model)

                new_path = prefix + [field.name]

                if (
                    getattr(
                        remote_model._meta,
                        "model_name",
                        "",
                    )
                    == "school"
                ):
                    paths.append(
                        "__".join(new_path)
                    )
                    continue

                if len(new_path) < 3:
                    next_frontier.append(
                        (
                            remote_model,
                            new_path,
                        )
                    )

        frontier = next_frontier

        if not frontier:
            break

    # ------------------------------------------------------------------
    # Deduplicate
    # ------------------------------------------------------------------

    result = []
    seen = set()

    for path in paths:

        if path not in seen:

            seen.add(path)
            result.append(path)

    return result


# ============================================================================
# SCHOOL QUERYSET
# ============================================================================

def _queryset_for_school(model, school):
    """
    Return a tenant-scoped queryset.

    NEVER return an unscoped queryset.
    """

    if not school:
        return None, None

    paths = _find_school_paths(model)

    manager = model._default_manager

    for path in paths:

        try:

            queryset = manager.filter(
                **{path: school}
            )

            return queryset, path

        except Exception:
            continue

    return None, None


# ============================================================================
# MODEL TEXT FOR ROUTING ONLY
# ============================================================================

def _model_text(model):

    pieces = [
        model._meta.app_label,
        model.__name__,
        model._meta.verbose_name,
    ]

    for field in model._meta.get_fields():

        if not hasattr(field, "name"):
            continue

        field_name = field.name

        if _field_is_sensitive(field_name):
            continue

        pieces.append(field_name)

    return _normalize(
        " ".join(pieces)
    )


# ============================================================================
# MODEL SCORING
# ============================================================================

def _score_model(model, question):

    question = _normalize(question)

    if not question:
        return 0

    score = 0

    model_name = _normalize(
        model.__name__
    )

    app_label = _normalize(
        model._meta.app_label
    )

    verbose_name = _normalize(
        model._meta.verbose_name
    )

    model_text = _model_text(model)

    # --------------------------------------------------------------
    # Exact model matches
    # --------------------------------------------------------------

    if model_name in question:
        score += 50

    if verbose_name and verbose_name in question:
        score += 35

    if app_label and app_label in question:
        score += 20

    # --------------------------------------------------------------
    # Field matches
    # --------------------------------------------------------------

    for field in model._meta.get_fields():

        field_name = _normalize(
            getattr(field, "name", "")
        )

        if not field_name:
            continue

        if _field_is_sensitive(field_name):
            continue

        field_display = field_name.replace(
            "_",
            " ",
        )

        if field_name in question:
            score += 8

        if field_display in question:
            score += 10

    # --------------------------------------------------------------
    # Aliases
    # --------------------------------------------------------------

    app = model._meta.app_label.lower()
    name = model.__name__.lower()

    for group, aliases in ALIASES.items():

        if not any(
            alias in question
            for alias in aliases
        ):
            continue

        if group == app:
            score += 40

        elif group.rstrip("s") in name:
            score += 35

        elif group == "staff_hr" and app == "staff":
            score += 45

        elif group == "assessments" and app == "assessments":
            score += 40

        elif group == "school" and app == "school":
            score += 35

    # --------------------------------------------------------------
    # Token overlap
    # --------------------------------------------------------------

    tokens = set(
        question.split()
    )

    score += min(
        20,
        sum(
            1
            for token in tokens
            if token and token in model_text
        ),
    )

    return score


# ============================================================================
# QUESTION CLASSIFICATION
# ============================================================================

def _question_contains(question, words):

    question = _normalize(question)

    return any(
        word in question
        for word in words
    )


def _question_type(question):

    q = _normalize(question)

    # Attendance
    if (
        "attendance rate" in q
        or "attendance percentage" in q
        or "attendance today" in q
        or "attendance recorded today" in q
        or "how many students attended" in q
        or "how many students attendance" in q
        or "students present" in q
        or "students absent" in q
        or "attendance" in q
    ):
        return "attendance"

    # Leave
    if (
        "on leave" in q
        or "currently on leave" in q
        or "staff on leave" in q
        or "leave today" in q
        or "leave" in q
    ):
        return "leave"

    # Student count
    if (
        "how many students" in q
        or "number of students" in q
        or "total students" in q
        or "student population" in q
    ):
        return "student_count"

    # Staff count
    if (
        "how many staff" in q
        or "number of staff" in q
        or "total staff" in q
        or "staff population" in q
    ):
        return "staff_count"

    # Performance
    if (
        "school performance" in q
        or "academic performance" in q
        or "overall performance" in q
        or "key risks" in q
        or "school risks" in q
        or "performance and risks" in q
    ):
        return "school_performance"

    return "general"


# ============================================================================
# MODEL FINDER
# ============================================================================

def _find_best_models(question, school, user):

    candidates = []

    for model in apps.get_models():

        try:

            if not issubclass(
                model,
                Model,
            ):
                continue

        except TypeError:
            continue

        if model._meta.abstract:
            continue

        if model._meta.proxy:
            continue

        if _model_blocked(model):
            continue

        capability = _capability_for_model(
            model
        )

        if not capability:
            continue

        try:

            if not can_use(
                user,
                capability,
            ):
                continue

        except Exception:

            logger.exception(
                "AI capability check failed."
            )
            continue

        queryset, school_path = (
            _queryset_for_school(
                model,
                school,
            )
        )

        if queryset is None:
            continue

        score = _score_model(
            model,
            question,
        )

        if score <= 0:
            continue

        candidates.append(
            (
                score,
                model,
                school_path,
                queryset,
            )
        )

    candidates.sort(
        key=lambda item: (
            -item[0],
            item[1]._meta.label_lower,
        )
    )

    return candidates[:MAX_MODELS]


# ============================================================================
# FIELD FINDER
# ============================================================================

def _find_field(model, candidates):

    field_map = {}

    for field in model._meta.get_fields():

        name = getattr(
            field,
            "name",
            None,
        )

        if not name:
            continue

        if _field_is_sensitive(name):
            continue

        field_map[
            name.lower()
        ] = field

    # Exact matches first
    for candidate in candidates:

        candidate = candidate.lower()

        if candidate in field_map:
            return field_map[candidate]

    # Contains matches second
    for candidate in candidates:

        candidate = candidate.lower()

        for name, field in field_map.items():

            if candidate in name:
                return field

    return None


# ============================================================================
# GENERIC DATE FIELD FINDER
# ============================================================================

def _find_date_field(model):

    candidates = [
        "date",
        "attendance_date",
        "record_date",
        "day",
        "leave_date",
        "start_date",
        "date_from",
        "from_date",
        "created_at",
        "created",
    ]

    return _find_field(
        model,
        candidates,
    )


# ============================================================================
# GENERIC STATUS FIELD FINDER
# ============================================================================

def _find_status_field(model):

    candidates = [
        "status",
        "attendance_status",
        "state",
        "leave_status",
        "approval_status",
    ]

    return _find_field(
        model,
        candidates,
    )


# ============================================================================
# SAFE PERSON NAME
# ============================================================================

def _safe_person_name(obj):

    # We intentionally do NOT expose IDs, phone numbers,
    # email addresses, biometrics or government IDs.

    possible = [
        "full_name",
        "name",
        "staff_name",
        "student_name",
        "display_name",
    ]

    for attr in possible:

        try:

            value = getattr(
                obj,
                attr,
                None,
            )

            if value:
                return _safe_text(value)

        except Exception:
            pass

    # Follow common user/staff/student relationships
    for relation in [
        "staff",
        "student",
        "teacher",
        "user",
    ]:

        try:

            related = getattr(
                obj,
                relation,
                None,
            )

            if related:

                for attr in [
                    "get_full_name",
                    "full_name",
                    "name",
                    "username",
                ]:

                    try:

                        value = getattr(
                            related,
                            attr,
                            None,
                        )

                        if callable(value):
                            value = value()

                        if value:
                            return _safe_text(
                                value
                            )

                    except Exception:
                        pass

        except Exception:
            pass

    return "Unnamed staff member"


# ============================================================================
# ATTENDANCE MODEL FINDER
# ============================================================================

def _find_attendance_models(
    question,
    school,
    user,
):

    models = []

    for model in apps.get_models():

        try:
            if not issubclass(
                model,
                Model,
            ):
                continue
        except TypeError:
            continue

        if model._meta.abstract:
            continue

        if model._meta.proxy:
            continue

        if _model_blocked(model):
            continue

        app = model._meta.app_label.lower()
        name = model.__name__.lower()

        text = _model_text(model)

        looks_like_attendance = (
            "attendance" in name
            or "attendance" in app
            or "attendance" in text
        )

        if not looks_like_attendance:
            continue

        capability = _capability_for_model(
            model
        )

        if not capability:
            continue

        try:
            if not can_use(
                user,
                capability,
            ):
                continue
        except Exception:
            continue

        qs, school_path = (
            _queryset_for_school(
                model,
                school,
            )
        )

        if qs is None:
            continue

        models.append(
            (
                model,
                school_path,
                qs,
            )
        )

    return models


# ============================================================================
# ATTENDANCE FACT BUILDER
# ============================================================================

def _build_attendance_facts(
    school,
    user,
    question,
):

    facts = []
    evidence = []

    today = date.today()

    models = _find_attendance_models(
        question,
        school,
        user,
    )

    if not models:

        facts.append(
            "No school-scoped attendance model could be identified."
        )

        return facts, evidence

    for model, school_path, qs in models:

        date_field = _find_date_field(
            model
        )

        status_field = _find_status_field(
            model
        )

        if not date_field:
            continue

        date_name = date_field.name

        # --------------------------------------------------------------
        # Today
        # --------------------------------------------------------------

        try:

            today_qs = qs.filter(
                **{
                    date_name: today
                }
            )

            total_today = today_qs.count()

        except Exception:

            continue

        facts.append(
            "Attendance records recorded today: {}".format(
                total_today
            )
        )

        # --------------------------------------------------------------
        # Status analysis
        # --------------------------------------------------------------

        present_count = None
        absent_count = None
        late_count = None

        if status_field:

            status_name = status_field.name

            try:

                values = (
                    today_qs
                    .values(status_name)
                    .annotate(total=Count("pk"))
                    .order_by()
                )

                for item in values:

                    raw_status = item.get(
                        status_name
                    )

                    status = _normalize(
                        raw_status
                    )

                    total = item.get(
                        "total",
                        0,
                    )

                    if (
                        status in {
                            "present",
                            "p",
                            "attended",
                            "on time",
                        }
                    ):
                        present_count = (
                            present_count or 0
                        ) + total

                    elif status in {
                        "absent",
                        "a",
                        "missing",
                    }:
                        absent_count = (
                            absent_count or 0
                        ) + total

                    elif (
                        status in {
                            "late",
                            "l",
                            "tardy",
                        }
                    ):
                        late_count = (
                            late_count or 0
                        ) + total

            except Exception:
                pass

        if present_count is not None:
            facts.append(
                "Students/attendance records marked present today: {}".format(
                    present_count
                )
            )

        if absent_count is not None:
            facts.append(
                "Students/attendance records marked absent today: {}".format(
                    absent_count
                )
            )

        if late_count is not None:
            facts.append(
                "Attendance records marked late today: {}".format(
                    late_count
                )
            )

        # --------------------------------------------------------------
        # Attendance rate
        # --------------------------------------------------------------

        if (
            present_count is not None
            and absent_count is not None
        ):

            denominator = (
                present_count
                + absent_count
            )

            if denominator > 0:

                rate = (
                    present_count
                    / denominator
                ) * 100

                rate = round(
                    rate,
                    2,
                )

                facts.append(
                    "Attendance rate today: {}% "
                    "(present {} of {} recorded present/absent records).".format(
                        rate,
                        present_count,
                        denominator,
                    )
                )

        evidence.append(
            {
                "type": "attendance",
                "model": _model_label(model),
                "date": today.isoformat(),
                "records_today": total_today,
            }
        )

        # We normally only need the primary attendance model.
        break

    return facts, evidence


# ============================================================================
# LEAVE MODEL FINDER
# ============================================================================

def _find_leave_models(
    question,
    school,
    user,
):

    models = []

    for model in apps.get_models():

        try:
            if not issubclass(
                model,
                Model,
            ):
                continue
        except TypeError:
            continue

        if model._meta.abstract:
            continue

        if model._meta.proxy:
            continue

        if _model_blocked(model):
            continue

        app = model._meta.app_label.lower()
        name = model.__name__.lower()
        text = _model_text(model)

        looks_like_leave = (
            "leave" in name
            or "leave" in app
            or "leave" in text
        )

        if not looks_like_leave:
            continue

        capability = _capability_for_model(
            model
        )

        if not capability:
            continue

        try:
            if not can_use(
                user,
                capability,
            ):
                continue
        except Exception:
            continue

        qs, school_path = (
            _queryset_for_school(
                model,
                school,
            )
        )

        if qs is None:
            continue

        models.append(
            (
                model,
                school_path,
                qs,
            )
        )

    return models


# ============================================================================
# LEAVE FACT BUILDER
# ============================================================================

def _build_leave_facts(
    school,
    user,
    question,
):

    facts = []
    evidence = []

    today = date.today()

    models = _find_leave_models(
        question,
        school,
        user,
    )

    if not models:

        facts.append(
            "No school-scoped staff leave model could be identified."
        )

        return facts, evidence

    for model, school_path, qs in models:

        # --------------------------------------------------------------
        # Find status
        # --------------------------------------------------------------

        status_field = _find_status_field(
            model
        )

        # --------------------------------------------------------------
        # Determine date fields
        # --------------------------------------------------------------

        start_field = _find_field(
            model,
            [
                "start_date",
                "date_from",
                "from_date",
                "leave_start",
                "start",
            ],
        )

        end_field = _find_field(
            model,
            [
                "end_date",
                "date_to",
                "to_date",
                "leave_end",
                "end",
            ],
        )

        single_date_field = _find_field(
            model,
            [
                "leave_date",
                "date",
            ],
        )

        active_qs = qs

        # --------------------------------------------------------------
        # Filter approved/active status when possible
        # --------------------------------------------------------------

        if status_field:

            status_name = status_field.name

            try:

                active_qs = active_qs.filter(
                    Q(**{
                        "{}__iexact".format(
                            status_name
                        ): "approved"
                    })
                    |
                    Q(**{
                        "{}__iexact".format(
                            status_name
                        ): "active"
                    })
                    |
                    Q(**{
                        "{}__iexact".format(
                            status_name
                        ): "on_leave"
                    })
                    |
                    Q(**{
                        "{}__iexact".format(
                            status_name
                        ): "on leave"
                    })
                )

            except Exception:
                pass

        # --------------------------------------------------------------
        # Determine people currently on leave
        # --------------------------------------------------------------

        current_qs = active_qs

        try:

            if start_field and end_field:

                current_qs = current_qs.filter(
                    **{
                        "{}__lte".format(
                            start_field.name
                        ): today,
                        "{}__gte".format(
                            end_field.name
                        ): today,
                    }
                )

            elif single_date_field:

                current_qs = current_qs.filter(
                    **{
                        single_date_field.name: today
                    }
                )

        except Exception:

            continue

        try:

            count = current_qs.count()

        except Exception:

            continue

        facts.append(
            "Staff leave records covering today: {}".format(
                count
            )
        )

        # --------------------------------------------------------------
        # Names
        # --------------------------------------------------------------

        names = []

        try:

            for obj in current_qs[:20]:

                name = _safe_person_name(
                    obj
                )

                if (
                    name
                    and name not in names
                ):
                    names.append(name)

        except Exception:
            names = []

        if names:

            facts.append(
                "Staff currently on leave: {}".format(
                    ", ".join(names)
                )
            )

        elif count == 0:

            facts.append(
                "No staff leave records currently cover today."
            )

        evidence.append(
            {
                "type": "staff_leave",
                "model": _model_label(model),
                "date": today.isoformat(),
                "records_currently_active": count,
            }
        )

        break

    return facts, evidence


# ============================================================================
# STUDENT COUNT
# ============================================================================

def _build_student_count_facts(
    school,
    user,
):

    facts = []
    evidence = []

    candidates = []

    for model in apps.get_models():

        try:

            if not issubclass(
                model,
                Model,
            ):
                continue

        except TypeError:
            continue

        if model._meta.abstract:
            continue

        if model._meta.proxy:
            continue

        if _model_blocked(model):
            continue

        if model.__name__.lower() != "student":
            continue

        capability = _capability_for_model(
            model
        )

        if not capability:
            continue

        try:
            if not can_use(
                user,
                capability,
            ):
                continue
        except Exception:
            continue

        qs, path = _queryset_for_school(
            model,
            school,
        )

        if qs is not None:
            candidates.append(
                (model, path, qs)
            )

    if not candidates:

        facts.append(
            "The school-scoped Student model could not be identified."
        )

        return facts, evidence

    model, path, qs = candidates[0]

    try:

        active_qs = qs

        # Prefer is_active when present
        try:

            model._meta.get_field(
                "is_active"
            )

            active_qs = qs.filter(
                is_active=True
            )

        except FieldDoesNotExist:
            pass

        total = active_qs.count()

        facts.append(
            "Current active student population: {}".format(
                total
            )
        )

        evidence.append(
            {
                "type": "student_population",
                "model": _model_label(model),
                "active_students": total,
            }
        )

    except Exception:

        logger.exception(
            "Unable to calculate student population."
        )

    return facts, evidence


# ============================================================================
# STAFF COUNT
# ============================================================================

def _build_staff_count_facts(
    school,
    user,
):

    facts = []
    evidence = []

    for model in apps.get_models():

        try:

            if not issubclass(
                model,
                Model,
            ):
                continue

        except TypeError:
            continue

        if model._meta.abstract:
            continue

        if model._meta.proxy:
            continue

        name = model.__name__.lower()
        app = model._meta.app_label.lower()

        if not (
            name in {
                "staff",
                "staffprofile",
                "employee",
                "teacher",
            }
            or app == "staff"
        ):
            continue

        if _model_blocked(model):
            continue

        capability = _capability_for_model(
            model
        )

        if not capability:
            continue

        try:

            if not can_use(
                user,
                capability,
            ):
                continue

        except Exception:
            continue

        qs, path = _queryset_for_school(
            model,
            school,
        )

        if qs is None:
            continue

        try:

            total = qs.count()

            facts.append(
                "School staff records: {}".format(
                    total
                )
            )

            evidence.append(
                {
                    "type": "staff_population",
                    "model": _model_label(model),
                    "staff_records": total,
                }
            )

            return facts, evidence

        except Exception:
            continue

    facts.append(
        "No school-scoped staff model was identified."
    )

    return facts, evidence


# ============================================================================
# PERFORMANCE FACTS
# ============================================================================

def _build_performance_facts(
    school,
    user,
    question,
):

    facts = []
    evidence = []

    # --------------------------------------------------------------
    # Student population
    # --------------------------------------------------------------

    student_facts, student_evidence = (
        _build_student_count_facts(
            school,
            user,
        )
    )

    facts.extend(
        student_facts
    )

    evidence.extend(
        student_evidence
    )

    # --------------------------------------------------------------
    # Attendance
    # --------------------------------------------------------------

    attendance_facts, attendance_evidence = (
        _build_attendance_facts(
            school,
            user,
            question,
        )
    )

    facts.extend(
        attendance_facts
    )

    evidence.extend(
        attendance_evidence
    )

    # --------------------------------------------------------------
    # Assessments
    # --------------------------------------------------------------

    assessment_models = _find_best_models(
        "student grades scores assessments results exams",
        school,
        user,
    )

    for score, model, path, qs in assessment_models[:3]:

        if _model_blocked(model):
            continue

        try:

            numeric_field = _find_field(
                model,
                [
                    "score",
                    "marks",
                    "mark",
                    "percentage",
                    "grade",
                    "average",
                ],
            )

            if not numeric_field:
                continue

            field_name = numeric_field.name

            aggregate = qs.aggregate(
                average=Avg(
                    field_name
                )
            )

            average = aggregate.get(
                "average"
            )

            if average is not None:

                try:
                    average = round(
                        float(average),
                        2,
                    )
                except Exception:
                    pass

                facts.append(
                    "Average recorded assessment value from {}: {}".format(
                        _model_label(model),
                        average,
                    )
                )

                evidence.append(
                    {
                        "type": "academic_assessment",
                        "model": _model_label(model),
                        "average": average,
                    }
                )

                break

        except Exception:
            continue

    # --------------------------------------------------------------
    # Risk summary
    # --------------------------------------------------------------

    facts.append(
        "Performance assessment is based only on verified "
        "school database records available to the current user."
    )

    return facts, evidence


# ============================================================================
# GENERAL MODEL FACTS
# ============================================================================

def _build_general_facts(
    question,
    school,
    user,
):

    facts = []
    evidence = []

    candidates = _find_best_models(
        question,
        school,
        user,
    )

    # For broad questions (e.g. "tell me about the school"), model
    # scoring can legitimately produce no candidate. Provide a compact
    # whole-school snapshot so the Copilot still has verified facts to
    # reason over instead of falling back to unsupported guesses.
    if not candidates:
        preferred = {
            "students": ("students", "students"),
            "staff": ("staff", "staff"),
            "academics": ("academics", "academic"),
            "attendance": ("attendance", "attendance"),
            "finance": ("finance", "fee"),
            "library": ("library", "library"),
        }
        for app_label, (capability, label_hint) in preferred.items():
            try:
                if not can_use(user, capability):
                    continue
            except Exception:
                continue
            for model in apps.get_models():
                if model._meta.app_label.lower() != app_label or _model_blocked(model):
                    continue
                qs, school_path = _queryset_for_school(model, school)
                if qs is not None:
                    candidates.append((1, model, school_path, qs))
                    break

    for score, model, school_path, qs in candidates:

        try:

            count = qs.count()

        except Exception:

            continue

        facts.append(
            "{} has {} school-scoped records.".format(
                model._meta.verbose_name.title(),
                count,
            )
        )

        evidence.append(
            {
                "type": "model_count",
                "model": _model_label(model),
                "records": count,
            }
        )

    return facts, evidence


# ============================================================================
# BUILD CONTEXT
# ============================================================================

def build_universal_school_context(
    user,
    school,
    question,
    max_chars=MAX_CONTEXT_CHARS,
):
    """
    Main entry point.

    IMPORTANT:

    This function deliberately does NOT return raw Django model rows.

    Instead it returns a structured fact-based context that can safely
    be supplied to the Copilot LLM.
    """

    question = str(
        question or ""
    ).strip()

    result = {

        "school": _safe_text(
            getattr(
                school,
                "name",
                "School",
            )
        ),

        "question": question,

        "data_source": (
            "Verified school database"
        ),

        "context_type": (
            "structured_verified_school_facts"
        ),

        "facts": [],

        "evidence": [],

        # Kept for backward compatibility with existing Copilot code.
        # IMPORTANT: these are summaries, NOT database rows.
        "records": [],

        # Kept because existing code may reference model_catalog.
        # It contains only high-level labels and counts.
        "model_catalog": [],

        "warnings": [],
    }

    if not school:

        result["warnings"].append(
            "No school tenant was available. "
            "No school data was queried."
        )

        return result

    qtype = _question_type(
        question
    )

    try:

        # ==============================================================
        # DETERMINISTIC DOMAIN ROUTING
        # ==============================================================

        if qtype == "attendance":

            facts, evidence = (
                _build_attendance_facts(
                    school,
                    user,
                    question,
                )
            )

        elif qtype == "leave":

            facts, evidence = (
                _build_leave_facts(
                    school,
                    user,
                    question,
                )
            )

        elif qtype == "student_count":

            facts, evidence = (
                _build_student_count_facts(
                    school,
                    user,
                )
            )

        elif qtype == "staff_count":

            facts, evidence = (
                _build_staff_count_facts(
                    school,
                    user,
                )
            )

        elif qtype == "school_performance":

            facts, evidence = (
                _build_performance_facts(
                    school,
                    user,
                    question,
                )
            )

        else:

            facts, evidence = (
                _build_general_facts(
                    question,
                    school,
                    user,
                )
            )

        result["facts"].extend(
            facts
        )

        result["evidence"].extend(
            evidence
        )

    except Exception as exc:

        logger.exception(
            "Universal school context failed."
        )

        result["warnings"].append(
            "The school database context could not "
            "be completely calculated."
        )

    # ==============================================================
    # NORMALIZE FACTS
    # ==============================================================

    clean_facts = []

    seen_facts = set()

    for fact in result["facts"]:

        fact = _safe_text(
            fact,
            500,
        )

        if not fact:
            continue

        if fact in seen_facts:
            continue

        seen_facts.add(
            fact
        )

        clean_facts.append(
            fact
        )

        if len(clean_facts) >= MAX_FACTS:
            break

    result["facts"] = clean_facts

    # ==============================================================
    # SAFE EVIDENCE
    # ==============================================================

    clean_evidence = []

    for item in result["evidence"]:

        if not isinstance(
            item,
            dict,
        ):
            continue

        clean_item = {}

        for key, value in item.items():

            # Never allow IDs or sensitive fields
            if _field_is_sensitive(
                key
            ):
                continue

            if key in {
                "id",
                "pk",
                "uuid",
                "object_id",
            }:
                continue

            if isinstance(
                value,
                (date, datetime),
            ):
                value = value.isoformat()

            elif isinstance(
                value,
                Decimal,
            ):
                value = str(value)

            elif isinstance(
                value,
                str,
            ):
                value = _safe_text(
                    value
                )

            clean_item[key] = value

        clean_evidence.append(
            clean_item
        )

        if (
            len(clean_evidence)
            >= MAX_EVIDENCE_ITEMS
        ):
            break

    result["evidence"] = (
        clean_evidence
    )

    # ==============================================================
    # BACKWARD-COMPATIBILITY RECORD SUMMARY
    # ==============================================================
    #
    # Existing Copilot code may expect result["records"].
    #
    # We DO NOT put actual rows there.
    #

    for evidence in result["evidence"]:

        model = evidence.get(
            "model"
        )

        if not model:
            continue

        summary = {
            "model": model,
        }

        if "records" in evidence:
            summary["records"] = evidence[
                "records"
            ]

        if "records_today" in evidence:
            summary["records_today"] = evidence[
                "records_today"
            ]

        if "active_students" in evidence:
            summary["active_students"] = evidence[
                "active_students"
            ]

        if "staff_records" in evidence:
            summary["staff_records"] = evidence[
                "staff_records"
            ]

        if (
            "records_currently_active"
            in evidence
        ):
            summary[
                "records_currently_active"
            ] = evidence[
                "records_currently_active"
            ]

        result["records"].append(
            summary
        )

    # ==============================================================
    # SAFE SIZE LIMIT
    # ==============================================================

    while (
        len(str(result))
        > max_chars
        and result["evidence"]
    ):

        result["evidence"].pop()

    return result


# ============================================================================
# MODEL CATALOG
# ============================================================================

def build_model_catalog(
    user,
    school,
):
    """
    Returns a safe internal catalog of school-readable models.

    This function is useful for diagnostics/routing.

    IMPORTANT:
    Do NOT send this catalog directly to the LLM.

    It intentionally excludes fields because the LLM does not need
    Django implementation details.
    """

    catalog = []

    if not school:
        return catalog

    for model in apps.get_models():

        try:

            if not issubclass(
                model,
                Model,
            ):
                continue

        except TypeError:
            continue

        if model._meta.abstract:
            continue

        if model._meta.proxy:
            continue

        if _model_blocked(model):
            continue

        capability = _capability_for_model(
            model
        )

        if not capability:
            continue

        try:

            if not can_use(
                user,
                capability,
            ):
                continue

        except Exception:
            continue

        qs, school_path = (
            _queryset_for_school(
                model,
                school,
            )
        )

        if qs is None:
            continue

        try:

            count = qs.count()

        except Exception:

            count = None

        catalog.append(
            {
                "model": _model_label(
                    model
                ),
                "records": count,
                "school_scope_path": school_path,
                "capability": capability,
            }
        )

        if len(catalog) >= MAX_MODEL_CATALOG:
            break

    return catalog