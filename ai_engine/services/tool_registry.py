# ai_engine/services/tool_registry.py
"""
STEP 1 — AI Tool Registry + secure tool execution.

Two ways to use this module:

1. Legacy / backward compatible:
       ToolRegistry().get_engine(intent) -> service class or None
   Kept so nothing that already calls get_engine() breaks.

2. Secure execution (new — use this going forward):
       ToolRegistry().execute(intent, school=school, user=user,
                               question=question, context=context)
   This is the only path that:
     - checks the user's role actually has the required capability
       (single source of truth: role_ai_policy.py)
     - validates arguments against the tool's declared schema
     - runs the tool with a hard timeout so one bad tool can't hang
       a request
     - writes an audit row to ToolExecutionLog regardless of
       success/denial/error
     - always returns a structured dict instead of raising, so callers
       (views, the AI router, other tools) never have to guess what
       kind of exception a given legacy service might throw
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from ai_engine.services.risk_batch import RiskBatchService
from ai_engine.services.exam_engine import ExamGeneratorService
from ai_engine.services.report_card_batch import ReportCardBatchService
from ai_engine.services.parent_assistant_engine import ParentAssistantService
from ai_engine.services.finance_engine import FinanceInsightService
from ai_engine.services.hr_payroll_service import HRPayrollService
from ai_engine.services.role_ai_policy import can_use

from ai_engine.services.tools.base import (
    ToolExecutionError,
    ToolPermissionDenied,
    ToolValidationError,
    ToolTimeoutError,
)
from ai_engine.services.tools.adapters import TOOL_CLASSES

logger = logging.getLogger(__name__)

_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="ai-tool")


class ToolRegistry:
    """
    Registry that maps intent strings to instantiated AI service classes
    (legacy path), and secure AITool instances (execute() path).
    """

    def __init__(self):
        self._registry = self._build_registry()
        self._tools = {cls().name: cls() for cls in TOOL_CLASSES}

    # ------------------------------------------------------------------
    # LEGACY REGISTRY (kept for backward compatibility)
    # ------------------------------------------------------------------

    def _build_registry(self):
        """Build the legacy registry mapping (intent -> service class)."""
        return {
            "students": self._get_student_tool,
            "student": self._get_student_tool,
            "staff": self._get_staff_tool,
            "hr": self._get_staff_tool,
            "payroll": self._get_payroll_tool,
            "academics": self._get_academic_tool,
            "timetable": self._get_timetable_tool,
            "attendance": self._get_attendance_tool,
            "exam": self._get_exam_tool,
            "exams": self._get_exam_tool,
            "risk": self._get_risk_tool,
            "report": self._get_report_tool,
            "reports": self._get_report_tool,
            "finance": self._get_finance_tool,
            "parent": self._get_parent_tool,
            "research": self._get_research_tool,
            "ghana_education": self._get_research_tool,
            "general": self._get_general_tool,
        }

    def get_engine(self, intent):
        """Get the appropriate engine for the given intent (legacy path, no security checks)."""
        if isinstance(intent, str):
            tool = self._registry.get(intent)
            if tool:
                return tool()
            return None

        if isinstance(intent, dict):
            intent_name = intent.get('intent') or intent.get('capability')
            if intent_name:
                tool = self._registry.get(intent_name)
                if tool:
                    return tool()
            return None

        return None

    def _get_student_tool(self):
        try:
            from ai_engine.services.tools.student_tool import StudentTool
            return StudentTool
        except ImportError:
            logger.warning("StudentTool not available")
            return None

    def _get_staff_tool(self):
        return HRPayrollService

    def _get_payroll_tool(self):
        return HRPayrollService

    def _get_academic_tool(self):
        return None

    def _get_timetable_tool(self):
        return None

    def _get_attendance_tool(self):
        return None

    def _get_exam_tool(self):
        return ExamGeneratorService

    def _get_risk_tool(self):
        return RiskBatchService

    def _get_report_tool(self):
        return ReportCardBatchService

    def _get_finance_tool(self):
        return FinanceInsightService

    def _get_parent_tool(self):
        return ParentAssistantService

    def _get_research_tool(self):
        return None

    def _get_general_tool(self):
        return None

    # ------------------------------------------------------------------
    # SECURE EXECUTION (Step 1)
    # ------------------------------------------------------------------

    def list_tools(self, user=None):
        """
        Describe every registered secure tool, optionally filtered to
        what `user`'s role is actually authorized to use. Useful for
        building an AI system prompt ("here are the tools you may
        call") without leaking tools the user can't use anyway.
        """
        tools = []
        for tool in self._tools.values():
            if user is not None and tool.required_capability and not can_use(user, tool.required_capability):
                continue
            tools.append({
                "name": tool.name,
                "description": tool.description,
                "required_capability": tool.required_capability,
                "parameters": [
                    {
                        "name": p.name,
                        "type": p.type.__name__ if p.type else "any",
                        "required": p.required,
                        "description": p.description,
                    }
                    for p in tool.parameters
                ],
            })
        return tools

    def execute(self, name_or_intent, *, school, user, question="", context=None, **kwargs):
        """
        The single secure entry point for calling a tool. Always
        returns a dict:

            {"success": True,  "data": <tool result>, "tool": name}
            {"success": False, "error": "...", "error_type": "...", "tool": name}

        Never raises — every failure mode (unknown tool, permission
        denied, bad arguments, timeout, internal error) is caught and
        logged, with a safe message returned to the caller.
        """
        started = time.monotonic()
        tool = self._tools.get(name_or_intent)
        status = "SUCCESS"
        error_message = ""
        result = None

        try:
            if tool is None:
                status = "ERROR"
                error_message = f"Unknown tool '{name_or_intent}'."
                raise ToolExecutionError(error_message)

            # ---- permission check (role_ai_policy is the single source of truth) ----
            if tool.required_capability and not can_use(user, tool.required_capability):
                status = "DENIED"
                error_message = (
                    f"Your role does not have access to the '{tool.required_capability}' capability."
                )
                raise ToolPermissionDenied(error_message)

            # ---- argument validation ----
            try:
                tool.validate(kwargs)
            except ToolValidationError as exc:
                status = "INVALID"
                error_message = str(exc)
                raise

            # ---- execute with a hard timeout ----
            future = _EXECUTOR.submit(
                tool.run, school=school, user=user, question=question, context=context, **kwargs
            )
            try:
                result = future.result(timeout=tool.timeout_seconds)
            except FutureTimeoutError:
                status = "TIMEOUT"
                error_message = f"'{tool.name}' took too long to respond."
                raise ToolTimeoutError(error_message)

        except ToolExecutionError as exc:
            if status == "SUCCESS":
                status = "ERROR"
            if not error_message:
                error_message = str(exc)
        except Exception as exc:  # noqa: BLE001 - last line of defense, never leak a raw traceback
            status = "ERROR"
            error_message = "Something went wrong while running this tool."
            logger.exception("Unhandled error executing tool '%s': %s", name_or_intent, exc)

        duration_ms = int((time.monotonic() - started) * 1000)
        self._log_execution(
            school=school,
            user=user,
            tool_name=name_or_intent,
            required_capability=getattr(tool, "required_capability", None),
            arguments=kwargs,
            status=status,
            result_summary=self._summarize(result) if status == "SUCCESS" else "",
            error_message=error_message,
            duration_ms=duration_ms,
        )

        if status == "SUCCESS":
            return {"success": True, "data": result, "tool": name_or_intent}
        return {
            "success": False,
            "error": error_message,
            "error_type": status,
            "tool": name_or_intent,
        }

    @staticmethod
    def _summarize(result, limit=300):
        try:
            text = result if isinstance(result, str) else repr(result)
        except Exception:
            text = "<unserializable result>"
        return text[:limit]

    @staticmethod
    def _log_execution(*, school, user, tool_name, required_capability, arguments,
                        status, result_summary, error_message, duration_ms):
        """Best-effort audit log — a logging failure must never break a tool call."""
        try:
            from ai_engine.models import ToolExecutionLog
            ToolExecutionLog.objects.create(
                school=school,
                user=user if getattr(user, "is_authenticated", False) else None,
                tool_name=str(tool_name),
                required_capability=required_capability or "",
                arguments={k: str(v) for k, v in (arguments or {}).items()},
                status=status,
                result_summary=result_summary,
                error_message=error_message,
                duration_ms=duration_ms,
            )
        except Exception:
            logger.exception("Failed to write ToolExecutionLog for tool '%s'", tool_name)
