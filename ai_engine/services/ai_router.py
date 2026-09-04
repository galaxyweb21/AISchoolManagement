# ai_engine/services/ai_router.py
"""
Enterprise AI Request Router - Complete School Operations

Routes natural language queries to the appropriate AI engine
based on intent detection, role authorization, and data scope.
"""

from ai_engine.services.intent_detector import IntentDetector
from ai_engine.services.tool_registry import ToolRegistry
from ai_engine.services.role_ai_policy import can_use
import logging

logger = logging.getLogger(__name__)


class AIRouter:
    """
    Enterprise AI Request Router - Routes queries to the right engine
    """

    def __init__(self, user):
        self.user = user
        self.intent_detector = IntentDetector()
        self.registry = ToolRegistry()

    def process(self, school, user, question):
        """
        Main entry point to route a question to the correct AI engine.
        """
        if not question or not question.strip():
            return self._get_help_response()

        question_lower = question.lower().strip()

        # 1. Detect intent
        intent_result = self.intent_detector.detect(question)

        # 2. Check if user is authorized for this intent
        if not can_use(user, intent_result['intent']):
            return self._get_unauthorized_response(intent_result['intent'])

        intent_name = intent_result['intent']

        # 3. Prefer the secure Tool Registry execution path (Step 1) when
        #    this intent has been migrated to a proper AITool adapter —
        #    it enforces the capability check again at the tool level,
        #    validates arguments, applies a timeout and writes an audit
        #    log (ToolExecutionLog) regardless of outcome.
        if intent_name in self.registry._tools:
            result = self.registry.execute(
                intent_name,
                school=school,
                user=user,
                question=question,
                context=intent_result,
            )
            if result["success"]:
                return result["data"]
            logger.warning("Secure tool '%s' failed: %s", intent_name, result["error"])
            return f"⚠️ {result['error']}"

        # 4. Fall back to the legacy engine lookup for intents not yet
        #    migrated to the secure registry (academics, timetable,
        #    attendance, exam, risk, report, parent, general).
        tool = self.registry.get_engine(intent_result['intent'])

        if tool:
            try:
                return tool.run(
                    school=school,
                    user=user,
                    question=question,
                    context=intent_result
                )
            except Exception as e:
                logger.error(f"Tool execution error: {e}")
                return "⚠️ I encountered an error while processing your request. Please try again or rephrase your question."

        # 5. If no specific tool matched, return intelligent fallback
        return self._get_fallback_response(question, intent_result)

    def _get_help_response(self):
        """Return a helpful response when no question is provided."""
        return """
🤖 **AI School Copilot** - I can help you with:

**📚 Students & Academics**
- Student records, enrollment, performance
- Classes, subjects, timetables
- Attendance tracking
- Exams and assessments
- Report cards

**👨‍🏫 Staff & HR**
- Staff records and profiles
- Absence management and substitute cover
- Lesson planning
- Workload management

**💰 Finance & Payroll**
- Fees, invoices, payments
- Staff payroll and salaries
- Financial reporting
- Budget management

**📊 School Operations**
- Risk assessment and early warning
- School health score
- AI insights and recommendations
- Ghana Education System knowledge

**🔍 Research**
- Ghana Education Service policies
- NaCCA curriculum standards
- WAEC examination regulations

Try asking me something like:
- "List all students in Grade 10"
- "Show me staff absences this month"
- "What is the outstanding fee balance?"
- "Generate a lesson plan for Mathematics"
- "Explain the BECE grading system"
- "What are the current GES policies on..."
"""

    def _get_unauthorized_response(self, intent):
        """Return a response when the user is not authorized."""
        return f"""
⚠️ **Access Restricted**

I understand you're asking about **{intent.replace('_', ' ').title()}**, but your role ({self.user.role}) does not have permission to access this information.

Please contact your school administrator if you need access to this area.

I can help you with other questions within your authorized scope.
"""

    def _get_fallback_response(self, question, intent_result):
        """Return an intelligent fallback response."""
        # Try to suggest related topics
        suggested_topics = []

        # Check if the question contains any known keywords
        keywords = {
            "student": "students",
            "teacher": "staff",
            "staff": "staff",
            "pay": "payroll",
            "salary": "payroll",
            "money": "finance",
            "fee": "finance",
            "class": "academics",
            "subject": "academics",
            "exam": "exam",
            "test": "exam",
            "attendance": "attendance",
            "absent": "attendance",
            "time": "timetable",
            "schedule": "timetable",
            "lesson": "academics",
            "risk": "risk",
            "policy": "ghana_education",
            "curriculum": "ghana_education",
            "ges": "ghana_education",
            "nacca": "ghana_education",
            "waec": "ghana_education",
            "bece": "ghana_education",
            "wassce": "ghana_education",
        }

        for word, topic in keywords.items():
            if word in question.lower():
                suggested_topics.append(topic)

        suggested_topics = list(set(suggested_topics))[:3]

        response = f"""
🤔 **I'm not quite sure how to help with that specific question.**

I can assist with the following areas:
- 📚 Students & Academics
- 👨‍🏫 Staff & HR  
- 💰 Finance & Payroll
- 📊 School Operations
- 🔍 Research & Policy
- 🇬🇭 Ghana Education System

"""
        if suggested_topics:
            response += f"\n**Based on your question, you might be looking for help with:**\n"
            for topic in suggested_topics:
                response += f"- {topic.replace('_', ' ').title()}\n"
            response += f"\nTry rephrasing your question to be more specific, e.g.,\n"
            response += f"- 'Show me all students'\n"
            response += f"- 'What is the outstanding fee balance?'\n"
            response += f"- 'Explain the current GES policy on...'"
        else:
            response += f"\nTry asking about:\n"
            response += f"- 'List all students in Grade 10'\n"
            response += f"- 'Show me staff absences this month'\n"
            response += f"- 'What is the outstanding fee balance?'\n"
            response += f"- 'Explain the BECE grading system'"

        return response