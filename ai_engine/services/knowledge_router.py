# ai_engine/services/knowledge_router.py
"""
Routes general education questions to the appropriate Copilot
knowledge source.
"""
from .ghana_education import search_ghana_education


# ============================================================================
# GENERAL KNOWLEDGE INTENT
# ============================================================================
GENERAL_EDUCATION_TERMS = {
    "education",
    "school",
    "teaching",
    "teacher",
    "teachers",
    "learning",
    "learner",
    "learners",
    "student",
    "students",
    "curriculum",
    "assessment",
    "examination",
    "exams",
    "exam",
    "bece",
    "wassce",
    "ges",
    "nacca",
    "moe",
    "ghana",
    "classroom",
    "lesson",
    "lessons",
    "pedagogy",
    "grading",
    "revision",
    "study",
    "studying",
}


def is_general_education_question(question):
    """
    Determine whether a question appears to concern education.
    """
    if not question:
        return False
    normalized = str(question).lower()
    return any(
        term in normalized
        for term in GENERAL_EDUCATION_TERMS
    )


def get_knowledge_context(question, limit=8):
    """
    Return Ghana education knowledge relevant to the question.
    """
    if not is_general_education_question(question):
        return {
            "enabled": False,
            "source": "ghana_education",
            "results": [],
        }
    results = search_ghana_education(
        question,
        limit=limit,
    )
    return {
        "enabled": True,
        "source": "ghana_education",
        "results": results,
    }
