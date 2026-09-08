"""
Copilot V4 - Full School Database Intelligence
===============================================

Deterministic, tenant-safe query layer for factual school questions.

Design rules:
* Database facts are calculated from Django ORM, never guessed by an LLM.
* Every queryset is explicitly scoped to the authenticated school.
* Sensitive/internal AI/security models are never exposed by the generic layer.
* The engine is additive: it runs before the existing specialized engines.
* Unsupported factual questions return None so the existing pipeline can
  handle educational/general questions; callers may apply their safety guard.
"""
import logging
import re
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

logger = logging.getLogger(__name__)

MAX_LIST = 100


class FullSchoolDatabaseIntelligence:
    """High-confidence database answers for the complete school domain."""

    def __init__(self, user, school, allowed_students=None):
        self.user = user
        self.school = school
        self.allowed_students = allowed_students

    @staticmethod
    def norm(value):
        text = str(value or "").strip().lower()
        text = re.sub(r"[^a-z0-9\s\-/]", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def meta(self, mode="verified_database", sources=None):
        return {
            "mode": mode,
            "sources": sources or ["school_database"],
            "scope": "authorized school data",
        }

    def can(self, capability):
        try:
            from .role_ai_policy import can_use
            return bool(can_use(self.user, capability))
        except Exception:
            return False

    def denied(self, label):
        return {"answer": f"You do not have permission to access {label}.", **self.meta("permission_denied")}

    def students(self):
        from students.models import Student
        if self.allowed_students is not None:
            return self.allowed_students
        return Student.objects.filter(school=self.school, is_active=True)

    def staff(self):
        from staff.models import StaffProfile
        return StaffProfile.objects.filter(school=self.school)

    def active_staff(self):
        return self.staff().filter(is_active=True)

    # ------------------------------------------------------------------
    # School / academic context
    # ------------------------------------------------------------------
    def school_context(self, q):
        if any(p in q for p in ("school name", "name of this school", "which school is this", "our school name")):
            name = str(self.school.name or "").strip()
            return {"answer": f"## School Information\n\nThe name of this school is **{name}**.", "data": {"school_name": name}, **self.meta()}

        if any(p in q for p in ("academic year", "academic term", "current term", "current academic year")) and any(a in q for a in ("current", "active", "what is", "which", "show", "tell me")):
            from school.models import AcademicYear, AcademicTerm
            year = AcademicYear.objects.filter(school=self.school, is_active=True).order_by("-start_date").first()
            if "term" in q:
                term = AcademicTerm.objects.filter(academic_year__school=self.school, is_active=True).select_related("academic_year").order_by("-start_date").first()
                if term:
                    return {"answer": f"## Current Academic Term\n\n**{term.name}** — {term.academic_year.name} ({term.start_date:%d %B %Y} to {term.end_date:%d %B %Y}).", "data": {"term": term.name, "academic_year": term.academic_year.name}, **self.meta()}
                return {"answer": "There is no active academic term configured in the school database.", **self.meta()}
            if year:
                return {"answer": f"## Current Academic Year\n\n**{year.name}** ({year.start_date:%d %B %Y} to {year.end_date:%d %B %Y}).", "data": {"academic_year": year.name}, **self.meta()}
            return {"answer": "There is no active academic year configured in the school database.", **self.meta()}
        return None

    # ------------------------------------------------------------------
    # Students
    # ------------------------------------------------------------------
    def student(self, q):
        if not any(w in q for w in ("student", "students", "learner", "learners", "pupil", "pupils")):
            return None
        if not self.can("students"):
            return self.denied("student information")
        qs = self.students()
        if "inactive" in q:
            from students.models import Student
            qs = Student.objects.filter(school=self.school, is_active=False)
        elif "all students" in q or "total students" in q:
            from students.models import Student
            qs = Student.objects.filter(school=self.school)
        if "male" in q or "female" in q:
            # The current Student model does not expose a guaranteed gender field;
            # never guess from names or user profiles.
            field_names = {f.name for f in qs.model._meta.get_fields()}
            if "gender" not in field_names:
                return {"answer": "The school database does not currently contain a Student gender field that I can verify.", **self.meta("database_unavailable")}
            gender = "MALE" if "male" in q else "FEMALE"
            qs = qs.filter(gender=gender)
        if "new student" in q or "new students" in q:
            if hasattr(qs.model, "is_new_student"):
                qs = qs.filter(is_new_student=True)
        # Natural-language class filter: "students in Basic 1" /
        # "how many students are in JHS 2". We only apply it when the
        # phrase clearly targets a class, avoiding guesses from names.
        class_match = re.search(r"(?:students?|learners?|pupils?)\s+(?:are\s+)?(?:in|from|of)\s+(.+?)(?:\?|$)", q)
        if class_match:
            class_name = class_match.group(1).strip()
            class_name = re.sub(r"^(?:the|class)\s+", "", class_name).strip()
            try:
                qs = qs.filter(school_class__name__iexact=class_name)
            except Exception:
                pass
        if not any(a in q for a in ("how many", "number of", "count", "total", "list", "show", "who", "which", "names", "population")):
            return None
        count = qs.count()
        if any(a in q for a in ("list", "show", "who", "which", "names")):
            rows = qs.select_related("user", "school_class", "grade_level").order_by("user__last_name", "user__first_name")[:MAX_LIST]
            lines = [f"## Students\n\n**{count:,} students** match your query.", ""]
            for i, s in enumerate(rows, 1):
                name = s.user.get_full_name().strip() or s.user.username
                cls = getattr(s.school_class, "name", None) or "Not assigned"
                lines.append(f"{i}. **{name}** — {cls}")
            if count > MAX_LIST:
                lines.append(f"\n*Showing the first {MAX_LIST} of {count:,} records.*")
            return {"answer": "\n".join(lines), "data": {"count": count}, **self.meta()}
        status = "inactive" if "inactive" in q else "active" if "active" in q else "all"
        return {"answer": f"There are **{count:,} {status} students** in the authorized school scope.", "data": {"count": count, "status": status}, **self.meta()}

    # ------------------------------------------------------------------
    # Staff / HR / leave
    # ------------------------------------------------------------------
    def staff_question(self, q):
        if not any(w in q for w in ("staff", "employee", "employees", "personnel", "teacher", "teachers")):
            return None
        # Leave-specific questions must be handled by leave_question(), not
        # by the generic staff handler. Otherwise questions such as
        # "Which staff members are currently on leave?" are incorrectly
        # interpreted as "list active staff".
        if "leave" in q or "on leave" in q:
            return None
        if not self.can("staff"):
            return self.denied("staff information")
        qs = self.staff()
        if any(x in q for x in ("inactive", "former staff", "former employee")):
            qs = qs.filter(is_active=False)
        else:
            qs = qs.filter(is_active=True)
        if "teacher" in q or "teaching staff" in q:
            qs = qs.filter(staff_position="TEACHER")
        elif "non teaching" in q or "non-teaching" in q:
            qs = qs.exclude(staff_position="TEACHER")
        positions = {
            "bursar": "BURSAR", "finance officer": "BURSAR", "registrar": "REGISTRAR",
            "hod": "HOD", "head of department": "HOD", "secretary": "SECRETARY",
            "librarian": "LIBRARIAN", "it support": "IT_SUPPORT", "school administrator": "SCHOOL_ADMIN",
        }
        for label, value in positions.items():
            if label in q:
                qs = qs.filter(staff_position=value)
                break
        department_match = re.search(r"(?:staff|employees?|teachers?)\s+(?:in|from|of)\s+(.+?)(?:\?|$)", q)
        if department_match and "department" in q:
            dept_name = re.sub(r"\s+department$", "", department_match.group(1).strip()).strip()
            qs = qs.filter(department__name__icontains=dept_name)
        action = any(a in q for a in ("how many", "number of", "count", "total", "list", "show", "who", "which", "names", "available", "currently working", "at work"))
        if not action:
            return None
        count = qs.count()
        availability = any(a in q for a in ("available", "currently working", "at work"))
        if availability:
            today = timezone.localdate()
            try:
                from staff.models import LeaveRequest
                leave_ids = LeaveRequest.objects.filter(
                    school=self.school, staff__school=self.school, staff__is_active=True,
                    status__in=("APPROVED", "TAKEN"), start_date__lte=today, end_date__gte=today,
                ).values_list("staff_id", flat=True)
                available = qs.exclude(pk__in=leave_ids).count()
                on_leave = count - available
            except Exception:
                logger.exception("Staff availability lookup failed")
                return {"answer": "I could not verify staff availability from the school database. No unverified answer was provided.", **self.meta("database_error")}
            return {"answer": f"## Staff Availability\n\nThere are **{count:,} active staff members** matching your query. As of **{today:%d %B %Y}**, **{available:,}** are available and **{on_leave:,}** are on approved/taken leave.", "data": {"active_staff": count, "available_staff": available, "on_leave": on_leave, "date": today.isoformat()}, **self.meta()}
        if any(a in q for a in ("list", "show", "who", "which", "names")):
            rows = qs.select_related("user", "department", "staff_grade").order_by("user__last_name", "user__first_name")[:MAX_LIST]
            lines = [f"## Staff\n\n**{count:,} staff members** match your query.", ""]
            for i, s in enumerate(rows, 1):
                name = s.user.get_full_name().strip() or s.user.username
                pos = s.get_staff_position_display()
                dept = getattr(s.department, "name", None) or "No department"
                lines.append(f"{i}. **{name}** — {pos} — {dept}")
            if count > MAX_LIST:
                lines.append(f"\n*Showing the first {MAX_LIST} of {count:,} records.*")
            return {"answer": "\n".join(lines), "data": {"count": count}, **self.meta()}
        label = "inactive" if "inactive" in q or "former" in q else "active"
        return {"answer": f"There are **{count:,} {label} staff members** matching your query.", "data": {"count": count, "status": label}, **self.meta()}

    def leave_question(self, q):
        """Answer current staff-leave questions from LeaveRequest only."""
        if "leave" not in q and "on leave" not in q:
            return None
        if not self.can("staff"):
            return self.denied("staff leave information")

        from staff.models import LeaveRequest

        today = timezone.localdate()
        qs = LeaveRequest.objects.filter(
            school=self.school,
            staff__school=self.school,
        ).select_related("staff__user", "staff__department", "staff__staff_grade", "leave_type")

        # "currently", "today", "now", and "available" in a leave context
        # mean a leave transaction that covers today. Only APPROVED/TAKEN
        # requests count as active leave; PENDING/DRAFT/REJECTED/CANCELLED
        # requests must never be presented as people currently on leave.
        current = any(x in q for x in (
            "today", "currently", "right now", "now", "at present",
            "on leave", "available",
        ))

        if current:
            qs = qs.filter(
                status__in=("APPROVED", "TAKEN"),
                start_date__lte=today,
                end_date__gte=today,
                staff__is_active=True,
            )

            # Optional role filter.
            if "teacher" in q or "teaching staff" in q:
                qs = qs.filter(staff__staff_position="TEACHER")

            staff_ids = list(qs.values_list("staff_id", flat=True).distinct())
            count = len(staff_ids)
            wants_list = any(x in q for x in ("who", "which", "list", "show", "names"))

            if not wants_list:
                return {
                    "answer": (
                        f"As of **{today:%d %B %Y}**, **{count:,} staff member"
                        f"{'s' if count != 1 else ''}** are on approved/taken leave."
                    ),
                    "data": {"count": count, "date": today.isoformat()},
                    **self.meta(),
                }

            rows = list(
                qs.order_by(
                    "staff__user__last_name",
                    "staff__user__first_name",
                    "start_date",
                )
            )

            # One person can have more than one overlapping record. Present
            # each person once and combine the verified leave details.
            grouped = {}
            for r in rows:
                key = r.staff_id
                grouped.setdefault(key, {"staff": r.staff, "leaves": []})["leaves"].append(r)

            lines = [
                "## Staff Currently on Leave",
                "",
                f"**{count:,} staff member{'s' if count != 1 else ''}** "
                f"currently have approved/taken leave covering **{today:%d %B %Y}**.",
                "",
            ]
            records = []
            for i, item in enumerate(grouped.values(), 1):
                staff = item["staff"]
                name = staff.user.get_full_name().strip() or staff.user.username
                position = staff.get_staff_position_display()
                department = getattr(staff.department, "name", None) or "No department"
                leave_details = []
                for leave in item["leaves"]:
                    leave_name = getattr(leave.leave_type, "name", None) or "Leave"
                    leave_details.append(
                        f"{leave_name} ({leave.start_date:%d %b %Y} – {leave.end_date:%d %b %Y})"
                    )
                details = "; ".join(leave_details)
                lines.append(f"{i}. **{name}** — {position} — {department}")
                lines.append(f"   - {details}")
                records.append({"name": name, "position": position, "department": department, "leave": leave_details})

            if count > MAX_LIST:
                lines.append(f"\n*Showing the first {MAX_LIST} of {count:,} staff members.*")

            return {
                "answer": "\n".join(lines),
                "data": {"count": count, "date": today.isoformat(), "staff": records[:MAX_LIST]},
                **self.meta(),
            }

        # Non-current leave questions can safely report request totals.
        if any(x in q for x in ("how many", "number of", "count", "total", "list", "show", "who", "which")):
            count = qs.count()
            return {
                "answer": f"There are **{count:,} leave requests** in the school database.",
                "data": {"count": count},
                **self.meta(),
            }
        return None

    # ------------------------------------------------------------------
    # Generic entity registry. This gives V4 coverage for the whole domain
    # without exposing internal AI/security records.
    # ------------------------------------------------------------------
    def registry(self):
        specs = []
        def add(model, aliases, capability, label, school_lookup="school", string_fields=None):
            specs.append({"model": model, "aliases": aliases, "capability": capability, "label": label, "school_lookup": school_lookup, "string_fields": string_fields or ()})
        try:
            from staff.models import Department, StaffGrade, Allowance, Deduction, PayrollPeriod, PayrollRun, Payslip, LeaveType, StaffLeaveBalance, LeaveLedger, TeacherAbsence
            add(Department, ("department", "departments"), "staff", "departments")
            add(StaffGrade, ("staff grade", "staff grades"), "staff", "staff grades")
            add(Allowance, ("allowance", "allowances"), "payroll", "allowances")
            add(Deduction, ("deduction", "deductions"), "payroll", "deductions")
            add(PayrollPeriod, ("payroll period", "payroll periods"), "payroll", "payroll periods")
            add(PayrollRun, ("payroll run", "payroll runs"), "payroll", "payroll runs")
            add(Payslip, ("payslip", "payslips", "pay slips", "pay slip"), "payroll", "payslips")
            add(LeaveType, ("leave type", "leave types"), "staff", "leave types")
            add(StaffLeaveBalance, ("leave balance", "leave balances"), "staff", "staff leave balances")
            add(LeaveLedger, ("leave ledger", "leave ledgers"), "staff", "leave ledger")
            add(TeacherAbsence, ("teacher absence", "teacher absences"), "staff", "teacher absences")
        except Exception: pass
        try:
            from students.models import GradeLevel, StudentEnrollmentType
            add(GradeLevel, ("grade level", "grade levels", "student grade", "student grades"), "students", "grade levels")
            add(StudentEnrollmentType, ("enrollment type", "enrollment types", "student enrollment type", "student enrollment types"), "students", "student enrollment types")
        except Exception: pass
        try:
            from academics.models import Subject, SchoolClass, TeacherAssignment, ClassSubject, TeacherClassAssignment, Room, TimeSlot, Timetable, TimetableEntry, TeacherWorkload, StudentPromotion, PromotionBatch
            from staff.models import Teacher
            add(Subject, ("subject", "subjects"), "academics", "subjects")
            add(SchoolClass, ("class", "classes", "school class", "school classes"), "academics", "school classes")
            add(Teacher, ("teacher record", "teacher records", "teachers"), "staff", "teacher records")
            add(TeacherAssignment, ("teacher assignment", "teacher assignments"), "academics", "teacher assignments")
            add(ClassSubject, ("class subject", "class subjects"), "academics", "class subjects")
            add(TeacherClassAssignment, ("teacher class assignment", "teacher class assignments"), "academics", "teacher-class assignments")
            add(Room, ("room", "rooms", "classroom", "classrooms"), "academics", "rooms")
            add(TimeSlot, ("time slot", "time slots"), "academics", "time slots")
            add(Timetable, ("timetable", "timetables"), "academics", "timetables")
            add(TimetableEntry, ("timetable entry", "timetable entries"), "academics", "timetable entries")
            add(TeacherWorkload, ("teacher workload", "teacher workloads"), "academics", "teacher workloads")
            add(StudentPromotion, ("student promotion", "student promotions", "promotion"), "academics", "student promotions")
            add(PromotionBatch, ("promotion batch", "promotion batches"), "academics", "promotion batches")
        except Exception: pass
        try:
            from assessments.models import Assessment, Grade, AssessmentQuestion, TerminalResult
            add(Assessment, ("assessment", "assessments", "exam", "exams", "quiz", "quizzes", "assignment", "assignments"), "academics", "assessments")
            add(Grade, ("grade records", "grade record", "marks", "mark records", "scores"), "academics", "grade records", "assessment__school")
            add(AssessmentQuestion, ("assessment question", "assessment questions", "exam question", "exam questions"), "academics", "assessment questions", "assessment__school")
            add(TerminalResult, ("terminal result", "terminal results", "report result", "report results"), "academics", "terminal results")
        except Exception: pass
        try:
            from attendance.models import Attendance
            add(Attendance, ("attendance record", "attendance records", "attendance"), "attendance", "attendance records")
        except Exception: pass
        try:
            from finance.models import FeeCategory, FeeStructure, FeeStructureItem, FeeWaiver, TransportRoute, StudentTransportSubscription, Invoice, InvoiceLineItem, Payment, StudentFinancialLedger, LogisticItem, LogisticIssuance, StudentFee, StudentFeeItem, FeeAddOnStructure, FeeAddOnItem, StudentFeeAdjustment, EnrollmentFeePackage, StudentFeeEnrollment, ClassAddOnStructure, ClassAddOnItem, PaymentReceipt
            add(FeeCategory, ("fee category", "fee categories"), "finance", "fee categories")
            add(FeeStructure, ("fee structure", "fee structures"), "finance", "fee structures")
            add(FeeStructureItem, ("fee structure item", "fee structure items"), "finance", "fee structure items", "fee_structure__school")
            add(FeeWaiver, ("fee waiver", "fee waivers", "waiver", "waivers"), "finance", "fee waivers")
            add(TransportRoute, ("transport route", "transport routes", "bus route", "bus routes"), "finance", "transport routes")
            add(StudentTransportSubscription, ("transport subscription", "transport subscriptions", "bus subscription"), "finance", "transport subscriptions", "student__school")
            add(Invoice, ("invoice", "invoices", "bill", "bills"), "finance", "invoices")
            add(InvoiceLineItem, ("invoice line", "invoice lines", "invoice item", "invoice items"), "finance", "invoice line items", "invoice__school")
            add(Payment, ("payment", "payments", "payment record", "payment records"), "finance", "payments", "invoice__school")
            add(StudentFinancialLedger, ("financial ledger", "student financial ledger", "ledger entries"), "finance", "financial ledger")
            add(LogisticItem, ("logistic item", "logistics", "stock item", "inventory item", "inventory"), "finance", "logistic/inventory items")
            add(LogisticIssuance, ("logistic issuance", "logistic issuances", "item issuance"), "finance", "logistic issuances", "school")
            add(StudentFee, ("student fee", "student fees"), "finance", "student fees")
            add(StudentFeeItem, ("student fee item", "student fee items"), "finance", "student fee items", "student_fee__school")
            add(FeeAddOnStructure, ("fee addon", "fee add on", "fee add-ons", "fee addons"), "finance", "fee add-on structures")
            add(FeeAddOnItem, ("fee addon item", "fee add-on item", "fee addon items"), "finance", "fee add-on items", "addon_structure__school")
            add(StudentFeeAdjustment, ("fee adjustment", "fee adjustments"), "finance", "fee adjustments")
            add(EnrollmentFeePackage, ("enrollment fee package", "enrollment fee packages", "fee package", "fee packages"), "finance", "enrollment fee packages")
            add(StudentFeeEnrollment, ("student fee enrollment", "student fee enrollments"), "finance", "student fee enrollments")
            add(ClassAddOnStructure, ("class addon", "class add-on", "class add-ons", "class addons"), "finance", "class add-on structures")
            add(ClassAddOnItem, ("class addon item", "class add-on item", "class addon items"), "finance", "class add-on items", "addon_structure__school")
            add(PaymentReceipt, ("payment receipt", "payment receipts", "receipt", "receipts"), "finance", "payment receipts", "payment__invoice__school")
        except Exception: pass
        try:
            from library.models import BookCategory, Book, BookBorrowing
            add(BookCategory, ("book category", "book categories"), "school_intelligence", "book categories")
            add(Book, ("book", "books", "library book", "library books"), "school_intelligence", "books")
            add(BookBorrowing, ("borrowing", "borrowings", "book borrowing", "book borrowings", "library borrowing"), "school_intelligence", "book borrowings")
        except Exception: pass
        try:
            from communication.models import Announcement
            add(Announcement, ("announcement", "announcements"), "school_intelligence", "announcements")
        except Exception: pass
        try:
            from school.models import AcademicYear, AcademicTerm
            add(AcademicYear, ("academic year", "academic years"), "school_intelligence", "academic years")
            add(AcademicTerm, ("academic term", "academic terms", "terms"), "school_intelligence", "academic terms", "academic_year__school")
        except Exception: pass
        return specs

    @staticmethod
    def _label(obj):
        try:
            return str(obj)
        except Exception:
            return obj.__class__.__name__

    def generic_entity(self, q):
        action = any(a in q for a in ("how many", "number of", "count", "total", "list", "show", "which", "what are"))
        if not action:
            return None
        for spec in self.registry():
            if not any(alias in q for alias in spec["aliases"]):
                continue
            if not self.can(spec["capability"]):
                return self.denied(spec["label"])
            model = spec["model"]
            lookup = spec["school_lookup"]
            try:
                qs = model.objects.filter(**{lookup: self.school})
                if hasattr(model, "is_active"):
                    if "inactive" in q:
                        qs = qs.filter(is_active=False)
                    elif "active" in q:
                        qs = qs.filter(is_active=True)
                if hasattr(model, "status"):
                    for status in ("CONFIRMED", "APPROVED", "PAID", "UNPAID", "PARTIAL", "ACTIVE", "DRAFT", "COMPLETE"):
                        if status.lower().replace("_", " ") in q:
                            qs = qs.filter(status=status)
                            break
                count = qs.count()
                if any(a in q for a in ("list", "show", "which", "what are")):
                    rows = qs[:MAX_LIST]
                    lines = [f"## {spec['label'].title()}\n\n**{count:,} {spec['label']}** match your query.", ""]
                    for i, obj in enumerate(rows, 1):
                        lines.append(f"{i}. **{self._label(obj)}**")
                    if count > MAX_LIST:
                        lines.append(f"\n*Showing the first {MAX_LIST} of {count:,} records.*")
                    return {"answer": "\n".join(lines), "data": {"count": count, "entity": spec["label"]}, **self.meta()}
                return {"answer": f"There are **{count:,} {spec['label']}** in the school database.", "data": {"count": count, "entity": spec["label"]}, **self.meta()}
            except Exception:
                logger.exception("Generic database entity query failed: %s", spec["label"])
                return {"answer": "I could not safely verify that information from the school database. No unverified answer was provided.", **self.meta("database_error")}
        return None

    # ------------------------------------------------------------------
    # Domain summaries
    # ------------------------------------------------------------------
    def finance_summary(self, q):
        if not any(w in q for w in ("fee", "fees", "finance", "financial", "invoice", "invoices", "payment", "payments", "outstanding", "owing", "owe", "receivable", "collection", "collected")):
            return None
        if not self.can("finance"):
            return self.denied("financial information")
        if not any(a in q for a in ("summary", "how much", "total", "outstanding", "owing", "owe", "number of", "count", "how many")):
            return None
        try:
            from finance.models import Invoice, Payment
            invoices = Invoice.objects.filter(school=self.school)
            payments = Payment.objects.filter(invoice__school=self.school)
            total_billed = sum((i.total_amount for i in invoices), Decimal("0"))
            total_paid = payments.filter(status="CONFIRMED").aggregate(v=Sum("amount"))["v"] or Decimal("0")
            outstanding = total_billed - total_paid
            if "payment" in q or "collection" in q or "collected" in q:
                count = payments.count()
                return {"answer": f"## Payments\n\nThere are **{count:,} payment records**. Confirmed payments total **GH₵{total_paid:,.2f}**.", "data": {"payment_records": count, "confirmed": str(total_paid)}, **self.meta()}
            return {"answer": f"## Finance Summary\n\n- **Invoices:** {invoices.count():,}\n- **Total billed:** **GH₵{total_billed:,.2f}**\n- **Total paid:** **GH₵{total_paid:,.2f}**\n- **Outstanding:** **GH₵{outstanding:,.2f}**", "data": {"invoices": invoices.count(), "billed": str(total_billed), "paid": str(total_paid), "outstanding": str(outstanding)}, **self.meta()}
        except Exception:
            logger.exception("Finance summary failed")
            return {"answer": "I could not safely verify the requested financial information. No unverified answer was provided.", **self.meta("database_error")}

    def attendance(self, q):
        if "attendance" not in q and not any(x in q for x in ("present today", "absent today", "late today")):
            return None
        if not self.can("attendance"):
            return self.denied("attendance information")
        try:
            from attendance.models import Attendance
            today = timezone.localdate()
            qs = Attendance.objects.filter(school=self.school, date=today)
            counts = {s: qs.filter(status=s).count() for s in ("PRESENT", "ABSENT", "LATE", "EXCUSED")}
            recorded = qs.values("student_id").distinct().count()
            if any(x in q for x in ("who", "which", "list", "names")):
                status = "ABSENT" if "absent" in q else "LATE" if "late" in q else "PRESENT" if "present" in q else None
                if status:
                    rows = qs.filter(status=status).select_related("student__user").order_by("student__user__last_name")[:MAX_LIST]
                    lines = [f"## {status.title()} Students — {today:%d %B %Y}", ""]
                    for i, a in enumerate(rows, 1):
                        lines.append(f"{i}. **{a.student.user.get_full_name() or a.student.user.username}**")
                    return {"answer": "\n".join(lines), "data": {"count": counts[status]}, **self.meta()}
            return {"answer": f"## Today's Attendance — {today:%d %B %Y}\n\n**{recorded:,} students** have attendance recorded.\n\n- Present: **{counts['PRESENT']:,}**\n- Absent: **{counts['ABSENT']:,}**\n- Late: **{counts['LATE']:,}**\n- Excused: **{counts['EXCUSED']:,}**", "data": {"recorded_students": recorded, **{k.lower(): v for k, v in counts.items()}}, **self.meta()}
        except Exception:
            logger.exception("Attendance intelligence failed")
            return {"answer": "I could not safely verify attendance. No unverified answer was provided.", **self.meta("database_error")}

    def academic_summary(self, q):
        if not any(x in q for x in ("result", "results", "assessment", "assessments", "exam", "exams", "marks", "scores", "performance")):
            return None
        if not self.can("academics"):
            return self.denied("academic information")
        if not any(x in q for x in ("how many", "number of", "count", "total", "average", "highest", "lowest", "summary")):
            return None
        try:
            from assessments.models import Assessment, Grade, TerminalResult
            assessment_count = Assessment.objects.filter(school=self.school).count()
            grade_qs = Grade.objects.filter(assessment__school=self.school)
            grade_count = grade_qs.count()
            terminal_qs = TerminalResult.objects.filter(school=self.school)
            terminal_count = terminal_qs.count()
            avg = grade_qs.aggregate(v=Avg("score_achieved"))["v"]
            if "terminal" in q or "report result" in q:
                return {"answer": f"There are **{terminal_count:,} terminal result records** in the school database.", "data": {"terminal_results": terminal_count}, **self.meta()}
            if "assessment" in q or "exam" in q:
                return {"answer": f"## Academic Records\n\n- **Assessments:** {assessment_count:,}\n- **Grade records:** {grade_count:,}\n- **Terminal results:** {terminal_count:,}", "data": {"assessments": assessment_count, "grades": grade_count, "terminal_results": terminal_count}, **self.meta()}
            answer = f"There are **{grade_count:,} grade records** and **{terminal_count:,} terminal results** in the school database."
            if avg is not None:
                answer += f" The average recorded assessment score is **{avg:.2f}**."
            return {"answer": answer, "data": {"grades": grade_count, "terminal_results": terminal_count, "average": str(avg) if avg is not None else None}, **self.meta()}
        except Exception:
            logger.exception("Academic summary failed")
            return {"answer": "I could not safely verify the requested academic information. No unverified answer was provided.", **self.meta("database_error")}

    def library(self, q):
        if not any(x in q for x in ("book", "books", "library", "borrow", "borrowing")):
            return None
        if not self.can("school_intelligence"):
            return self.denied("library information")
        try:
            from library.models import Book, BookBorrowing
            if "borrow" in q:
                qs = BookBorrowing.objects.filter(school=self.school)
                if "overdue" in q:
                    qs = qs.filter(status="ACTIVE", due_date__lt=timezone.localdate())
                elif "active" in q or "currently" in q:
                    qs = qs.filter(status="ACTIVE")
                count = qs.count()
                return {"answer": f"There are **{count:,} matching library borrowing records** in the school database.", "data": {"count": count}, **self.meta()}
            books = Book.objects.filter(school=self.school)
            total_titles = books.count()
            total_copies = books.aggregate(v=Sum("total_copies"))["v"] or 0
            available = books.aggregate(v=Sum("available_copies"))["v"] or 0
            if any(x in q for x in ("how many", "number of", "count", "total", "summary")):
                return {"answer": f"## Library Summary\n\n- **Book titles:** {total_titles:,}\n- **Total copies:** {total_copies:,}\n- **Available copies:** {available:,}", "data": {"titles": total_titles, "copies": total_copies, "available": available}, **self.meta()}
        except Exception:
            logger.exception("Library intelligence failed")
            return {"answer": "I could not safely verify the requested library information. No unverified answer was provided.", **self.meta("database_error")}
        return None

    def answer(self, question):
        q = self.norm(question)
        if not q:
            return None
        handlers = (
            self.school_context,
            self.leave_question,
            self.staff_question,
            self.student,
            self.attendance,
            self.finance_summary,
            self.academic_summary,
            self.library,
            self.generic_entity,
        )
        for handler in handlers:
            try:
                result = handler(q)
                if result is not None:
                    return result
            except Exception:
                logger.exception("Full V4 database handler failed: %s", getattr(handler, "__name__", handler))
                return {"answer": "I could not safely verify that information from the school database. No unverified answer was provided.", **self.meta("database_error")}
        return None

    def looks_like_school_fact(self, q):
        q = self.norm(q)
        entities = (
            "school", "student", "students", "staff", "teacher", "employee", "class", "subject", "attendance",
            "fee", "fees", "invoice", "payment", "finance", "payroll", "salary", "leave", "result", "results",
            "exam", "assessment", "book", "library", "announcement", "department", "academic", "timetable",
            "promotion", "transport", "inventory", "stock", "allowance", "deduction", "payslip", "receipt",
            "borrowing", "absence", "workload", "room", "term", "year",
        )
        actions = (
            "how many", "how much", "who", "which", "what is", "what are", "show", "list", "give me", "tell me",
            "total", "count", "number of", "available", "current", "today", "this term", "this year", "outstanding",
            "balance", "owing", "owe", "summary", "active", "inactive",
        )
        return any(e in q for e in entities) and any(a in q for a in actions)
