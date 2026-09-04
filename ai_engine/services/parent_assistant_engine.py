# ai_engine/services/parent_assistant_engine.py
"""
Parent-facing AI assistant. This is a RAG pattern, not a general chatbot:
before the LLM ever sees the parent's question, real attendance/grade/fee
data for the specific child is gathered and handed to it as ground truth,
with an explicit instruction not to invent anything beyond it. The point
isn't "a chatbot that can talk about school" - it's an answer a parent can
actually trust, grounded in this child's real record.
"""
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from attendance.models import Attendance
from assessments.models import Grade
from finance.models import Invoice
from ai_engine.services.services import AIService

CONVERSATION_HISTORY_LIMIT = 10  # last N messages included as prompt context, keeps it bounded
ATTENDANCE_LOOKBACK_DAYS = 30


class ParentAssistantError(Exception):
    """Raised for access-control failures - e.g. a parent asking about a
    child that isn't theirs. Never silently returns another child's data."""


class ParentAssistantService:

    @staticmethod
    def _build_student_context(student, today=None) -> str:
        today = today or timezone.localdate()
        lookback_start = today - timezone.timedelta(days=ATTENDANCE_LOOKBACK_DAYS)

        attendance_qs = Attendance.objects.filter(student=student, date__gte=lookback_start, date__lte=today)
        total_days = attendance_qs.count()
        present_days = attendance_qs.filter(status__in=['PRESENT', 'LATE']).count()

        lines = [f"Student: {student.user.get_full_name()}, {student.grade_level}."]

        if total_days:
            rate = round((present_days / total_days) * 100, 1)
            lines.append(f"Attendance (last {ATTENDANCE_LOOKBACK_DAYS} days): {rate}% ({present_days}/{total_days} school days present).")
        else:
            lines.append(f"Attendance: no attendance records in the last {ATTENDANCE_LOOKBACK_DAYS} days.")

        grades = list(
            Grade.objects.filter(student=student).select_related('assessment').order_by('-assessment__created_at')[:10]
        )
        if grades:
            lines.append("Recent grades (most recent first):")
            for g in grades:
                max_score = g.assessment.max_score
                pct = f" ({round((float(g.score_achieved) / float(max_score)) * 100, 1)}%)" if max_score else ""
                lines.append(f"- {g.assessment.subject} - {g.assessment.title}: {g.score_achieved}/{max_score}{pct}")
        else:
            lines.append("Recent grades: none recorded yet.")

        invoices = list(Invoice.objects.filter(student=student).exclude(status='PAID'))
        if invoices:
            outstanding = sum((inv.balance_due for inv in invoices), Decimal('0'))
            overdue = [inv for inv in invoices if inv.due_date < today]
            overdue_note = f", {len(overdue)} invoice(s) overdue" if overdue else ""
            lines.append(f"Outstanding fees: {outstanding}{overdue_note}.")
        else:
            lines.append("Outstanding fees: none - fully paid up.")

        return "\n".join(lines)

    @classmethod
    def ask(cls, parent, student, question, history_messages) -> str:
        """
        history_messages: pre-fetched ParentChatMessage queryset/list for
        this (parent, student) pair, oldest-first - passed in rather than
        queried here so the view controls exactly what's shown vs sent.
        """
        if student.parent_id != parent.id:
            raise ParentAssistantError("You can only ask about your own child.")

        if not getattr(settings, 'GROQ_API_KEY', ''):
            return "The AI assistant is currently offline. Please contact the school office directly."

        context = cls._build_student_context(student)
        history_lines = [
            f"{'Parent' if m.sender == 'PARENT' else 'Assistant'}: {m.content}"
            for m in list(history_messages)[-CONVERSATION_HISTORY_LIMIT:]
        ]

        system_prompt = (
            "You are a warm, helpful school assistant answering a parent's question about their child. "
            "You are given real, current data about the child below - use ONLY this data, and NEVER invent "
            "attendance figures, grades, or fee amounts that aren't shown here. If the parent asks something "
            "the data doesn't cover, say plainly that you don't have that information and suggest they contact "
            "the school office - do not guess. Keep answers conversational and concise (2-4 sentences unless "
            "real detail is needed), and encouraging even when flagging a concern. Do not give medical, legal, "
            "or disciplinary advice, and do not discuss any child other than the one described below - redirect "
            "any of that to the school office."
        )

        prompt = f"""
        CHILD'S CURRENT DATA:
        {context}

        CONVERSATION SO FAR:
        {chr(10).join(history_lines) if history_lines else "(this is the first message in this conversation)"}

        PARENT'S NEW QUESTION: {question}

        Respond directly to the parent's question, using only the data above.
        """

        try:
            answer = AIService._call_groq(system_prompt, prompt, max_tokens=300, temperature=0.6)
        except Exception as e:
            return f"Sorry, I couldn't process that right now. Please try again shortly, or contact the school office. ({e})"

        return answer or "Sorry, I couldn't generate a response. Please try again."
