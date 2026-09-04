# ai_engine/services/tools/adapters.py
"""
STEP 1 — AI Tool Registry: adapters around the school's existing AI
service classes (StudentTool, FinanceInsightService, HRPayrollService,
etc.) so they can be called through the secure ToolRegistry executor
without rewriting their internals.

Some legacy services expose a chat-style `run(school, user, question)`
(optionally with `context`); a couple (e.g. ExamGeneratorService,
RiskBatchService) expose a completely different, non-chat interface
(structured generation / batch-job methods) and were never actually
reachable through the old chat registry despite being wired in there.
LegacyServiceAdapter detects this via introspection and fails
*safely and legibly* — a clear "not available as a chat tool" result —
instead of the raw AttributeError/TypeError the old code path produced.
"""

import inspect
import logging

from ai_engine.services.tools.base import AITool, ToolExecutionError

logger = logging.getLogger(__name__)


class LegacyServiceAdapter(AITool):
    """
    Wraps a legacy service class/instance that exposes some form of
    `run(...)` into the AITool interface expected by ToolRegistry.
    """

    service_factory = None  # callable returning the service class or instance

    def _get_runner(self):
        service = self.service_factory()
        if service is None:
            raise ToolExecutionError(f"'{self.name}' is not available on this deployment.")

        runner = getattr(service, "run", None)
        if runner is None or not callable(runner):
            raise ToolExecutionError(
                f"'{self.name}' does not expose a chat-compatible interface."
            )
        return runner

    def run(self, *, school, user, question="", context=None, **kwargs):
        runner = self._get_runner()

        try:
            accepted = set(inspect.signature(runner).parameters.keys())
        except (TypeError, ValueError):
            accepted = {"school", "user", "question", "context"}

        call_kwargs = {}
        if "school" in accepted:
            call_kwargs["school"] = school
        if "user" in accepted:
            call_kwargs["user"] = user
        if "question" in accepted:
            call_kwargs["question"] = question
        if "context" in accepted:
            call_kwargs["context"] = context

        # If the legacy method doesn't actually accept the chat-style
        # arguments this tool needs, don't call it blind — that's how
        # the old registry produced raw tracebacks for exam/parent/etc.
        if not {"school", "user"}.issubset(call_kwargs.keys()):
            raise ToolExecutionError(
                f"'{self.name}' does not support conversational queries yet. "
                f"It is used by a different workflow in this app."
            )

        try:
            return runner(**call_kwargs)
        except TypeError as exc:
            raise ToolExecutionError(f"'{self.name}' rejected its arguments: {exc}")


def _import(path, attr):
    module = __import__(path, fromlist=[attr])
    return getattr(module, attr)


def _factory(path, attr):
    """Lazy import factory so a missing/broken service doesn't break the whole registry."""

    def make():
        try:
            return _import(path, attr)
        except ImportError:
            logger.warning("Tool service '%s.%s' is not available", path, attr)
            return None

    return make


class StudentQueryTool(LegacyServiceAdapter):
    name = "students"
    description = "Answer questions about enrolled students: counts, lists, lookups, basic records."
    required_capability = "students"
    service_factory = staticmethod(_factory("ai_engine.services.tools.student_tool", "StudentTool"))


class StaffQueryTool(LegacyServiceAdapter):
    name = "staff"
    description = "Answer questions about staff records, HR and payroll."
    required_capability = "staff"
    service_factory = staticmethod(_factory("ai_engine.services.hr_payroll_service", "HRPayrollService"))

    def _get_runner(self):
        service_cls = self.service_factory()
        if service_cls is None:
            raise ToolExecutionError(f"'{self.name}' is not available on this deployment.")
        instance = service_cls()
        return instance.run


class PayrollQueryTool(StaffQueryTool):
    name = "payroll"
    description = "Answer questions about payroll, salaries and staff payments."
    required_capability = "payroll"


class FinanceQueryTool(LegacyServiceAdapter):
    name = "finance"
    description = "Answer questions about fees, invoices, payments and financial standing."
    required_capability = "finance"
    service_factory = staticmethod(_factory("ai_engine.services.finance_engine", "FinanceInsightService"))

    def _get_runner(self):
        service_cls = self.service_factory()
        if service_cls is None:
            raise ToolExecutionError(f"'{self.name}' is not available on this deployment.")
        instance = service_cls()
        return instance.run


class ResearchQueryTool(AITool):
    name = "research"
    description = "Answer general Ghana education, GES/NaCCA/WAEC policy and curriculum questions."
    required_capability = "research"
    timeout_seconds = 25

    def run(self, *, school, user, question="", context=None, **kwargs):
        try:
            from ai_engine.services.research_service import ResearchService
        except ImportError:
            raise ToolExecutionError("The Ghana education research tool is not available.")

        service = ResearchService()
        runner = getattr(service, "run", None) or getattr(service, "answer", None)
        if runner is None:
            raise ToolExecutionError("The research tool does not support this query yet.")
        try:
            accepted = set(inspect.signature(runner).parameters.keys())
        except (TypeError, ValueError):
            accepted = {"question"}
        call_kwargs = {}
        if "question" in accepted:
            call_kwargs["question"] = question
        if "school" in accepted:
            call_kwargs["school"] = school
        if "user" in accepted:
            call_kwargs["user"] = user
        return runner(**call_kwargs)


TOOL_CLASSES = [
    StudentQueryTool,
    StaffQueryTool,
    PayrollQueryTool,
    FinanceQueryTool,
    ResearchQueryTool,
]
