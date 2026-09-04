# ai_engine/services/exam_engine.py
"""
AI question/exam generation with Ghana Education Service (GES) / NaCCA
Standards-Based Curriculum alignment.
"""
import json
import re
from django.conf import settings

from ai_engine.services.services import AIService

VALID_TYPES = {'MCQ', 'TRUE_FALSE', 'SHORT_ANSWER', 'ESSAY'}

# ============================================================================
# GHANA EDUCATION SERVICE (GES) / NaCCA CURRICULUM CONTEXT
# ============================================================================
GES_STAGE_CONTEXT = {
    'KG': (
        "This is Kindergarten under Ghana's Standards-Based Curriculum (Nursery/KG). "
        "Content standards at this stage are foundational and largely oral/pictorial: "
        "recognizing letters, sounds, and numbers 1-10; basic shapes and colours; simple "
        "classroom routines and social skills. Questions should rely on very simple language, "
        "pictures-in-words descriptions, and concrete, everyday Ghanaian examples (local fruits, "
        "animals, family members) rather than abstract concepts or multi-step reasoning."
    ),
    'PRIMARY': (
        "This is a Primary level (Basic 1-6) under Ghana's Standards-Based Curriculum. Core "
        "subjects follow NaCCA strands such as: Numeracy/Mathematics (Number, Algebra, Geometry "
        "& Measurement, Data), English Language (Listening & Speaking, Reading, Writing, Grammar), "
        "Our World Our People (people, places, the environment, citizenship), Science, Religious "
        "and Moral Education, and Creative Arts. Match question difficulty and vocabulary to the "
        "specific Basic level given (Basic 1-2 is early literacy/numeracy; Basic 3-4 introduces "
        "more structured reasoning; Basic 5-6 approaches JHS-readiness). Use Ghanaian context "
        "throughout: Ghanaian names, Cedis for money, local towns/landmarks, and the Ghanaian "
        "school calendar/terms, not generic Western examples."
    ),
    'JHS': (
        "This is Junior High School (JHS 1-3 / Basic 7-9) under Ghana's Standards-Based "
        "Curriculum -- the stage that prepares students for the BECE (Basic Education Certificate "
        "Examination). Core subjects include Mathematics, English Language, Integrated Science, "
        "Social Studies, Career Technology, Computing, Religious and Moral Education, and Ghanaian "
        "Language. Questions should reflect BECE-style phrasing and rigor appropriate to the "
        "specific JHS year given (JHS 1 introduces the subject's JHS-level strands; JHS 3 approaches "
        "actual BECE standard). Use Ghanaian context: Cedis, local geography and civic structures "
        "(e.g. District Assemblies), and examples a JHS student in Ghana would recognize."
    ),
    'SHS': (
        "This is Senior High School (SHS 1-3) under Ghana's curriculum, working toward the WASSCE "
        "(West African Senior School Certificate Examination) set by WAEC. Match the question style, "
        "command words (e.g. 'state', 'explain', 'evaluate', 'discuss'), and rigor to WASSCE "
        "conventions for the subject and elective/core track implied by the subject name. Use "
        "Ghanaian/West African context and examples where relevant (economics, geography, history, "
        "civic content specific to Ghana/West Africa) rather than generic international examples."
    ),
    'OTHER': "",  # no GES-specific framing
}


class ExamGenerationError(Exception):
    """Raised when generation can't produce a usable set of questions."""
    pass


def _extract_json_array(raw_text: str):
    """Extract JSON array from LLM response."""
    text = raw_text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    text = text.strip()

    if not text.startswith('['):
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            text = match.group(0)

    return json.loads(text)


def _validate_question(q: dict, index: int):
    """Validate a question dict has required fields."""
    missing = [k for k in ('type', 'question', 'correct_answer') if k not in q]
    if missing:
        raise ExamGenerationError(f"Question {index + 1} is missing field(s): {', '.join(missing)}.")
    if q['type'] not in VALID_TYPES:
        raise ExamGenerationError(f"Question {index + 1} has an unrecognized type: {q['type']!r}.")
    if q['type'] == 'MCQ' and (not isinstance(q.get('options'), list) or len(q['options']) < 2):
        raise ExamGenerationError(f"Question {index + 1} is MCQ but doesn't have at least 2 options.")
    if not str(q['question']).strip():
        raise ExamGenerationError(f"Question {index + 1} has empty question text.")


class ExamGeneratorService:
    """Service for generating AI-powered exam questions with GES curriculum alignment."""

    @staticmethod
    def _build_prompt(subject, topic, grade_level, difficulty, num_questions, question_types, ges_stage=None):
        types_line = ", ".join(question_types)
        topic_line = f" specifically on the topic of \"{topic}\"" if topic else ""

        curriculum_context = GES_STAGE_CONTEXT.get(ges_stage, "") if ges_stage else ""
        curriculum_block = f"\n\nCurriculum context: {curriculum_context}\n" if curriculum_context else ""

        return f"""
        Generate {num_questions} exam questions for a {grade_level} class on the subject of
        {subject}{topic_line}. Difficulty level: {difficulty}. Only use these question types,
        distributed sensibly across the set: {types_line}.
        {curriculum_block}
        Return ONLY a raw JSON array (no markdown fences, no commentary before or after) where each
        element has exactly these fields:
        - "type": one of "MCQ", "TRUE_FALSE", "SHORT_ANSWER", "ESSAY"
        - "question": the question text
        - "options": for MCQ, a list of 4 answer choices (as plain strings, no "A)" prefixes); for
          TRUE_FALSE, ["True", "False"]; omit or leave empty for SHORT_ANSWER/ESSAY
        - "correct_answer": for MCQ/TRUE_FALSE, the exact text of the correct option; for
          SHORT_ANSWER, a brief model answer; for ESSAY, a short marking guide (2-3 key points a
          strong answer should cover)
        - "points": a reasonable integer point value for the question's difficulty and type

        Questions must be factually accurate and age-appropriate for {grade_level}. Do not repeat the
        same question twice.
        """

    @classmethod
    def generate(cls, subject, topic, grade_level, difficulty, num_questions, question_types, ges_stage=None):
        """Generate exam questions with GES curriculum alignment."""
        if not getattr(settings, 'GROQ_API_KEY', ''):
            raise ExamGenerationError("AI question generation is offline (API key missing).")

        prompt = cls._build_prompt(subject, topic, grade_level, difficulty, num_questions, question_types, ges_stage)

        system_prompt = "You are an experienced curriculum-aligned exam writer. You respond with raw JSON only."
        if ges_stage and ges_stage != 'OTHER':
            system_prompt = (
                "You are an experienced Ghanaian teacher and exam writer, deeply familiar with the "
                "Ghana Education Service (GES) and NaCCA Standards-Based Curriculum, and with WAEC "
                "conventions (BECE/WASSCE) where relevant. You write exam questions the way they would "
                "genuinely appear in a Ghanaian classroom or official exam for the specified level. "
                "You respond with raw JSON only."
            )

        try:
            raw = AIService._call_groq(
                system_prompt,
                prompt,
                max_tokens=200 + (num_questions * 180),
                temperature=0.6,
            )
        except Exception as e:
            raise ExamGenerationError(f"Request to the AI provider failed: {e}")

        if raw is None:
            raise ExamGenerationError("AI question generation is offline (API key missing).")

        try:
            questions = _extract_json_array(raw)
        except (json.JSONDecodeError, AttributeError):
            raise ExamGenerationError(
                "The AI response couldn't be parsed as a question set. Try regenerating - "
                "this can happen occasionally with free-form model output."
            )

        if not isinstance(questions, list) or not questions:
            raise ExamGenerationError("The AI did not return any questions. Try regenerating.")

        for i, q in enumerate(questions):
            _validate_question(q, i)

        return questions

    @classmethod
    def generate_replacement_question(cls, exam, existing_question):
        """Generate a replacement question of the same type."""
        ges_stage = None
        if exam.school_class and exam.school_class.grade_level:
            ges_stage = exam.school_class.grade_level.stage

        curriculum_context = GES_STAGE_CONTEXT.get(ges_stage, "") if ges_stage else ""
        curriculum_line = f"\nCurriculum context: {curriculum_context}\n" if curriculum_context else ""

        prompt = f"""
        Generate exactly ONE exam question for a {exam.grade_level} class on the subject of
        {exam.subject}{f' (topic: {exam.topic})' if exam.topic else ''}. Difficulty: {exam.difficulty}.
        Question type: {existing_question.question_type}.
        {curriculum_line}
        This is a replacement for a question the teacher wants regenerated - make it meaningfully
        different in content from a typical question on this topic, not a trivial rewording.

        Return ONLY a raw JSON object (no markdown fences, no commentary) with fields: "type",
        "question", "options" (for MCQ: 4 choices; for TRUE_FALSE: ["True","False"]; omit otherwise),
        "correct_answer", "points".
        """

        system_prompt = "You are an experienced curriculum-aligned exam writer. You respond with raw JSON only."
        if ges_stage and ges_stage != 'OTHER':
            system_prompt = (
                "You are an experienced Ghanaian teacher and exam writer, deeply familiar with the "
                "Ghana Education Service (GES) and NaCCA Standards-Based Curriculum. You respond with raw JSON only."
            )

        try:
            raw = AIService._call_groq(
                system_prompt,
                prompt,
                max_tokens=300,
                temperature=0.7,
            )
        except Exception as e:
            raise ExamGenerationError(f"Request to the AI provider failed: {e}")

        if raw is None:
            raise ExamGenerationError("AI question generation is offline (API key missing).")

        text = raw.strip()
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        if not text.startswith('{'):
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                text = match.group(0)

        try:
            question = json.loads(text)
        except json.JSONDecodeError:
            raise ExamGenerationError("The AI response couldn't be parsed. Try regenerating again.")

        _validate_question(question, 0)
        return question