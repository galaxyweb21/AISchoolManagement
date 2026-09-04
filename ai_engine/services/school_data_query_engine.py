# ai_engine/services/school_data_query_engine.py

"""
Deterministic, tenant-safe school data query engine.

IMPORTANT ARCHITECTURE
----------------------

The LLM must NOT calculate or invent school database facts.

This service answers high-confidence factual questions directly from
the Django ORM.

Examples:
    - How many active students?
    - Who are the active students?
    - What is today's attendance?
    - What is the attendance rate?
    - Which students owe fees?
    - Which staff members are currently on leave?

If a question is not confidently understood, this engine returns None
and the normal SchoolCopilotEngine can handle the question.

SECURITY
--------

Every query is scoped to the authenticated user's school.

Staff leave information is additionally restricted to school
administration roles because leave information is HR-sensitive.
"""

import re
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from students.models import Student
from attendance.models import Attendance


class SchoolDataQueryEngine:
    """
    Exact database answers for high-confidence school-data questions.
    """

    def __init__(self, user, school, allowed_students=None):
        self.user = user
        self.school = school
        self.allowed_students = allowed_students

    # ==================================================================
    # BASIC HELPERS
    # ==================================================================

    @staticmethod
    def _norm(value):
        """
        Normalize text for reliable comparison.
        """
        return re.sub(
            r"\s+",
            " ",
            str(value or "").strip().lower(),
        )

    def _meta(self, mode="database"):
        """
        Common metadata returned with deterministic answers.
        """
        return {
            "mode": mode,
            "sources": ["school_database"],
            "scope": "authorized school data",
        }

    def _students(self):
        """
        Return the students the current user is authorized to see.
        """
        if self.allowed_students is not None:
            return self.allowed_students

        return Student.objects.filter(
            school=self.school,
            is_active=True,
        )

    # ==================================================================
    # ATTENDANCE
    # ==================================================================

    def _attendance_queryset(self):
        """
        Attendance restricted to the current school and authorized
        students.
        """
        queryset = Attendance.objects.filter(
            school=self.school,
        )

        students = self._students()

        if students is not None:
            queryset = queryset.filter(
                student__in=students,
            )

        return queryset

    # ==================================================================
    # FINANCE
    # ==================================================================

    def _has_finance_access(self):
        """
        Check finance access using the existing AI role policy.
        """
        try:
            from .role_ai_policy import can_use

            return can_use(
                self.user,
                "finance",
            )

        except Exception:
            return False

    def _get_invoice_queryset(self):
        """
        Return invoices restricted to the current school and
        authorized students.
        """
        try:
            from finance.models import Invoice

            queryset = Invoice.objects.filter(
                school=self.school,
            )

            students = self._students()

            if students is not None:
                queryset = queryset.filter(
                    student__in=students,
                )

            return queryset

        except ImportError:
            return None

    # ==================================================================
    # STAFF / HR ACCESS
    # ==================================================================

    def _has_staff_leave_access(self):
        """
        Staff leave information is HR-sensitive.

        At present, the safe access boundary is school administration.

        We deliberately do NOT expose school-wide staff leave records
        to ordinary teachers simply because they can use the Copilot.
        """

        user_role = str(
            getattr(
                self.user,
                "role",
                "",
            )
            or ""
        ).upper()

        return user_role in {
            "SUPER_ADMIN",
            "SCHOOL_ADMIN",
        }

    def _get_leave_request_queryset(self):
        """
        Import LeaveRequest safely and return a school-scoped queryset.

        LeaveRequest is the actual source of truth for current leave.

        StaffGrade is NOT used here because StaffGrade contains leave
        entitlement/configuration, not current leave transactions.
        """
        try:
            from staff.models import LeaveRequest

            return (
                LeaveRequest.objects
                .filter(
                    school=self.school,
                )
                .select_related(
                    "staff",
                    "staff__user",
                    "staff__department",
                    "staff__staff_grade",
                    "leave_type",
                )
            )

        except ImportError:
            return None

    # ==================================================================
    # FEE QUESTION DETECTION
    # ==================================================================

    def _is_owing_fees_question(self, q):
        phrases = (
            "owing school fees",
            "owing fees",
            "owe school fees",
            "owe fees",
            "students owing",
            "student owing",
            "outstanding fees",
            "outstanding school fees",
            "unpaid fees",
            "unpaid school fees",
            "fee balance",
            "school fee balance",
            "students with fees",
            "student with fees",
            "how many students owe",
            "how many students are owing",
            "list students owing",
            "students who owe",
            "students with outstanding",
            "fee arrears",
            "school fees arrears",
            "students in debt",
            "debtors",
            "fee debtors",
            "who owes fees",
            "who hasn't paid fees",
            "students not paid fees",
            "students who haven't paid",
            "fee defaulters",
            "defaulters",
        )

        return any(
            phrase in q
            for phrase in phrases
        )

    def _is_fee_balance_question(self, q):
        phrases = (
            "total outstanding",
            "total fees",
            "total school fees",
            "total fee balance",
            "total outstanding fees",
            "total owing",
            "overall outstanding",
            "total debt",
            "total fee arrears",
            "total unpaid fees",
            "what is the total",
            "how much is owed",
            "total amount owing",
            "total fees outstanding",
            "outstanding balance",
            "total balance",
        )

        return any(
            phrase in q
            for phrase in phrases
        )

    # ==================================================================
    # FEE ANSWERS
    # ==================================================================

    def _extract_person_name(self, question):
        """Extract a likely student name from common fee-balance wording."""
        text = str(question or '').strip()
        patterns = (
            r'\b(?:balance|fees?|fee balance|amount owing|amount owed)\s+(?:for|of)\s+(.+)$',
            r'\b(?:how much|what is)\s+(?:does|do)?\s*(?:the student|student)?\s*(?:owe|owes|pay|pays)?\s*(?:for|of)?\s*(.+)$',
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                candidate = re.sub(r'[?!.]+$', '', match.group(1)).strip()
                candidate = re.sub(r'^(?:student|the student)\s+', '', candidate, flags=re.IGNORECASE)
                if 2 <= len(candidate.split()) <= 5:
                    return candidate
        return None

    def _answer_named_student_fee(self, question):
        """Return an exact school-scoped fee balance for a named student."""
        if not self._has_finance_access():
            return {
                'answer': 'You do not have permission to access financial information.',
                **self._meta('permission_denied'),
            }

        name = self._extract_person_name(question)
        if not name:
            return None

        from django.db.models import Q
        tokens = [t for t in re.split(r'\s+', name) if t]
        students = self._students().select_related('user', 'school_class')
        query = Q()
        for token in tokens:
            query &= (Q(user__first_name__icontains=token) | Q(user__last_name__icontains=token))
        matches = list(students.filter(query)[:5])

        if not matches:
            return {
                'answer': f'No active student matching **{name}** was found in your authorized school scope.',
                **self._meta('database'),
            }
        if len(matches) > 1:
            names = ', '.join(m.user.get_full_name().strip() for m in matches)
            return {
                'answer': f'I found multiple students matching **{name}**: {names}. Please provide the admission number or full name.',
                **self._meta('database'),
            }

        student = matches[0]
        invoices = self._get_invoice_queryset().filter(student=student).exclude(status='VOID')
        total = Decimal('0.00')
        paid = Decimal('0.00')
        rows = []
        for invoice in invoices.select_related('academic_term'):
            inv_total = invoice.line_items.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            inv_paid = invoice.payments.filter(status='CONFIRMED').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            balance = max(inv_total - inv_paid, Decimal('0.00'))
            total += inv_total
            paid += inv_paid
            rows.append((invoice, inv_total, inv_paid, balance))

        balance = max(total - paid, Decimal('0.00'))
        name_display = student.user.get_full_name().strip() or student.user.username
        answer = (
            f'## Fee Balance — {name_display}\n\n'
            f'- **Total billed:** ₵{total:,.2f}\n'
            f'- **Total paid:** ₵{paid:,.2f}\n'
            f'- **Balance owing:** **₵{balance:,.2f}**\n'
            f'- **Invoices:** {len(rows):,}'
        )
        return {
            'answer': answer,
            'data': {
                'student': name_display,
                'total_billed': float(total),
                'total_paid': float(paid),
                'balance_due': float(balance),
                'invoice_count': len(rows),
            },
            **self._meta('database'),
        }

    def _answer_owing_fees(self, question):
        """
        Answer questions about students owing fees.
        """

        if not self._has_finance_access():
            return {
                "answer": (
                    "You do not have permission to access "
                    "financial information. Please contact "
                    "the school administration."
                ),
                **self._meta("permission_denied"),
            }

        invoice_qs = self._get_invoice_queryset()

        if invoice_qs is None:
            return {
                "answer": (
                    "The finance module is currently unavailable. "
                    "Please try again later."
                ),
                **self._meta("error"),
            }

        unpaid_invoices = (
            invoice_qs
            .filter(
                status__in=[
                    "UNPAID",
                    "PARTIAL",
                ],
            )
            .select_related(
                "student",
                "student__user",
            )
        )

        students_with_balance = {}
        total_outstanding = Decimal("0")

        for invoice in unpaid_invoices:
            balance = invoice.balance_due

            if balance <= 0:
                continue

            student_id = invoice.student_id

            if student_id not in students_with_balance:
                students_with_balance[student_id] = {
                    "student": invoice.student,
                    "balance": Decimal("0"),
                    "invoices": [],
                }

            students_with_balance[student_id]["balance"] += balance

            students_with_balance[student_id]["invoices"].append(
                invoice
            )

            total_outstanding += balance

        owing_students = list(
            students_with_balance.values()
        )

        owing_students.sort(
            key=lambda item: item["balance"],
            reverse=True,
        )

        total_owing = len(
            owing_students
        )

        q = self._norm(question)

        is_count_only = any(
            phrase in q
            for phrase in (
                "how many",
                "count",
                "number",
                "total",
                "how much",
                "what is",
            )
        )

        if total_owing == 0:
            if is_count_only:
                answer = (
                    "## School Fees Status\n\n"
                    "**No students** are currently owing school fees. "
                    "All students have cleared their fee obligations. ✅"
                )
            else:
                answer = (
                    "## School Fees Status\n\n"
                    "✅ **No students** are currently owing school fees. "
                    "All students have cleared their fee obligations.\n\n"
                    "Total outstanding balance: **₵0.00**"
                )

            return {
                "answer": answer,
                "data": {
                    "total_owing": 0,
                    "total_outstanding": "0.00",
                },
                **self._meta("database"),
            }

        lines = [
            "## School Fees - Students Owing",
            "",
            (
                f"**{total_owing:,} student"
                f"{'s' if total_owing != 1 else ''}** "
                "have outstanding fees."
            ),
            "",
            (
                f"Total outstanding balance: "
                f"**₵{total_outstanding:,.2f}**"
            ),
            "",
        ]

        display_limit = 20

        for index, item in enumerate(
            owing_students[:display_limit],
            start=1,
        ):
            student = item["student"]

            name = (
                student.user.get_full_name().strip()
                or student.user.username
            )

            balance = item["balance"]
            invoice_count = len(
                item["invoices"]
            )

            lines.append(
                f"{index}. **{name}** — "
                f"₵{balance:,.2f} "
                f"(over {invoice_count} "
                f"invoice{'s' if invoice_count != 1 else ''})"
            )

        if total_owing > display_limit:
            lines.append(
                f"\n*...and "
                f"{total_owing - display_limit} more students.*"
            )

        lines.append(
            "\n---\n"
            "*For detailed fee information, please visit "
            "the Finance module.*"
        )

        return {
            "answer": "\n".join(lines),
            "data": {
                "total_owing": total_owing,
                "total_outstanding": float(
                    total_outstanding
                ),
                "students": [
                    {
                        "name": (
                            item["student"]
                            .user
                            .get_full_name()
                            .strip()
                            or item["student"].user.username
                        ),
                        "balance": float(
                            item["balance"]
                        ),
                        "invoice_count": len(
                            item["invoices"]
                        ),
                    }
                    for item in owing_students[
                        :display_limit
                    ]
                ],
            },
            **self._meta("database"),
        }

    def _answer_total_fee_balance(self, question):
        """Calculate fee totals from invoice line items and confirmed payments."""
        if not self._has_finance_access():
            return {
                "answer": "You do not have permission to access financial information. Please contact the school administration.",
                **self._meta("permission_denied"),
            }

        invoice_qs = self._get_invoice_queryset()
        if invoice_qs is None:
            return {
                "answer": "The finance module is currently unavailable. Please try again later.",
                **self._meta("error"),
            }

        total_billed = Decimal("0.00")
        total_collected = Decimal("0.00")
        total_outstanding = Decimal("0.00")
        students_with_balance = set()
        invoice_count = 0

        for invoice in invoice_qs.exclude(status="VOID").prefetch_related("line_items", "payments"):
            invoice_count += 1
            billed = invoice.line_items.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
            collected = invoice.payments.filter(status="CONFIRMED").aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
            balance = max(billed - collected, Decimal("0.00"))
            total_billed += billed
            total_collected += collected
            total_outstanding += balance
            if balance > 0:
                students_with_balance.add(invoice.student_id)

        collection_rate = (float(total_collected) / float(total_billed) * 100) if total_billed > 0 else 0.0
        response = (
            "## Total Fee Balance Summary\n\n"
            "### Current Outstanding\n"
            f"- **Total Outstanding Balance:** ₵{total_outstanding:,.2f}\n"
            f"- **Students with Balance:** {len(students_with_balance):,}\n\n"
            "### Overall Financial Status\n"
            f"- **Total Billed:** ₵{total_billed:,.2f}\n"
            f"- **Total Collected:** ₵{total_collected:,.2f}\n"
            f"- **Collection Rate:** {collection_rate:.1f}%\n"
            f"- **Invoices Analysed:** {invoice_count:,}"
        )
        return {
            "answer": response,
            "data": {
                "total_outstanding": float(total_outstanding),
                "students_owing": len(students_with_balance),
                "total_billed": float(total_billed),
                "total_collected": float(total_collected),
                "collection_rate": round(collection_rate, 1),
                "invoice_count": invoice_count,
            },
            **self._meta("database"),
        }

    # ==================================================================
    # STAFF LEAVE DETECTION
    # ==================================================================

    def _is_current_staff_leave_question(self, q):
        """
        Detect questions asking which staff members are currently
        on leave.

        Examples:

            Which staff members are currently on leave?
            Which staff are currently on leave?
            Who is currently on leave?
            Who is on leave today?
            Which teachers are on leave?
            Are any staff on leave?
            How many staff are currently on leave?
            List staff on leave.
        """

        staff_terms = (
            "staff",
            "staff member",
            "staff members",
            "employee",
            "employees",
            "teacher",
            "teachers",
            "teaching staff",
        )

        leave_terms = (
            "on leave",
            "currently on leave",
            "on annual leave",
            "on sick leave",
            "on maternity leave",
            "on paternity leave",
            "on study leave",
            "on casual leave",
            "on compassionate leave",
            "on unpaid leave",
            "on leave today",
        )

        direct_phrases = (
            "who is currently on leave",
            "who is on leave",
            "which staff are on leave",
            "which staff members are on leave",
            "which staff are currently on leave",
            "which staff members are currently on leave",
            "which employees are on leave",
            "which employees are currently on leave",
            "which teachers are on leave",
            "which teachers are currently on leave",
            "staff currently on leave",
            "staff members currently on leave",
            "staff on leave today",
            "staff members on leave today",
            "teachers on leave today",
            "are any staff on leave",
            "are any staff members on leave",
            "how many staff are on leave",
            "how many staff members are on leave",
            "how many teachers are on leave",
            "list staff on leave",
            "list staff members on leave",
            "show staff on leave",
            "show staff members on leave",
        )

        if any(
            phrase in q
            for phrase in direct_phrases
        ):
            return True

        has_staff = any(
            term in q
            for term in staff_terms
        )

        has_leave = any(
            term in q
            for term in leave_terms
        )

        return has_staff and has_leave

    # ==================================================================
    # STAFF LEAVE ANSWER
    # ==================================================================

    def _answer_current_staff_leave(self, question):
        """
        Return staff who have an active approved/taken leave request
        covering today's date.

        SOURCE OF TRUTH:

            staff.LeaveRequest

        NOT:

            staff.StaffGrade

        Current leave is determined by:

            status IN (APPROVED, TAKEN)
            start_date <= today
            end_date >= today
        """

        if not self._has_staff_leave_access():
            return {
                "answer": (
                    "You do not have permission to access "
                    "staff leave information."
                ),
                **self._meta("permission_denied"),
            }

        leave_qs = self._get_leave_request_queryset()

        if leave_qs is None:
            return {
                "answer": (
                    "The staff leave module is currently unavailable. "
                    "Please try again later."
                ),
                **self._meta("error"),
            }

        today = timezone.localdate()

        active_leave = (
            leave_qs
            .filter(
                status__in=[
                    "APPROVED",
                    "TAKEN",
                ],
                start_date__lte=today,
                end_date__gte=today,
                staff__is_active=True,
            )
            .order_by(
                "staff__user__last_name",
                "staff__user__first_name",
                "start_date",
            )
        )

        # --------------------------------------------------------------
        # Avoid duplicate staff members.
        #
        # A staff member may theoretically have overlapping records.
        # The answer should list the staff member once.
        # --------------------------------------------------------------

        staff_records = {}

        for leave in active_leave:
            staff = leave.staff

            if not staff:
                continue

            staff_id = str(
                staff.pk
            )

            if staff_id not in staff_records:
                staff_records[staff_id] = {
                    "staff": staff,
                    "leave_requests": [],
                }

            staff_records[
                staff_id
            ]["leave_requests"].append(
                leave
            )

        records = list(
            staff_records.values()
        )

        q = self._norm(question)

        count_only = (
            "how many" in q
            or "count" in q
            or "number of" in q
        )

        if not records:

            if count_only:
                answer = (
                    "## Staff Leave Status\n\n"
                    f"There are **0 staff members** currently "
                    f"on approved/taken leave as of "
                    f"**{today:%d %B %Y}**."
                )
            else:
                answer = (
                    "## Staff Leave Status\n\n"
                    f"There are currently **no staff members** "
                    f"with an approved or taken leave covering "
                    f"**{today:%d %B %Y}**."
                )

            return {
                "answer": answer,
                "data": {
                    "date": today.isoformat(),
                    "staff_on_leave": 0,
                    "records": [],
                },
                **self._meta("database"),
            }

        # --------------------------------------------------------------
        # Build human-readable response.
        # --------------------------------------------------------------

        lines = [
            "## Staff Currently on Leave",
            "",
            (
                f"**{len(records):,} staff member"
                f"{'s' if len(records) != 1 else ''}** "
                f"currently have approved/taken leave covering "
                f"**{today:%d %B %Y}**.",
            ),
            "",
        ]

        display_limit = 50

        output_records = []

        for index, record in enumerate(
            records[:display_limit],
            start=1,
        ):
            staff = record["staff"]
            leave_requests = record[
                "leave_requests"
            ]

            try:
                name = (
                    staff.user
                    .get_full_name()
                    .strip()
                )
            except Exception:
                name = ""

            if not name:
                name = (
                    getattr(
                        staff.user,
                        "username",
                        "",
                    )
                    or "Unnamed staff member"
                )

            position = (
                getattr(
                    staff,
                    "get_staff_position_display",
                    lambda: staff.staff_position,
                )()
                or "Staff"
            )

            department = (
                getattr(
                    getattr(
                        staff,
                        "department",
                        None,
                    ),
                    "name",
                    None,
                )
                or "No department"
            )

            # There may be more than one active request.
            # Show each leave type cleanly.
            leave_descriptions = []

            for leave in leave_requests:
                leave_type = getattr(
                    getattr(
                        leave,
                        "leave_type",
                        None,
                    ),
                    "name",
                    None,
                ) or "Leave"

                leave_descriptions.append(
                    f"{leave_type} "
                    f"({leave.start_date:%d %b %Y} – "
                    f"{leave.end_date:%d %b %Y})"
                )

            leave_text = "; ".join(
                leave_descriptions
            )

            lines.append(
                f"{index}. **{name}**\n"
                f"   - Position: {position}\n"
                f"   - Department: {department}\n"
                f"   - Leave: {leave_text}"
            )

            output_records.append(
                {
                    "name": name,
                    "staff_id": getattr(
                        staff,
                        "staff_id",
                        None,
                    ),
                    "position": position,
                    "department": department,
                    "leave": [
                        {
                            "type": getattr(
                                getattr(
                                    leave,
                                    "leave_type",
                                    None,
                                ),
                                "name",
                                "Leave",
                            ),
                            "start_date": (
                                leave.start_date.isoformat()
                            ),
                            "end_date": (
                                leave.end_date.isoformat()
                            ),
                            "status": leave.status,
                        }
                        for leave in leave_requests
                    ],
                }
            )

        if len(records) > display_limit:
            lines.append(
                "",
            )
            lines.append(
                f"*Showing the first {display_limit} "
                f"of {len(records):,} staff members.*"
            )

        lines.append(
            "",
        )
        lines.append(
            f"**Date checked:** "
            f"{today:%d %B %Y}"
        )

        return {
            "answer": "\n".join(lines),
            "data": {
                "date": today.isoformat(),
                "staff_on_leave": len(records),
                "records": output_records,
            },
            **self._meta("database"),
        }

    # ==================================================================
    # ATTENDANCE DETECTION
    # ==================================================================

    def _is_today_attendance(self, q):
        phrases = (
            "attendance recorded today",
            "attendance records today",
            "students attendance today",
            "student attendance today",
            "attendance today",
            "how many students attended today",
            "how many students have attendance today",
            "how many students had attendance today",
            "how many attendance records today",
            "attendance for today",
            "today's attendance",
            "today attendance",
            "attendance count today",
            "number of attendance today",
            "how many attendance today",
            "how many students are present today",
            "how many students are absent today",
            "attendance marked today",
            "students with attendance today",
            "attendance taken today",
            "attendance logged today",
            "today attendance records",
            "today student attendance",
            "students present today",
            "students absent today",
            "today attendance count",
        )

        return any(
            phrase in q
            for phrase in phrases
        )

    def _is_today_attendance_names(self, q):
        has_attendance = (
            "attendance" in q
        )

        has_today = (
            "today" in q
            or "today's" in q
        )

        has_names = any(
            term in q
            for term in (
                "who",
                "names",
                "name",
                "list",
                "which students",
            )
        )

        return (
            has_attendance
            and has_today
            and has_names
        )

    def _is_attendance_breakdown(self, q):
        return (
            "attendance" in q
            and "today" in q
            and any(
                term in q
                for term in (
                    "present",
                    "absent",
                    "late",
                    "breakdown",
                    "status",
                    "how many present",
                    "how many absent",
                )
            )
        )

    def _is_active_student_count(self, q):
        # NOTE: this used to require the literal word "active" right
        # before "student"/"students" (e.g. only "how many active
        # students"), which meant the single most natural way anyone
        # would actually ask this - "how many students do we have?",
        # "total students", "number of students" - fell straight
        # through this deterministic, guaranteed-accurate database
        # check and went to the LLM instead, which has no real access
        # to the database and could only guess. Broadened to match
        # "student(s)" with or without "active" in front of it.
        return (
            (
                "student" in q
                or "students" in q
            )
            and any(
                term in q
                for term in (
                    "how many",
                    "count",
                    "number",
                    "total",
                )
            )
        )

    def _is_active_student_names(self, q):
        return (
            (
                "student" in q
                or "students" in q
            )
            and any(
                term in q
                for term in (
                    "who",
                    "name",
                    "names",
                    "list",
                    "show",
                    "which",
                )
            )
        )

    def _is_present_absent_breakdown(self, q):
        return (
            "attendance" in q
            and any(
                term in q
                for term in (
                    "present",
                    "absent",
                )
            )
            and "today" in q
        )

    # ==================================================================
    # ATTENDANCE RATE
    # ==================================================================

    def _is_attendance_rate_question(self, q):
        phrases = (
            "attendance rate",
            "attendance percentage",
            "overall attendance",
            "student attendance rate",
            "attendance stats",
            "attendance statistics",
            "attendance summary",
            "school attendance rate",
            "current attendance rate",
            "attendance for the term",
            "attendance for this term",
            "attendance for the year",
            "attendance for this year",
            "attendance so far",
            "attendance overview",
            "attendance performance",
            "what is the attendance rate",
            "attendance trend",
            "attendance figures",
            "attendance metrics",
        )

        return any(
            phrase in q
            for phrase in phrases
        )

    # ==================================================================
    # ATTENDANCE ANSWERS
    # ==================================================================

    def _answer_today_attendance(self, question):
        today = timezone.localdate()

        queryset = (
            self._attendance_queryset()
            .filter(
                date=today,
                student__isnull=False,
            )
        )

        unique_student_count = (
            queryset
            .values_list(
                "student_id",
                flat=True,
            )
            .distinct()
            .count()
        )

        total_records = queryset.count()

        if unique_student_count == 0:
            answer = (
                "## Today's Student Attendance\n\n"
                f"**No students** have attendance recorded "
                f"for **{today:%d %B %Y}**."
            )

            return {
                "answer": answer,
                "data": {
                    "date": today.isoformat(),
                    "students_with_attendance": 0,
                    "attendance_records": 0,
                },
                **self._meta("database"),
            }

        answer = (
            "## Today's Student Attendance\n\n"
            f"**{unique_student_count:,} student"
            f"{'s' if unique_student_count != 1 else ''}** "
            f"have attendance recorded for "
            f"**{today:%d %B %Y}**.\n\n"
            f"There are **{total_records:,} attendance "
            f"record{'s' if total_records != 1 else ''}** total."
        )

        return {
            "answer": answer,
            "data": {
                "date": today.isoformat(),
                "students_with_attendance": unique_student_count,
                "attendance_records": total_records,
            },
            **self._meta("database"),
        }

    def _answer_today_attendance_names(self):
        today = timezone.localdate()

        queryset = (
            self._attendance_queryset()
            .filter(
                date=today,
                student__isnull=False,
            )
            .select_related(
                "student__user",
            )
            .values(
                "student_id",
                "student__user__first_name",
                "student__user__last_name",
                "status",
            )
            .order_by(
                "student__user__last_name",
                "student__user__first_name",
            )
        )

        seen = set()
        lines = []

        for row in queryset:
            student_id = row[
                "student_id"
            ]

            if student_id in seen:
                continue

            seen.add(
                student_id
            )

            name = (
                f"{row['student__user__first_name']} "
                f"{row['student__user__last_name']}"
            ).strip()

            lines.append(
                f"{len(lines) + 1}. "
                f"**{name or 'Unnamed student'}** "
                f"— {row['status']}"
            )

        if not lines:
            answer = (
                f"No student attendance records were "
                f"found for today "
                f"({today:%d %B %Y})."
            )
        else:
            answer = (
                f"There are **{len(lines):,} students** "
                f"with attendance recorded today "
                f"({today:%d %B %Y}).\n\n"
                + "\n".join(lines)
            )

        return {
            "answer": answer,
            **self._meta("database"),
        }

    def _answer_attendance_breakdown(self):
        today = timezone.localdate()

        queryset = (
            self._attendance_queryset()
            .filter(
                date=today,
                student__isnull=False,
            )
        )

        statuses = (
            "PRESENT",
            "ABSENT",
            "LATE",
            "EXCUSED",
            "HOLIDAY",
        )

        breakdown = {}

        for status in statuses:
            count = queryset.filter(
                status=status
            ).count()

            if count > 0:
                breakdown[
                    status
                ] = count

        unique_students = (
            queryset
            .values(
                "student_id"
            )
            .distinct()
            .count()
        )

        lines = [
            (
                f"## Today's Attendance Breakdown "
                f"— {today:%d %B %Y}"
            ),
            "",
            (
                f"**{unique_students:,} students** "
                "have attendance recorded."
            ),
            "",
        ]

        if breakdown:
            for status, count in sorted(
                breakdown.items(),
                key=lambda item: item[1],
                reverse=True,
            ):
                lines.append(
                    f"- **{status.replace('_', ' ').title()}**: "
                    f"{count:,}"
                )
        else:
            lines.append(
                "No attendance records found for today."
            )

        return {
            "answer": "\n".join(lines),
            **self._meta("database"),
        }

    def _answer_present_absent_breakdown(self):
        today = timezone.localdate()

        queryset = (
            self._attendance_queryset()
            .filter(
                date=today,
                student__isnull=False,
            )
        )

        present_count = queryset.filter(
            status="PRESENT"
        ).count()

        absent_count = queryset.filter(
            status="ABSENT"
        ).count()

        late_count = queryset.filter(
            status="LATE"
        ).count()

        total_records = queryset.count()

        unique_students = (
            queryset
            .values(
                "student_id"
            )
            .distinct()
            .count()
        )

        answer = (
            f"## Today's Attendance — "
            f"{today:%d %B %Y}\n\n"
            f"**{unique_students:,} students** "
            "have attendance recorded.\n\n"
            f"- **Present**: {present_count:,}\n"
            f"- **Absent**: {absent_count:,}\n"
            f"- **Late**: {late_count:,}\n"
            f"- **Total Records**: {total_records:,}"
        )

        return {
            "answer": answer,
            **self._meta("database"),
        }

    # ==================================================================
    # ATTENDANCE RATE ANSWER
    # ==================================================================

    def _answer_attendance_rate(self, question):
        today = timezone.localdate()

        q = self._norm(question)

        lookback_days = 30

        if (
            "term" in q
            or "this term" in q
        ):
            lookback_days = 90

        elif (
            "year" in q
            or "this year" in q
            or "academic year" in q
        ):
            lookback_days = 365

        elif (
            "week" in q
            or "this week" in q
        ):
            lookback_days = 7

        start_date = (
            today
            - timedelta(
                days=lookback_days
            )
        )

        queryset = (
            self._attendance_queryset()
            .filter(
                date__gte=start_date,
                date__lte=today,
                student__isnull=False,
            )
        )

        total_records = queryset.count()

        total_students = self._students().count()

        if total_records == 0:
            return {
                "answer": (
                    "## Attendance Rate\n\n"
                    f"No attendance records were found "
                    f"for the last {lookback_days} days.\n\n"
                    f"**{total_students:,} active students** "
                    "are currently within your authorized scope."
                ),
                "data": {
                    "period_days": lookback_days,
                    "total_records": 0,
                    "total_students": total_students,
                },
                **self._meta("database"),
            }

        present_count = queryset.filter(
            status="PRESENT"
        ).count()

        absent_count = queryset.filter(
            status="ABSENT"
        ).count()

        late_count = queryset.filter(
            status="LATE"
        ).count()

        excused_count = queryset.filter(
            status="EXCUSED"
        ).count()

        holiday_count = queryset.filter(
            status="HOLIDAY"
        ).count()

        attended = (
            present_count
            + late_count
        )

        attendance_rate = round(
            (
                attended
                / total_records
                * 100
            ),
            1,
        )

        unique_students = (
            queryset
            .values(
                "student_id"
            )
            .distinct()
            .count()
        )

        period_label = (
            f"Last {lookback_days} days"
        )

        if lookback_days == 7:
            period_label = "This week"

        elif lookback_days == 90:
            period_label = "This term"

        elif lookback_days == 365:
            period_label = "This year"

        response = (
            "## Student Attendance Rate Summary\n\n"
            f"### Overall Statistics ({period_label})\n"
            f"- **Attendance Rate**: **{attendance_rate}%**\n"
            f"- **Total Records**: {total_records:,}\n"
            f"- **Unique Students**: {unique_students:,} "
            f"(out of {total_students:,} active students)\n"
            f"- **Period**: {start_date:%d %b %Y} "
            f"to {today:%d %b %Y}\n\n"
            "### Breakdown\n"
            f"- **Present**: {present_count:,} "
            f"({round(present_count / total_records * 100, 1)}%)\n"
            f"- **Late**: {late_count:,} "
            f"({round(late_count / total_records * 100, 1)}%)\n"
            f"- **Absent**: {absent_count:,} "
            f"({round(absent_count / total_records * 100, 1)}%)\n"
            f"- **Excused**: {excused_count:,} "
            f"({round(excused_count / total_records * 100, 1)}%)\n"
        )

        if holiday_count:
            response += (
                f"- **Holiday/No School**: "
                f"{holiday_count:,} "
                f"({round(holiday_count / total_records * 100, 1)}%)\n"
            )

        if attendance_rate >= 90:
            status = (
                "✅ **Excellent** - Attendance is strong"
            )

        elif attendance_rate >= 80:
            status = (
                "⚠️ **Good** - Attendance is acceptable "
                "but could improve"
            )

        elif attendance_rate >= 70:
            status = (
                "⚠️ **Needs Attention** - Attendance is below target"
            )

        else:
            status = (
                "🔴 **Critical** - Attendance requires immediate intervention"
            )

        response += (
            "\n### Status\n"
            f"{status}"
        )

        return {
            "answer": response,
            "data": {
                "period_days": lookback_days,
                "attendance_rate": attendance_rate,
                "total_records": total_records,
                "unique_students": unique_students,
                "total_students": total_students,
                "present_count": present_count,
                "absent_count": absent_count,
                "late_count": late_count,
                "excused_count": excused_count,
                "start_date": start_date.isoformat(),
                "end_date": today.isoformat(),
            },
            **self._meta("database"),
        }

    # ==================================================================
    # MAIN ANSWER
    # ==================================================================

    def answer(self, question):
        """
        Main deterministic database query entry point.

        IMPORTANT:

        Ordering matters.

        More specific queries are checked before broader queries.
        """

        q = self._norm(question)

        if not q:
            return None

        # ==============================================================
        # 1. STAFF LEAVE
        #
        # This MUST be checked before the question reaches Groq.
        # ==============================================================

        if self._is_current_staff_leave_question(q):
            return self._answer_current_staff_leave(
                question
            )

        # ==============================================================
        # 2. FEES
        # ==============================================================

        if "fee" in q or "fees" in q or "balance" in q or "owing" in q or "invoice" in q:
            named_fee_result = self._answer_named_student_fee(question)
            if named_fee_result is not None:
                return named_fee_result

        if self._is_owing_fees_question(q):
            return self._answer_owing_fees(
                question
            )

        if self._is_fee_balance_question(q):
            return self._answer_total_fee_balance(
                question
            )

        # ==============================================================
        # 3. SPECIFIC TODAY ATTENDANCE QUESTIONS
        #
        # Names must be checked before the generic attendance summary.
        # ==============================================================

        if self._is_today_attendance_names(q):
            return self._answer_today_attendance_names()

        if self._is_attendance_breakdown(q):
            return self._answer_attendance_breakdown()

        if self._is_present_absent_breakdown(q):
            return self._answer_present_absent_breakdown()

        if self._is_today_attendance(q):
            return self._answer_today_attendance(
                question
            )

        # ==============================================================
        # 4. ATTENDANCE RATE
        # ==============================================================

        if self._is_attendance_rate_question(q):
            return self._answer_attendance_rate(
                question
            )

        # ==============================================================
        # 5. STUDENTS
        # ==============================================================

        students = self._students()

        if self._is_active_student_count(q):

            count = students.count()

            word = (
                "student"
                if count == 1
                else "students"
            )

            return {
                "answer": (
                    f"There "
                    f"{'is' if count == 1 else 'are'} "
                    f"**{count:,} active {word}** "
                    "within your authorized school scope."
                ),
                **self._meta("database"),
            }

        if self._is_active_student_names(q):

            rows = list(
                students
                .select_related(
                    "user",
                    "school_class",
                    "grade_level",
                )
                .order_by(
                    "user__last_name",
                    "user__first_name",
                )
            )

            if not rows:
                text = (
                    "There are currently **no active students** "
                    "within your authorized school scope."
                )

            else:
                lines = [
                    (
                        f"There are **{len(rows):,} active students** "
                        "within your authorized school scope:\n"
                    )
                ]

                for index, student in enumerate(
                    rows,
                    start=1,
                ):
                    name = (
                        student.user
                        .get_full_name()
                        .strip()
                        or student.user.username
                    )

                    school_class = (
                        getattr(
                            getattr(
                                student,
                                "school_class",
                                None,
                            ),
                            "name",
                            None,
                        )
                        or "Not assigned"
                    )

                    lines.append(
                        f"{index}. **{name}** — "
                        f"{school_class}"
                    )

                text = "\n".join(
                    lines
                )

            return {
                "answer": text,
                **self._meta("database"),
            }

        # ==============================================================
        # 6. NO DETERMINISTIC MATCH
        #
        # Return None so SchoolCopilotEngine can handle generative
        # questions.
        # ==============================================================

        return None


# ======================================================================
# PUBLIC UTILITY
# ======================================================================

def get_direct_answer(
    user,
    school,
    question,
    allowed_students=None,
):
    """
    Convenience wrapper for deterministic school data queries.
    """

    engine = SchoolDataQueryEngine(
        user=user,
        school=school,
        allowed_students=allowed_students,
    )

    return engine.answer(
        question
    )