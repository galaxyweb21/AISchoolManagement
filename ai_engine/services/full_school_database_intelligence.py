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
    # Student academic ranking / overall performance
    # ------------------------------------------------------------------
    def student_merit_ranking(self, q):
        """Answer ranking questions from completed, school-scoped terminal results.

        This handler intentionally runs before the generic student list handler.
        Ranking is available for ordinary performance questions, not only awards.
        """
        student_words = ("student", "students", "learner", "learners", "pupil", "pupils")
        ranking_words = (
            "best", "top", "highest", "overall", "rank", "ranking", "performing",
            "performance", "performer", "performers", "average", "averages", "highest marks", "highest scores",
            "academic excellence", "award", "awards", "scholarship", "scholarships",
            "promotion", "promotions", "excellent student", "excellent students",
        )
        # Students are sometimes referred to as "top performers" without the
        # noun student/pupil. Recognize those phrasings, but keep the trigger
        # narrow so unrelated questions do not enter the ranking query.
        ranking_subject_phrases = (
            "top performer", "best performer", "highest performer",
            "top performing", "best performing", "highest scoring student",
            "highest scoring students", "who has the highest average",
            "who has the best average", "overall best student",
        )
        has_student_subject = any(w in q for w in student_words) or any(
            phrase in q for phrase in ranking_subject_phrases
        )
        if not has_student_subject or not any(w in q for w in ranking_words):
            return None
        if not self.can("academics") or not self.can("students"):
            return self.denied("student academic performance information")

        try:
            from assessments.models import TerminalResult
            from school.models import AcademicTerm
            from django.db.models import Avg, Count, Q

            # Parse an explicit result count: top 5, best five, top ten, etc.
            number_words = {
                "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                "eleven": 11, "twelve": 12, "twenty": 20,
            }
            limit = None
            count_match = re.search(r"\b(?:top|best|highest|rank(?:ed|ing)?|first)\s+(\d{1,2})\b", q)
            if count_match:
                limit = max(1, min(50, int(count_match.group(1))))
            else:
                for word, number in number_words.items():
                    if re.search(r"\b(?:top|best|highest|rank(?:ed|ing)?|first)\s+" + word + r"\b", q):
                        limit = number
                        break
            if limit is None:
                plural_ranking = any(x in q for x in (
                    "top students", "best students", "rank students", "ranking",
                    "top performers", "best performers", "highest performers",
                    "top performing students", "best performing students",
                ))
                limit = 10 if plural_ranking else 1

            # Establish a real, data-bearing term. Use active term only when
            # requested; otherwise use the most recent term with COMPLETE results.
            base = TerminalResult.objects.filter(
                school=self.school,
                student__school=self.school,
                student__is_active=True,
                status="COMPLETE",
                final_score__isnull=False,
            )
            if self.allowed_students is not None:
                # Fail closed if the caller's authorized-student scope cannot be
                # applied. Never broaden a restricted user's query to all students.
                try:
                    base = base.filter(student__in=self.allowed_students.values("pk"))
                except Exception:
                    logger.exception("Could not apply authorized student scope to ranking")
                    return {
                        "answer": "I couldn't verify your authorized student scope, so I stopped the ranking rather than risk showing results for students outside your access.",
                        **self.meta("scope_verification_failed"),
                    }

            term = None
            asks_current = any(x in q for x in ("current term", "this term", "active term", "current academic term"))
            if asks_current:
                term = AcademicTerm.objects.filter(
                    academic_year__school=self.school,
                    is_active=True,
                ).select_related("academic_year").order_by("-start_date").first()
            if term is None:
                # Do not trust result default ordering for recency; choose the latest
                # term among terms that have complete, scored records.
                term_ids = base.order_by().values_list("academic_term_id", flat=True).distinct()
                term = AcademicTerm.objects.filter(
                    pk__in=term_ids,
                    academic_year__school=self.school,
                ).select_related("academic_year").order_by("-end_date", "-start_date").first()
            if term is None:
                return {
                    "answer": "I can't determine the overall best student yet because the database has no completed terminal results with final scores. Complete and publish the students' results first.",
                    "data": {"count": 0, "basis": "COMPLETE terminal results with final_score"},
                    **self.meta("database_unavailable"),
                }

            qs = base.filter(academic_term=term)
            # Apply an explicit class scope. The previous parser required the
            # words "students in" immediately together and could miss natural
            # phrasing such as "Who are the best students in Basic 5?". Parse
            # common school stage + number patterns independently of the word
            # "students", then apply the filter to result class, student class,
            # and grade level. Never silently fall back to a school-wide ranking
            # when the question names a class.
            class_name = None
            class_match = re.search(
                r"\b(?:in|from|of)\s+(?:the\s+)?(?:class\s+)?"
                r"((?:basic|primary|nursery|kindergarten|kg|jhs|shs)\s*[- ]?\s*\d+[a-z]?)\b",
                q,
                re.IGNORECASE,
            )
            if class_match:
                class_name = re.sub(r"\s+", " ", class_match.group(1)).strip()
            else:
                # Support named classes such as "in Class A" without
                # interpreting generic phrases like "in the school" as a class.
                named_class = re.search(
                    r"\b(?:students?|learners?|pupils?)\b.*?\b(?:in|from|of)\s+"
                    r"(?:the\s+)?(class\s+[a-z][a-z0-9 -]{0,20}?)(?:\?|$|\s+based on\b|\s+with\b)",
                    q,
                    re.IGNORECASE,
                )
                if named_class:
                    class_name = re.sub(r"^class\s+", "", named_class.group(1), flags=re.IGNORECASE).strip()

            if class_name and class_name.lower() not in {"the school", "school", "all classes"}:
                # Scope by the student's CURRENT class/grade, not merely the
                # class stored on an older TerminalResult row. A student may
                # have been promoted/transferred after those results were saved;
                # filtering on result.school_class alone can therefore leak
                # students currently in another class into this ranking.
                class_filter = (
                    Q(student__school_class__name__iexact=class_name)
                    | Q(student__grade_level__name__iexact=class_name)
                )
                qs = qs.filter(class_filter)

            # Optional fair-comparison mode: compare every student on the same
            # subjects only when the user explicitly requests a like-for-like
            # comparison. Ordinary rankings continue to use each student's
            # available completed subject scores and disclose the basis.
            comparable_subject_mode = any(phrase in q for phrase in (
                "same subjects", "same subject", "common subjects", "common subject",
                "compare fairly", "fair comparison", "fairly compare", "like for like",
                "like-for-like", "equal subjects", "equal subject basis",
            ))
            comparison_subjects = []
            if comparable_subject_mode:
                raw_rows = list(qs.values(
                    "student_id", "student__user__first_name", "student__user__last_name",
                    "student__user__username", "student__school_class__name",
                    "student__grade_level__name", "subject", "final_score",
                ).order_by("student_id", "subject"))
                grouped = {}
                for item in raw_rows:
                    sid = item["student_id"]
                    bucket = grouped.setdefault(sid, {
                        "student_id": sid,
                        "student__user__first_name": item.get("student__user__first_name", ""),
                        "student__user__last_name": item.get("student__user__last_name", ""),
                        "student__user__username": item.get("student__user__username", ""),
                        "student__school_class__name": item.get("student__school_class__name"),
                        "student__grade_level__name": item.get("student__grade_level__name"),
                        "subject_scores": {},
                    })
                    subject = str(item.get("subject") or "").strip()
                    if subject and item.get("final_score") is not None:
                        bucket["subject_scores"][subject.casefold()] = (subject, float(item["final_score"]))
                subject_sets = [set(bucket["subject_scores"]) for bucket in grouped.values() if bucket["subject_scores"]]
                common_subject_keys = set.intersection(*subject_sets) if subject_sets else set()
                if not common_subject_keys:
                    return {
                        "answer": f"I couldn't produce a like-for-like ranking for **{term.name}** because the eligible students do not share any common completed subjects. Ask for the normal overall ranking, or check that the same subjects have completed results for this class and term.",
                        "data": {"count": 0, "term": term.name, "comparable_subjects": []},
                        **self.meta("comparable_subjects_unavailable"),
                    }
                comparison_subjects = sorted(
                    next(bucket["subject_scores"][key][0] for bucket in grouped.values() if key in bucket["subject_scores"])
                    for key in common_subject_keys
                )
                rows = []
                for bucket in grouped.values():
                    scores = [bucket["subject_scores"][key][1] for key in common_subject_keys]
                    if not scores:
                        continue
                    rows.append({
                        "student_id": bucket["student_id"],
                        "student__user__first_name": bucket["student__user__first_name"],
                        "student__user__last_name": bucket["student__user__last_name"],
                        "student__user__username": bucket["student__user__username"],
                        "student__school_class__name": bucket["student__school_class__name"],
                        "student__grade_level__name": bucket["student__grade_level__name"],
                        "average": sum(scores) / len(scores),
                        "subject_count": len(scores),
                        "scores_80_plus": sum(1 for score in scores if score >= 80),
                        "scores_below_50": sum(1 for score in scores if score < 50),
                    })
                rows.sort(key=lambda row: (
                    -round(float(row["average"] or 0), 2),
                    str(row.get("student__user__last_name") or "").casefold(),
                    str(row.get("student__user__first_name") or "").casefold(),
                ))
                rows = rows[:limit]
                ranking_basis_label = "average final score across the same completed subjects for every listed student"
            else:
                rows = list(qs.values(
                    "student_id", "student__user__first_name", "student__user__last_name",
                    "student__user__username", "student__school_class__name",
                    "student__grade_level__name",
                ).annotate(
                    average=Avg("final_score"),
                    subject_count=Count("subject", distinct=True),
                    scores_80_plus=Count("id", filter=Q(final_score__gte=80)),
                    scores_below_50=Count("id", filter=Q(final_score__lt=50)),
                ).filter(subject_count__gte=1).order_by(
                    "-average", "-subject_count", "student__user__last_name", "student__user__first_name"
                )[:limit])
                ranking_basis_label = "average of each student's COMPLETE subject final scores; only subjects with a recorded final score are included"

            # If no students match an explicitly named class, say that rather
            # than falling through to a generic list of all students.
            if not rows:
                return {
                    "answer": f"I found no eligible completed results for the requested scope in **{term.name}**. Check the class name and whether results have status COMPLETE.",
                    "data": {"count": 0, "term": term.name, "requested_limit": limit},
                    **self.meta("database_unavailable"),
                }

            records = []
            previous_average = None
            competition_rank = 0
            for i, row in enumerate(rows, 1):
                name = (row.get("student__user__first_name", "") + " " + row.get("student__user__last_name", "")).strip()
                name = name or row.get("student__user__username") or "Unnamed student"
                cls = row.get("student__school_class__name") or row.get("student__grade_level__name") or "Class not assigned"
                average_score = round(float(row["average"] or 0), 2)
                # Equal displayed averages receive equal competition ranks
                # (1, 1, 3), rather than arbitrary different ranks based on
                # subject coverage or alphabetical ordering.
                if previous_average is None or average_score != previous_average:
                    competition_rank = i
                records.append({
                    "rank": competition_rank, "name": name, "class": cls,
                    "average_score": average_score,
                    "subjects_counted": int(row["subject_count"] or 0),
                    "scores_80_or_above": int(row["scores_80_plus"] or 0),
                    "scores_below_50": int(row["scores_below_50"] or 0),
                })
                previous_average = average_score

            question_kind = "overall academic performance"
            if any(x in q for x in ("award", "awards", "scholarship", "scholarships")):
                question_kind = "academic award/scholarship consideration"
            elif "promotion" in q or "promotions" in q:
                question_kind = "promotion review"
            title = "Overall Student Academic Ranking"
            if question_kind == "academic award/scholarship consideration":
                title = "Academic Merit Shortlist"
            elif question_kind == "promotion review":
                title = "Academic Results for Promotion Review"

            lines = [
                f"## {title}", "",
                f"**Scope:** {question_kind} | **Term:** {term.name} ({getattr(getattr(term, 'academic_year', None), 'name', 'academic year not recorded')})",
                f"**Ranking basis:** {ranking_basis_label}.",
                f"**Results shown:** {len(records)} (requested: {limit}). Equal averages share the same rank; alphabetical order is used only to display tied students consistently.", "",
            ]
            for r in records:
                lines.append(
                    f"{r['rank']}. **{r['name']}** — {r['class']} — **{r['average_score']:.2f}% average** "
                    f"across {r['subjects_counted']} subject(s); {r['scores_80_or_above']} score(s) ≥80 and "
                    f"{r['scores_below_50']} score(s) below 50."
                )
            lines += [
                "",
                ("**Subjects compared:** " + ", ".join(comparison_subjects) + ".") if comparable_subject_mode else "",
                "**Interpretation:** This ranking uses completed academic results for the selected term. It is not a full measure of a student's character, attendance, financial need, or scholarship eligibility. For high-stakes decisions, confirm the school's written criteria and review result completeness.",
            ]
            return {
                "answer": "\n".join(line for line in lines if line != ""),
                "data": {"term": term.name, "academic_year": getattr(getattr(term, "academic_year", None), "name", None), "requested_limit": limit, "count": len(records), "ranking_basis": ("mean common-subject COMPLETE TerminalResult.final_score by student" if comparable_subject_mode else "mean COMPLETE TerminalResult.final_score by student"), "comparable_subjects": comparison_subjects, "students": records},
                **self.meta(),
            }
        except Exception:
            logger.exception("Student academic ranking failed")
            return {
                "answer": "I couldn't calculate the student ranking safely from the academic database. Please verify the terminal-result data and check the server log for the underlying query error; I won't substitute an unverified student list.",
                **self.meta("database_error"),
            }

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
    # Staff performance / merit questions
    # ------------------------------------------------------------------
    def staff_merit_question(self, q):
        """Handle staff merit questions without confusing directory and merit data."""
        staff_terms = ("staff", "employee", "employees", "personnel", "teacher", "teachers")
        merit_terms = ("best", "top", "outstanding", "highest performing", "most effective",
                       "employee of the term", "staff of the term", "performer")
        if not any(x in q for x in staff_terms) or not any(x in q for x in merit_terms):
            return None
        if not self.can("staff"):
            return self.denied("staff performance information")

        attendance_metric = any(x in q for x in (
            "attendance", "punctual", "punctuality", "reliability", "present most",
            "fewest absences", "least absent", "attendance rate",
        ))
        if not attendance_metric:
            return {
                "answer": (
                    "## Staff Performance — No Verified Overall Ranking\n\n"
                    "The available records include staff profiles, attendance, leave and payroll, but do not establish "
                    "a formal appraisal score or agreed overall performance measure for this term. A staff directory "
                    "or attendance percentage alone cannot establish who is the best employee.\n\n"
                    "Use a recorded appraisal, lesson-observation rubric, agreed teaching-and-learning measure, or "
                    "another approved school criterion to produce an overall ranking."
                ),
                "data": {"ranking_available": False, "reason": "No formal staff appraisal/performance model found"},
                **self.meta("database_unavailable"),
            }

        try:
            from attendance.models import StaffAttendance
            from school.models import AcademicTerm
            from django.db.models import Count, Q

            term = AcademicTerm.objects.filter(
                academic_year__school=self.school, is_active=True
            ).select_related("academic_year").order_by("-start_date").first()
            if not term:
                return {"answer": "There is no active academic term configured, so I cannot calculate a term-based staff attendance ranking.", **self.meta("database_unavailable")}
            qs = StaffAttendance.objects.filter(
                school=self.school, staff__school=self.school, staff__is_active=True,
                date__gte=term.start_date, date__lte=term.end_date,
            )
            summary = list(qs.values(
                "staff_id", "staff__user__first_name", "staff__user__last_name",
            ).annotate(
                recorded=Count("id"),
                present=Count("id", filter=Q(status="PRESENT")),
                late=Count("id", filter=Q(status="LATE")),
                absent=Count("id", filter=Q(status="ABSENT")),
                excused=Count("id", filter=Q(status="EXCUSED")),
            ).filter(recorded__gt=0))
            if not summary:
                return {"answer": f"No staff attendance records were found for **{term.name}** ({term.start_date:%d %b %Y} to {term.end_date:%d %b %Y}).", "data": {"count": 0}, **self.meta("database_unavailable")}

            # A rate based on one or two days is not a reliable term ranking.
            # Require at least five non-excused recorded days before ranking.
            minimum_days = 5
            ranked, insufficient = [], []
            for row in summary:
                denominator = row["recorded"] - row["excused"]
                if denominator < minimum_days:
                    insufficient.append(row)
                    continue
                attended = row["present"] + row["late"]
                rate = (attended / denominator) * 100
                ranked.append((rate, attended, -row["late"], row))
            ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
            limit_match = re.search(r"\b(?:top|best)\s+(\d{1,2})\b", q)
            limit = max(1, min(20, int(limit_match.group(1)))) if limit_match else 10
            lines = [
                f"## Staff Attendance Ranking — {term.name}", "",
                f"**Period:** {term.start_date:%d %B %Y} to {term.end_date:%d %B %Y}",
                "**Measure:** (Present + Late) ÷ (Recorded days − Excused days). Late days count as attended but are shown separately.",
                f"**Minimum evidence:** {minimum_days} non-excused recorded days per staff member.", "",
            ]
            records = []
            if ranked:
                previous = None
                rank = 0
                for position, (rate, attended, _late, row) in enumerate(ranked[:limit], 1):
                    if previous is None or rate != previous:
                        rank = position
                    previous = rate
                    name = (row.get("staff__user__first_name", "") + " " + row.get("staff__user__last_name", "")).strip() or "Unnamed staff member"
                    lines.append(f"{rank}. **{name}** — **{rate:.1f}% attendance**; {row['present']} present, {row['late']} late, {row['absent']} absent, {row['excused']} excused out of {row['recorded']} recorded day(s).")
                    records.append({"rank": rank, "name": name, "attendance_rate": round(rate, 2), "present": row["present"], "late": row["late"], "absent": row["absent"], "excused": row["excused"], "recorded": row["recorded"]})
            else:
                lines.append(f"No staff member currently meets the minimum {minimum_days}-day evidence requirement, so a defensible attendance ranking cannot yet be produced.")
            if insufficient:
                lines += ["", f"**Insufficient attendance history:** {len(insufficient)} staff member(s) have fewer than {minimum_days} non-excused recorded days and are excluded from the ranking."]
            lines += ["", "**Important:** This is an attendance indicator only, not a measure of teaching quality, student outcomes, conduct, or overall job performance."]
            return {"answer": "\n".join(lines), "data": {"term": term.name, "metric": "attendance_rate", "minimum_recorded_days": minimum_days, "ranked_count": len(records), "insufficient_evidence_count": len(insufficient), "staff": records}, **self.meta()}
        except Exception:
            logger.exception("Staff merit/attendance ranking failed")
            return {"answer": "I could not safely calculate the requested staff attendance ranking. Please check the staff attendance records and server log; I will not substitute a staff directory for a performance ranking.", **self.meta("database_error")}

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
        if not any(a in q for a in ("summary", "how much", "total", "outstanding", "owing", "owe", "number of", "count", "how many", "collected")):
            return None
        try:
            from finance.models import Invoice, Payment
            invoices = Invoice.objects.filter(school=self.school)
            payments = Payment.objects.filter(invoice__school=self.school)
            # Collections are actual confirmed payments only. Pending and reversed
            # transactions are deliberately excluded from the amount and count.
            confirmed = payments.filter(status="CONFIRMED")
            if "this term" in q or "current term" in q or "term to date" in q:
                from school.models import AcademicTerm
                term = AcademicTerm.objects.filter(academic_year__school=self.school, is_active=True).order_by("-start_date").first()
                if not term:
                    return {"answer": "There is no active academic term configured, so I cannot calculate term-to-date fee collections.", **self.meta("database_unavailable")}
                confirmed = confirmed.filter(paid_at__date__gte=term.start_date, paid_at__date__lte=term.end_date)
                period = f"{term.name} ({term.start_date:%d %b %Y} to {term.end_date:%d %b %Y})"
            else:
                period = "all recorded dates"
            total_paid = confirmed.aggregate(v=Sum("amount"))["v"] or Decimal("0")
            if "payment" in q or "collection" in q or "collected" in q or "fee" in q:
                count = confirmed.count()
                return {"answer": f"## Confirmed Fee Collections\n\nConfirmed payments for **{period}** total **GH₵{total_paid:,.2f}** across **{count:,} confirmed payment(s)**. Pending and reversed payments are excluded.", "data": {"confirmed_payment_records": count, "confirmed_amount": str(total_paid), "period": period}, **self.meta()}
            total_billed = sum((i.total_amount for i in invoices), Decimal("0"))
            outstanding = total_billed - total_paid
            return {"answer": f"## Finance Summary\n\n- **Invoices:** {invoices.count():,}\n- **Total billed:** **GH₵{total_billed:,.2f}**\n- **Confirmed payments ({period}):** **GH₵{total_paid:,.2f}**\n- **Outstanding (all recorded invoices less confirmed payments):** **GH₵{outstanding:,.2f}**", "data": {"invoices": invoices.count(), "billed": str(total_billed), "paid": str(total_paid), "outstanding": str(outstanding), "period": period}, **self.meta()}
        except Exception:
            logger.exception("Finance summary failed")
            return {"answer": "I could not safely verify the requested financial information. No unverified answer was provided.", **self.meta("database_error")}

    def _attendance_date_window(self, q, today=None):
        """Resolve explicit attendance periods without guessing school days."""
        today = today or timezone.localdate()
        # Explicit ISO date range: from 2026-10-01 to 2026-10-15.
        matches = re.findall(r"\b(20\d{2}-\d{2}-\d{2})\b", q)
        if len(matches) >= 2:
            try:
                start_date, end_date = date.fromisoformat(matches[0]), date.fromisoformat(matches[1])
                if end_date < start_date:
                    start_date, end_date = end_date, start_date
                return start_date, end_date, "custom date range"
            except ValueError:
                pass
        if len(matches) == 1:
            try:
                target = date.fromisoformat(matches[0])
                return target, target, "selected date"
            except ValueError:
                pass

        if "yesterday" in q:
            target = today - timedelta(days=1)
            return target, target, "yesterday"
        if "today" in q or "this morning" in q:
            return today, today, "today"
        if "last 30 days" in q or "past 30 days" in q or ("last month" in q and "this month" not in q and "current month" not in q):
            if "last month" in q and "30 days" not in q:
                first_this_month = today.replace(day=1)
                last_previous = first_this_month - timedelta(days=1)
                return last_previous.replace(day=1), last_previous, "last month"
            return today - timedelta(days=29), today, "last 30 days"
        relative_days = re.search(r"\b(?:last|past)\s+(\d{1,2})\s+days?\b", q)
        if relative_days:
            days = max(1, min(90, int(relative_days.group(1))))
            return today - timedelta(days=days - 1), today, f"last {days} days"
        relative_weeks = re.search(r"\b(?:last|past)\s+(\d{1,2})\s+weeks?\b", q)
        if relative_weeks:
            days = max(1, min(13, int(relative_weeks.group(1)))) * 7
            return today - timedelta(days=days - 1), today, f"last {days} days"
        if "this week" in q or "current week" in q or "weekly" in q:
            start = today - timedelta(days=today.weekday())
            return start, today, "this week"
        if "last week" in q or "previous week" in q:
            this_monday = today - timedelta(days=today.weekday())
            return this_monday - timedelta(days=7), this_monday - timedelta(days=1), "last week"
        if "this month" in q or "current month" in q or "monthly" in q:
            return today.replace(day=1), today, "this month"
        if any(x in q for x in ("this term", "current term", "term to date", "active term", "last term", "previous term")):
            from school.models import AcademicTerm
            terms = AcademicTerm.objects.filter(
                academic_year__school=self.school
            ).select_related("academic_year").order_by("-start_date")
            asks_previous_only = any(x in q for x in ("last term", "previous term")) and not any(x in q for x in ("this term", "current term", "active term", "term to date"))
            if asks_previous_only:
                active = terms.filter(is_active=True).first()
                term = terms.filter(end_date__lt=active.start_date).first() if active else terms.filter(end_date__lt=today).first()
            else:
                term = terms.filter(is_active=True).first()
            if term:
                if term.start_date > today:
                    return None, None, "selected term has not started"
                return term.start_date, min(term.end_date, today), term.name
            return None, None, "requested academic term is not configured"
        if "this year" in q or "year to date" in q or "current year" in q:
            return date(today.year, 1, 1), today, "year to date"
        # For a comparison without an explicit period, prefer a useful weekly
        # comparison. For a simple unqualified question, retain the old today default.
        if any(x in q for x in ("compare", "comparison", "trend", "trends", "over time")):
            start = today - timedelta(days=today.weekday())
            return start, today, "this week"
        return today, today, "today"

    def _attendance_counts(self, queryset):
        from django.db.models import Count, Q
        row = queryset.aggregate(
            total=Count("id"),
            present=Count("id", filter=Q(status="PRESENT")),
            late=Count("id", filter=Q(status="LATE")),
            absent=Count("id", filter=Q(status="ABSENT")),
            excused=Count("id", filter=Q(status="EXCUSED")),
        )
        row = {key: int(value or 0) for key, value in row.items()}
        denominator = row["total"] - row["excused"]
        attended = row["present"] + row["late"]
        row["attendance_rate"] = round((attended / denominator) * 100, 2) if denominator else None
        row["absence_rate"] = round((row["absent"] / denominator) * 100, 2) if denominator else None
        return row

    @staticmethod
    def _is_period_comparison(q):
        """Distinguish time-period comparisons from student-vs-staff comparisons."""
        explicit_pairs = (
            ("this week", "last week"), ("current week", "previous week"),
            ("this month", "last month"), ("current month", "previous month"),
            ("year to date", "same period last year"),
            ("this term", "last term"), ("current term", "previous term"),
        )
        if any(left in q and right in q for left, right in explicit_pairs):
            return True
        # "Compare student and staff attendance this week" compares two groups,
        # not this week against last week.
        return not ("student" in q and "staff" in q) and any(
            token in q for token in ("compare", "comparison", "versus", " vs ", "against")
        ) and any(token in q for token in ("last week", "previous week", "last month", "previous month", "last term", "previous term", "last year", "same period"))

    def attendance(self, q):
        """School-safe student/staff attendance summaries, comparisons and trends.

        Rates are explicitly calculated over recorded, non-excused entries. The
        engine does not infer unrecorded school days or treat missing marks as absences.
        """
        student_terms = ("student", "students", "learner", "learners", "pupil", "pupils")
        staff_terms = ("staff", "employee", "employees", "personnel", "teacher", "teachers")
        student_requested = any(x in q for x in student_terms)
        staff_requested = any(x in q for x in staff_terms)
        attendance_words = any(x in q for x in (
            "attendance", "absent", "absence", "present", "late", "punctual",
            "punctuality", "attendance rate", "attendances",
        ))
        if not attendance_words:
            return None
        if not self.can("attendance"):
            return self.denied("attendance information")

        # A generic attendance question means student attendance. Explicit staff
        # or combined requests are routed to their own record set.
        include_students = student_requested or not staff_requested
        include_staff = staff_requested
        staff_allowed = self.can("staff")
        if include_staff and not staff_allowed and not include_students:
            return self.denied("staff attendance information")

        try:
            # A face-recognition count without a requested period means the
            # complete available history, not today's attendance summary.
            asks_face_count = any(token in q for token in (
                "face recognition", "face-recognition", "facial recognition", "captured through face",
                "captured by face", "face attendance",
            )) and any(token in q for token in ("how many", "count", "number of", "total"))
            has_explicit_period = any(token in q for token in (
                "today", "yesterday", "this week", "last week", "this month", "last month",
                "this term", "last term", "previous term", "last 7 days", "last 14 days", "last 30 days",
                "from 20", "between 20",
            )) or bool(re.search(r"\b20\d{2}-\d{2}-\d{2}\b", q))
            if asks_face_count and include_staff:
                if not staff_allowed:
                    return self.denied("staff attendance information")
                from attendance.models import StaffAttendance
                face_qs = StaffAttendance.objects.filter(
                    school=self.school, staff__school=self.school, staff__is_active=True, method="FACE",
                )
                if str(getattr(self.user, "role", "")).upper() == "HOD":
                    try:
                        department_id = self.user.staff_profile.department_id
                    except Exception:
                        department_id = None
                    if not department_id:
                        return {"answer": "Your department assignment could not be verified, so I stopped the face-attendance count.", **self.meta("scope_verification_failed")}
                    face_qs = face_qs.filter(staff__department_id=department_id)
                if has_explicit_period:
                    face_start, face_end, face_period = self._attendance_date_window(q, timezone.localdate())
                    if face_start is None or face_end is None:
                        return {"answer": "I couldn't identify a valid date range for the face-attendance count.", **self.meta("clarification_required")}
                    face_qs = face_qs.filter(date__gte=face_start, date__lte=face_end)
                    period_text = f" from {face_start:%d %B %Y} to {face_end:%d %B %Y}"
                else:
                    face_period = "all available history"
                    period_text = " across all available attendance history"
                face_count = face_qs.count()
                return {
                    "answer": f"There are **{face_count:,} staff attendance record(s)** captured through face recognition{period_text} in your authorized scope.",
                    "data": {"staff_face_attendance_records": face_count, "period": face_period, "source_model": "attendance.StaffAttendance", "method": "FACE"},
                    **self.meta(),
                }

            today = timezone.localdate()
            start_date, end_date, period_label = self._attendance_date_window(q, today)
            if start_date is None or end_date is None or end_date < start_date:
                return {
                    "answer": "I couldn't identify a valid date range for attendance. Please specify a date, this week, last week, this month, or this term.",
                    **self.meta("database_unavailable"),
                }

            comparison = self._is_period_comparison(q)
            compare_window = None
            if comparison:
                if period_label == "this week":
                    compare_window = (start_date - timedelta(days=7), end_date - timedelta(days=7), "last week")
                elif period_label == "this month":
                    prev_end = start_date - timedelta(days=1)
                    prev_start = prev_end.replace(day=1)
                    compare_window = (prev_start, prev_end, "last month")
                elif period_label == "year to date":
                    prev_year = start_date.replace(year=start_date.year - 1)
                    compare_window = (prev_year, end_date.replace(year=end_date.year - 1), "same period last year")
                elif any(x in q for x in ("this term", "current term", "active term")) and any(x in q for x in ("last term", "previous term")):
                    from school.models import AcademicTerm
                    active_term = AcademicTerm.objects.filter(academic_year__school=self.school, is_active=True).order_by("-start_date").first()
                    previous_term = AcademicTerm.objects.filter(academic_year__school=self.school, end_date__lt=active_term.start_date).order_by("-start_date").first() if active_term else None
                    if active_term and previous_term:
                        elapsed_days = (end_date - start_date).days
                        previous_end = min(previous_term.end_date, previous_term.start_date + timedelta(days=elapsed_days))
                        compare_window = (previous_term.start_date, previous_end, previous_term.name + " (same elapsed period)")
                    else:
                        return {"answer": "I couldn't find both an active term and a previous term, so I cannot make a reliable term comparison.", **self.meta("database_unavailable")}
                else:
                    return {
                        "answer": "For a reliable comparison, please specify **this week vs last week**, **this month vs last month**, or **year to date vs the same period last year**.",
                        **self.meta("clarification_required"),
                    }

            result_data = {"period": period_label, "start_date": start_date.isoformat(), "end_date": end_date.isoformat(), "student": None, "staff": None}
            sections = []

            if include_students:
                from attendance.models import Attendance
                from .role_ai_policy import get_student_scope
                student_scope = get_student_scope(self.user)
                if student_scope != "school" and self.allowed_students is None:
                    return {
                        "answer": "I couldn't verify your assigned student access, so I stopped this attendance query rather than return whole-school figures outside your permitted scope.",
                        **self.meta("scope_verification_failed"),
                    }
                student_qs = Attendance.objects.filter(
                    school=self.school, student__school=self.school,
                    date__gte=start_date, date__lte=end_date,
                )
                if self.allowed_students is not None:
                    try:
                        student_qs = student_qs.filter(student__in=self.allowed_students.values("pk"))
                    except Exception:
                        logger.exception("Could not apply authorized student scope to attendance query")
                        return {"answer": "I couldn't verify your authorized student scope, so I stopped this attendance query rather than risk exposing records outside your access.", **self.meta("scope_verification_failed")}
                student_counts = self._attendance_counts(student_qs)
                result_data["student"] = student_counts
                sections.append(("Student", student_qs, student_counts, "student"))

            if include_staff and staff_allowed:
                from attendance.models import StaffAttendance
                staff_qs = StaffAttendance.objects.filter(
                    school=self.school, staff__school=self.school, staff__is_active=True,
                    date__gte=start_date, date__lte=end_date,
                )
                # HOD policy is department-scoped. Never broaden an HOD query
                # to every staff member in the school.
                if str(getattr(self.user, "role", "")).upper() == "HOD":
                    try:
                        department_id = self.user.staff_profile.department_id
                    except Exception:
                        department_id = None
                    if not department_id:
                        return {"answer": "Your department assignment could not be verified, so I stopped the staff attendance query.", **self.meta("scope_verification_failed")}
                    staff_qs = staff_qs.filter(staff__department_id=department_id)
                staff_counts = self._attendance_counts(staff_qs)
                staff_counts["face_records"] = staff_qs.filter(method="FACE").count()
                staff_counts["manual_records"] = staff_qs.filter(method="MANUAL").count()
                result_data["staff"] = staff_counts
                sections.append(("Staff", staff_qs, staff_counts, "staff"))
            elif include_staff and not staff_allowed and include_students:
                result_data["staff_access"] = "not_authorized"

            if not sections:
                return {"answer": "No attendance records are available in your authorized scope for the selected period.", "data": result_data, **self.meta("database_unavailable")}

            # Status-specific count/list requests take precedence over a general summary.
            requested_status = "ABSENT" if "absent" in q or "absence" in q else "LATE" if "late" in q or "punctual" in q else "PRESENT" if "present" in q else None
            asks_count = any(x in q for x in ("how many", "number of", "count", "total"))
            asks_list = any(x in q for x in ("who", "which", "list", "names", "show me", "show"))
            if requested_status and asks_count and len(sections) == 1:
                label, _qs, counts, _kind = sections[0]
                count = counts[requested_status.lower()]
                return {
                    "answer": f"**{count:,} {label.lower()} attendance record(s)** were marked **{requested_status.lower()}** from **{start_date:%d %B %Y}** to **{end_date:%d %B %Y}**. This counts recorded entries only; missing attendance marks are not assumed to be absences.",
                    "data": {**result_data, "requested_status": requested_status, "count": count}, **self.meta(),
                }
            if requested_status and asks_list and len(sections) == 1:
                label, qs, counts, kind = sections[0]
                filtered = qs.filter(status=requested_status)
                if kind == "student":
                    rows = filtered.select_related("student__user").order_by("-date", "student__user__last_name", "student__user__first_name")[:MAX_LIST]
                    names = [((r.student.user.get_full_name().strip() or r.student.user.username), r.date) for r in rows]
                else:
                    rows = filtered.select_related("staff__user").order_by("-date", "staff__user__last_name", "staff__user__first_name")[:MAX_LIST]
                    names = [((r.staff.user.get_full_name().strip() or r.staff.user.username), r.date) for r in rows]
                matched_count = counts[requested_status.lower()]
                lines = [f"## {requested_status.title()} {label} Attendance", ""]
                if matched_count == 0:
                    lines.append(f"No {label.lower()} were recorded as {requested_status.lower()} for {period_label}.")
                else:
                    lines.extend([f"**{matched_count:,} record(s)** for {period_label}.", ""])
                    lines.extend(f"{i}. **{name}** — {record_date:%d %b %Y}" for i, (name, record_date) in enumerate(names, 1))
                    if matched_count > len(names):
                        lines.append(f"*Showing {len(names)} of {matched_count:,} records.*")
                return {"answer": "\n".join(lines), "data": {**result_data, "requested_status": requested_status, "listed": len(names)}, **self.meta()}

            # Comparisons use the same tenant and authorized student scope.
            if comparison and compare_window:
                previous_start, previous_end, previous_label = compare_window
                previous_parts = []
                if include_students:
                    prev = Attendance.objects.filter(school=self.school, student__school=self.school, date__gte=previous_start, date__lte=previous_end)
                    if self.allowed_students is not None:
                        prev = prev.filter(student__in=self.allowed_students.values("pk"))
                    previous_parts.append(("Student", self._attendance_counts(prev)))
                if include_staff and staff_allowed:
                    prev_staff = StaffAttendance.objects.filter(school=self.school, staff__school=self.school, staff__is_active=True, date__gte=previous_start, date__lte=previous_end)
                    if str(getattr(self.user, "role", "")).upper() == "HOD":
                        try:
                            department_id = self.user.staff_profile.department_id
                        except Exception:
                            department_id = None
                        if not department_id:
                            return {"answer": "Your department assignment could not be verified, so I stopped the staff attendance comparison.", **self.meta("scope_verification_failed")}
                        prev_staff = prev_staff.filter(staff__department_id=department_id)
                    previous_parts.append(("Staff", self._attendance_counts(prev_staff)))
                for label, _qs, current_counts, kind in sections:
                    previous_counts = next((v for k, v in previous_parts if k == label), None)
                    if previous_counts is None:
                        continue
                    current_rate = current_counts["attendance_rate"]
                    previous_rate = previous_counts["attendance_rate"]
                    delta = round(current_rate - previous_rate, 2) if current_rate is not None and previous_rate is not None else None
                    current_counts["comparison"] = {"previous_period": previous_label, "previous": previous_counts, "attendance_rate_change_percentage_points": delta}

            # Trend requests return daily buckets, capped to 31 days to keep the chat concise.
            wants_trend = any(x in q for x in ("trend", "trends", "over time", "daily breakdown", "by day"))
            if wants_trend:
                trend_days = (end_date - start_date).days + 1
                if trend_days > 31:
                    return {"answer": "That trend range is longer than 31 days. Please narrow it to a month or less so the daily breakdown remains readable.", "data": result_data, **self.meta("clarification_required")}
                from django.db.models import Count
                for label, qs, counts, kind in sections:
                    daily = list(qs.values("date").annotate(total=Count("id"), present=Count("id", filter=Q(status="PRESENT")), late=Count("id", filter=Q(status="LATE")), absent=Count("id", filter=Q(status="ABSENT")), excused=Count("id", filter=Q(status="EXCUSED"))).order_by("date"))
                    daily_by_date = {row["date"]: row for row in daily}
                    trend_rows = []
                    for offset in range(trend_days):
                        day = start_date + timedelta(days=offset)
                        row = daily_by_date.get(day, {})
                        trend_rows.append({"date": day.isoformat(), **{k: int(row.get(k, 0) or 0) for k in ("total", "present", "late", "absent", "excused")}})
                    counts["daily_trend"] = trend_rows

            lines = [f"## Attendance Intelligence — {period_label.title()}", "", f"**Period:** {start_date:%d %B %Y} to {end_date:%d %B %Y}", ""]
            for label, _qs, counts, _kind in sections:
                lines.extend([
                    f"### {label} Attendance",
                    f"- Recorded entries: **{counts['total']:,}**",
                    f"- Present: **{counts['present']:,}**",
                    f"- Late: **{counts['late']:,}**",
                    f"- Absent: **{counts['absent']:,}**",
                    f"- Excused: **{counts['excused']:,}**",
                ])
                if _kind == "staff":
                    lines.append(f"- Face-recognition records: **{counts.get('face_records', 0):,}**")
                    lines.append(f"- Manual records: **{counts.get('manual_records', 0):,}**")
                if counts["attendance_rate"] is not None:
                    lines.append(f"- Attendance rate among recorded, non-excused entries: **{counts['attendance_rate']:.2f}%**")
                    lines.append(f"- Absence rate among recorded, non-excused entries: **{counts['absence_rate']:.2f}%**")
                else:
                    lines.append("- Attendance rate: **Not available** (no non-excused entries recorded).")
                comparison_data = counts.get("comparison")
                if comparison_data:
                    prev = comparison_data["previous"]
                    if prev["total"] == 0:
                        lines.append(f"- {comparison_data['previous_period'].title()}: **No attendance records were recorded**; a rate comparison is not available.")
                    elif prev["attendance_rate"] is None:
                        lines.append(f"- {comparison_data['previous_period'].title()}: attendance rate is not available because there were no non-excused records.")
                    else:
                        lines.append(f"- {comparison_data['previous_period'].title()} attendance rate: **{prev['attendance_rate']:.2f}%** ({prev['total']:,} recorded entries).")
                    delta = comparison_data["attendance_rate_change_percentage_points"]
                    if delta is not None:
                        direction = "up" if delta > 0 else "down" if delta < 0 else "unchanged"
                        lines.append(f"- Change: **{abs(delta):.2f} percentage points {direction}** compared with {comparison_data['previous_period']}.")
                if wants_trend:
                    lines.append("- Daily trend:")
                    for day in counts.get("daily_trend", []):
                        lines.append(f"- {day['date']}: {day['present']} present, {day['late']} late, {day['absent']} absent, {day['excused']} excused")
                lines.append("")
            if result_data.get("staff_access") == "not_authorized":
                lines.append("Staff attendance was not included because your role does not have permission to view staff records.")
            lines.append("**Data note:** These rates use attendance entries actually recorded, excluding excused entries. Unmarked days are not treated as absences, and the figures do not by themselves establish a whole-school attendance rate against the full enrolment or staff roster.")
            return {"answer": "\n".join(lines), "data": result_data, **self.meta()}
        except Exception:
            logger.exception("Attendance intelligence failed")
            return {"answer": "I could not safely verify attendance. No unverified answer was provided.", **self.meta("database_error")}

    @staticmethod
    def is_grade_decline_comparison_question(question):
        """Whether the user explicitly asks for a previous-term grade comparison.

        “Falling behind” is also a current-risk request and must not require a
        previous term with completed results.
        """
        question = (question or "").lower()
        return any(phrase in question for phrase in (
            "declining", "declined", "grades dropped", "scores dropped",
            "grades declined", "grades have declined", "grade decline",
            "students whose grades declined", "students with declining grades",
            "performance is declining",
        ))

    @staticmethod
    def academic_risk_band(average, failed_subjects, decline):
        """Return an explainable early-warning band, not a probability."""
        average = float(average or 0)
        failed_subjects = int(failed_subjects or 0)
        decline = float(decline) if decline is not None else None
        if average < 40 or failed_subjects >= 3:
            return "CRITICAL"
        if average < 50 or failed_subjects >= 2 or (decline is not None and decline <= -10):
            return "HIGH"
        if average < 60 or (decline is not None and decline <= -5):
            return "WATCH"
        return "ON_TRACK"

    def academic_risk_intelligence(self, q):
        """Identify students needing timely academic support from real results.

        This is a transparent rule-based early-warning indicator. It does not
        claim to predict an individual student's future or produce a validated
        probability. Only completed terminal results are used.
        """
        risk_terms = (
            "academic risk", "at risk academically", "early intervention",
            "intervention plan", "students at risk", "student at risk",
            "struggling academically", "students struggling", "falling behind",
            "needs academic support", "needing academic support", "students needing support",
            "remedial support", "remedial classes", "academic warning",
            "declining grades", "declining students", "students whose grades declined",
            "grades declined", "grades have declined", "grade decline", "students with declining grades",
            "performance is declining", "below 50", "below 60",
            "failed two or more", "failed three or more", "three or more failed subjects",
            "failing students", "failing in multiple subjects", "poor academic performance",
            "low performing students", "low-performing students", "academic intervention",
            "needs intervention", "students needing intervention", "need academic support",
        )
        if not any(term in q for term in risk_terms):
            return None
        if not self.can("academics") or not self.can("students"):
            return self.denied("student academic risk information")

        try:
            from assessments.models import TerminalResult
            from school.models import AcademicTerm

            base = TerminalResult.objects.filter(
                school=self.school,
                student__school=self.school,
                student__is_active=True,
                status="COMPLETE",
                final_score__isnull=False,
            )
            if self.allowed_students is not None:
                try:
                    base = base.filter(student__in=self.allowed_students.values("pk"))
                except Exception:
                    logger.exception("Could not apply authorized student scope to academic risk intelligence")
                    return {
                        "answer": "I couldn't verify your authorized student scope, so I stopped this academic risk query.",
                        **self.meta("scope_verification_failed"),
                    }

            terms = AcademicTerm.objects.filter(
                academic_year__school=self.school,
                pk__in=base.order_by().values_list("academic_term_id", flat=True).distinct(),
            ).select_related("academic_year").order_by("-end_date", "-start_date")
            available_terms = list(terms[:30])
            active_term = AcademicTerm.objects.filter(
                academic_year__school=self.school, is_active=True
            ).select_related("academic_year").order_by("-start_date").first()

            if any(x in q for x in ("this term", "current term", "active term", "term to date")):
                term = active_term
                if term is None:
                    return {
                        "answer": "There is no active academic term configured, so I cannot identify current-term academic risk.",
                        "data": {"term": None, "student_count": 0}, **self.meta("database_unavailable"),
                    }
            else:
                # Prefer the active term only when it has completed results;
                # otherwise analyse the latest data-bearing term rather than
                # returning an empty report during the opening weeks of a term.
                active_has_results = bool(active_term and base.filter(academic_term=active_term).exists())
                term = active_term if active_has_results else (available_terms[0] if available_terms else active_term)

            if term is None:
                return {
                    "answer": "There are no completed terminal results available for academic early-warning analysis. Draft and incomplete results are excluded.",
                    "data": {"term": None, "student_count": 0, "basis": "COMPLETE TerminalResult records with final_score"},
                    **self.meta("database_unavailable"),
                }

            previous_term = next((item for item in available_terms if item.end_date < term.start_date), None)
            current_qs = base.filter(academic_term=term)

            # Resolve class names against this school's own class records.
            class_name = None
            try:
                from academics.models import SchoolClass
                known_classes = SchoolClass.objects.filter(school=self.school).values_list("name", flat=True)
                class_name = next((name for name in known_classes if self.norm(name) in q), None)
            except Exception:
                logger.debug("Could not resolve class for academic risk query", exc_info=True)
            if class_name:
                current_qs = current_qs.filter(school_class__name__iexact=class_name)

            current_rows = list(current_qs.values(
                "student_id", "student__user__first_name", "student__user__last_name",
                "student__admission_number", "school_class__name", "subject", "final_score",
            ).order_by("student_id", "subject"))
            if not current_rows:
                return {
                    "answer": f"No completed terminal results are available for **{term.name} ({term.academic_year.name})** in the requested scope. I have not inferred risk from missing results.",
                    "data": {"term": term.name, "class": class_name, "student_count": 0, "result_count": 0},
                    **self.meta("database_unavailable"),
                }

            current_by_student = {}
            for row in current_rows:
                sid = row["student_id"]
                item = current_by_student.setdefault(sid, {
                    "student_id": str(sid),
                    "first_name": row.get("student__user__first_name") or "",
                    "last_name": row.get("student__user__last_name") or "",
                    "admission_number": row.get("student__admission_number") or "",
                    "class": row.get("school_class__name") or "Unassigned",
                    "scores": [], "failed_subjects": [], "subjects": [],
                })
                score = float(row["final_score"])
                item["scores"].append(score)
                item["subjects"].append({"subject": row["subject"], "score": round(score, 2)})
                if score < 40:
                    item["failed_subjects"].append(row["subject"])

            previous_by_student = {}
            if previous_term is not None:
                previous_qs = base.filter(academic_term=previous_term)
                if class_name:
                    previous_qs = previous_qs.filter(school_class__name__iexact=class_name)
                previous_rows = previous_qs.values("student_id", "subject", "final_score")
                for previous_row in previous_rows:
                    previous_by_student.setdefault(previous_row["student_id"], {})[previous_row["subject"]] = float(previous_row["final_score"])

            results = []
            for sid, item in current_by_student.items():
                average = sum(item["scores"]) / len(item["scores"]) if item["scores"] else 0.0
                prior_subjects = previous_by_student.get(sid, {})
                current_subject_scores = {subject_row["subject"]: subject_row["score"] for subject_row in item["subjects"]}
                common_subjects = set(current_subject_scores).intersection(prior_subjects)
                comparison_average = (sum(current_subject_scores[name] for name in common_subjects) / len(common_subjects)) if common_subjects else None
                previous_average = (sum(prior_subjects[name] for name in common_subjects) / len(common_subjects)) if common_subjects else None
                decline = round(comparison_average - previous_average, 2) if previous_average is not None else None
                failed_count = len(item["failed_subjects"])
                band = self.academic_risk_band(average, failed_count, decline)
                name = (item["first_name"] + " " + item["last_name"]).strip() or item["admission_number"] or "Student"
                if band == "CRITICAL":
                    recommendation = "Arrange a prompt teacher-led review, identify learning gaps in each failed subject, and agree a short, measurable support plan with regular check-ins."
                elif band == "HIGH":
                    recommendation = "Provide targeted small-group or one-to-one support in weak subjects and review progress at the next assessment."
                elif band == "WATCH":
                    recommendation = "Monitor the next assessment closely, reinforce weaker topics, and check understanding before the next reporting point."
                else:
                    recommendation = "Continue normal teaching support and routine progress monitoring."
                if decline is not None and decline <= -5:
                    recommendation += " Review recent work with the student to understand the term-to-term decline."
                results.append({
                    "student_id": item["student_id"], "name": name, "admission_number": item["admission_number"],
                    "class": item["class"], "average": round(average, 2),
                    "subjects_recorded": len(item["scores"]), "failed_subject_count": failed_count,
                    "failed_subjects": item["failed_subjects"], "previous_average": round(previous_average, 2) if previous_average is not None else None,
                    "comparison_average": round(comparison_average, 2) if comparison_average is not None else None,
                    "matched_subject_count": len(common_subjects),
                    "change_percentage_points": decline, "risk_band": band,
                    "recommendation": recommendation, "subject_scores": item["subjects"],
                })

            wants_declining = self.is_grade_decline_comparison_question(q)
            wants_support = any(x in q for x in (
                "what support", "support should", "how can we help", "how to help",
                "help students at risk", "support for students", "intervention recommendations",
            ))
            if wants_declining:
                results = [row for row in results if row["change_percentage_points"] is not None and row["change_percentage_points"] <= -5]
            elif not any(x in q for x in ("all students", "every student", "whole class", "all learners")):
                results = [row for row in results if row["risk_band"] != "ON_TRACK"]

            order = {"CRITICAL": 0, "HIGH": 1, "WATCH": 2, "ON_TRACK": 3}
            results.sort(key=lambda row: (order[row["risk_band"]], row["average"], row["name"].lower()))
            band_counts = {band: 0 for band in ("CRITICAL", "HIGH", "WATCH", "ON_TRACK")}
            for sid, item in current_by_student.items():
                avg = sum(item["scores"]) / len(item["scores"]) if item["scores"] else 0
                prior_subjects = previous_by_student.get(sid, {})
                current_subject_scores = {subject_row["subject"]: subject_row["score"] for subject_row in item["subjects"]}
                common_subjects = set(current_subject_scores).intersection(prior_subjects)
                comparison_delta = None
                if common_subjects:
                    current_comparable = sum(current_subject_scores[name] for name in common_subjects) / len(common_subjects)
                    previous_comparable = sum(prior_subjects[name] for name in common_subjects) / len(common_subjects)
                    comparison_delta = current_comparable - previous_comparable
                band_counts[self.academic_risk_band(avg, len(item["failed_subjects"]), comparison_delta)] += 1

            period = f"{term.name} ({term.academic_year.name})"
            lines = ["## Predictive Academic Risk & Early Intervention", "", f"**Analysis period:** {period}"]
            if previous_term:
                lines.append(f"**Trend comparison:** {previous_term.name} ({previous_term.academic_year.name}) to {term.name}")
            if class_name:
                lines.append(f"**Class:** {class_name}")
            lines.extend([
                "", f"- **Students assessed:** {len(current_by_student):,}",
                f"- **Critical:** {band_counts['CRITICAL']:,}",
                f"- **High:** {band_counts['HIGH']:,}",
                f"- **Watch:** {band_counts['WATCH']:,}",
                f"- **On track:** {band_counts['ON_TRACK']:,}",
            ])
            if results:
                lines.extend(["", "### Students requiring attention"])
                for row in results[:MAX_LIST]:
                    detail = f"{row['average']:.2f}% average across {row['subjects_recorded']} subject(s); {row['failed_subject_count']} below 40%"
                    if row["change_percentage_points"] is not None:
                        detail += (
                            f"; comparable-subject average {row['previous_average']:.2f}% to "
                            f"{row['comparison_average']:.2f}% across {row['matched_subject_count']} "
                            f"matched subject(s) ({row['change_percentage_points']:+.2f} percentage points)"
                        )
                    lines.append(f"- **{row['name']}** ({row['class']}) — **{row['risk_band']}**: {detail}.")
                    if row["failed_subjects"]:
                        lines.append(f"  - Weak/failed subjects: {', '.join(row['failed_subjects'])}.")
                    lines.append(f"  - Suggested action: {row['recommendation']}")
            else:
                if wants_declining and previous_term is None:
                    no_result_message = (
                        "A previous term with completed results is not available, so I cannot reliably determine "
                        "which students' grades declined. Current-term risk bands are still based on completed "
                        "results only."
                    )
                elif wants_declining:
                    no_result_message = (
                        "No students with comparable completed subject results showed a decline of at least "
                        "5 percentage points between the two terms."
                    )
                else:
                    no_result_message = (
                        "No students currently meet the selected early-warning criteria based on the completed results available."
                    )
                lines.extend(["", no_result_message])
            if wants_support:
                lines.extend([
                    "", "### Recommended support by risk level",
                    "- **Critical:** Arrange a prompt teacher-led review, identify gaps in each weak subject, agree short measurable targets, and schedule regular check-ins.",
                    "- **High:** Provide targeted small-group or one-to-one remedial support, assign a responsible teacher, and review progress at the next assessment.",
                    "- **Watch:** Reinforce weaker topics, check understanding through short formative tasks, and monitor the next assessment closely.",
                    "- **On track:** Continue normal teaching support, offer suitable enrichment, and maintain routine progress monitoring.",
                ])
                if not results:
                    lines.append("No student-specific intervention is indicated by the current completed results. The recommendations above are guidance to use if a student enters one of the risk bands.")
            lines.extend([
                "", "### How to use these alerts",
                "- Treat the bands as prompts for professional review, not labels or diagnoses.",
                "- Confirm the underlying marks and discuss learning needs with the student before deciding on support.",
                "- Record agreed actions and review progress at the next assessment point.",
                "", "**Method note:** This is a transparent rule-based early-warning screen, not a validated prediction or probability of future failure. It uses COMPLETE terminal results only; missing and draft results are not treated as zero. Term-to-term changes are calculated only across subjects with completed results in both terms. Thresholds: below 40% or 3+ failed subjects = Critical; below 50%, 2+ failed subjects or a like-for-like decline of 10+ points = High; below 60% or a like-for-like decline of 5+ points = Watch."
            ])
            data = {
                "term": period, "previous_term": previous_term.name if previous_term else None,
                "class": class_name, "student_count": len(current_by_student),
                "band_counts": band_counts, "students_requiring_attention": results[:MAX_LIST],
                "result_count": len(current_rows), "thresholds": {"pass_mark": 40, "watch_average": 60, "high_average": 50, "critical_average": 40},
                "method": "rule_based_early_warning_not_validated_probability",
                "source_model": "assessments.TerminalResult",
            }
            return {"answer": "\n".join(lines), "data": data, **self.meta()}
        except Exception:
            logger.exception("Academic risk intelligence failed")
            return {"answer": "I could not safely verify academic early-warning indicators from the school database. No unverified risk labels or recommendations were provided.", **self.meta("database_error")}

    def academic_performance_intelligence(self, q):
        """Deterministic academic analytics based on completed terminal results.

        TerminalResult is the authoritative report-card record in this project.
        Drafts and incomplete component scores are excluded from all metrics.
        """
        academic_terms = (
            "academic performance", "subject average", "subject performance",
            "class performance", "class average", "pass rate", "failure rate",
            "failed subjects", "below 40", "below forty", "declining performance",
            "performance trend", "compare this term", "compare terms",
            "weakest subject", "strongest subject", "best subject", "worst subject",
            "average score", "overall average", "school average", "best class",
            "worst class", "top class", "class ranking", "declined scores",
            "scores declined", "dropped scores",
        )
        has_academic_metric = (
            ("subject" in q and any(x in q for x in ("average", "performance", "lowest", "highest", "strongest", "weakest", "best", "worst", "compare")))
            or ("class" in q and any(x in q for x in ("average", "performance", "lowest", "highest", "best", "worst", "top", "compare", "rank")))
            or ("failed" in q and "subject" in q)
            or any(x in q for x in academic_terms)
        )
        if not has_academic_metric:
            return None
        if not self.can("academics"):
            return self.denied("academic performance information")
        if not self.can("students"):
            return self.denied("student academic performance information")

        try:
            from assessments.models import TerminalResult
            from school.models import AcademicTerm
            from django.db.models import Avg, Count

            base = TerminalResult.objects.filter(
                school=self.school,
                student__school=self.school,
                student__is_active=True,
                status="COMPLETE",
                final_score__isnull=False,
            )
            if self.allowed_students is not None:
                try:
                    base = base.filter(student__in=self.allowed_students.values("pk"))
                except Exception:
                    logger.exception("Could not apply authorized student scope to academic intelligence")
                    return {"answer": "I couldn't verify your authorized student scope, so I stopped this academic query.", **self.meta("scope_verification_failed")}

            current_requested = any(x in q for x in ("this term", "current term", "active term", "term to date"))
            previous_requested = any(x in q for x in ("last term", "previous term", "previous academic term"))
            terms_with_results = AcademicTerm.objects.filter(
                academic_year__school=self.school,
                pk__in=base.order_by().values_list("academic_term_id", flat=True).distinct(),
            ).select_related("academic_year").order_by("-end_date", "-start_date")
            active_term = AcademicTerm.objects.filter(
                academic_year__school=self.school, is_active=True
            ).select_related("academic_year").order_by("-start_date").first()
            available_terms = list(terms_with_results[:30])
            if current_requested:
                term = active_term
                if term is None:
                    return {"answer": "There is no active academic term configured, so I cannot label any results as current-term performance.", "data": {"term": None, "result_count": 0}, **self.meta("database_unavailable")}
            elif previous_requested:
                if active_term is None:
                    return {"answer": "There is no active academic term configured, so I cannot reliably identify the previous term.", "data": {"term": None, "result_count": 0}, **self.meta("database_unavailable")}
                term = next((t for t in available_terms if t.end_date < active_term.start_date), None)
            else:
                term = available_terms[0] if available_terms else None

            if term is None:
                return {
                    "answer": "There are no completed terminal results available for the requested academic period. Draft or incomplete results are excluded from performance calculations.",
                    "data": {"result_count": 0, "term": None, "basis": "COMPLETE TerminalResult records with final_score"},
                    **self.meta("database_unavailable"),
                }

            qs = base.filter(academic_term=term)
            # Resolve a named class only against classes belonging to this school.
            class_name = None
            try:
                from academics.models import SchoolClass
                known_classes = SchoolClass.objects.filter(school=self.school).values_list("name", flat=True)
                class_name = next((name for name in known_classes if self.norm(name) in q), None)
            except Exception:
                logger.debug("Could not resolve academic class name", exc_info=True)
            if class_name:
                qs = qs.filter(school_class__name__iexact=class_name)

            # Resolve a subject only against subjects with actual completed records.
            subjects = list(qs.order_by().values_list("subject", flat=True).distinct())
            subject_name = next((name for name in subjects if self.norm(name) in q), None)
            if subject_name:
                qs = qs.filter(subject__iexact=subject_name)

            if not qs.exists():
                return {"answer": f"No completed academic results match the requested filters for **{term.name} ({term.academic_year.name})**.", "data": {"term": term.name, "class": class_name, "subject": subject_name, "result_count": 0}, **self.meta("database_unavailable")}

            aggregate = qs.aggregate(
                average=Avg("final_score"),
                results=Count("id"),
                students=Count("student_id", distinct=True),
            )
            result_count = aggregate["results"] or 0
            average = float(aggregate["average"] or 0)
            pass_count = qs.filter(final_score__gte=40).count()
            fail_count = qs.filter(final_score__lt=40).count()
            pass_rate = (pass_count / result_count * 100.0) if result_count else 0.0
            failure_rate = (fail_count / result_count * 100.0) if result_count else 0.0
            title = f"{term.name} — {term.academic_year.name}"
            data = {
                "term": title, "average_percentage": round(average, 2),
                "result_count": result_count, "student_count": aggregate["students"] or 0,
                "pass_count": pass_count, "fail_count": fail_count,
                "pass_rate": round(pass_rate, 2), "failure_rate": round(failure_rate, 2), "class": class_name,
                "subject": subject_name,
                "basis": "COMPLETE TerminalResult records; pass threshold 40/100",
            }

            wants_subjects = any(x in q for x in ("subject", "subjects", "strongest", "weakest", "best subject", "worst subject"))
            wants_classes = any(x in q for x in ("class", "classes", "across all classes", "compare classes"))
            wants_risk = any(x in q for x in ("below 40", "below forty", "failed", "failure", "at risk", "struggling", "weak students"))
            wants_trend = any(x in q for x in ("compare this term", "compare terms", "last term", "previous term", "declining", "declined", "dropped", "trend"))

            lines = ["## Academic Performance Intelligence", "", f"**Period:** {title}"]
            if class_name:
                lines.append(f"**Class:** {class_name}")
            if subject_name:
                lines.append(f"**Subject:** {subject_name}")
            lines.extend([
                "", f"- **Average score:** {average:.2f}%",
                f"- **Students represented:** {data['student_count']:,}",
                f"- **Completed subject results:** {result_count:,}",
                f"- **Pass rate:** {pass_rate:.2f}% ({pass_count:,} passed)",
                f"- **Failure rate:** {failure_rate:.2f}% ({fail_count:,} below 40%)",
            ])

            if wants_subjects:
                rows = list(qs.values("subject").annotate(
                    average=Avg("final_score"), count=Count("id"),
                    students=Count("student_id", distinct=True),
                ).order_by("average", "subject"))
                if rows:
                    lines.extend(["", "### Subject performance"])
                    for row in rows:
                        lines.append(f"- **{row['subject']}** — {float(row['average'] or 0):.2f}% average across {row['count']:,} result(s)")
                    lowest, highest = rows[0], rows[-1]
                    lines.append(f"\n**Lowest average:** {lowest['subject']} ({float(lowest['average'] or 0):.2f}%).")
                    lines.append(f"**Highest average:** {highest['subject']} ({float(highest['average'] or 0):.2f}%).")
                    data["subjects"] = [{"subject": r["subject"], "average": round(float(r["average"] or 0), 2), "results": r["count"], "students": r["students"]} for r in rows]

            if wants_classes:
                rows = list(qs.values("school_class__name").annotate(
                    average=Avg("final_score"), count=Count("id"),
                    students=Count("student_id", distinct=True),
                ).order_by("-average", "school_class__name"))
                lines.extend(["", "### Class comparison"])
                for row in rows:
                    name = row["school_class__name"] or "Unassigned class"
                    lines.append(f"- **{name}** — {float(row['average'] or 0):.2f}% average ({row['students']:,} students; {row['count']:,} results)")
                data["classes"] = [{"class": r["school_class__name"] or "Unassigned", "average": round(float(r["average"] or 0), 2), "results": r["count"], "students": r["students"]} for r in rows]

            if wants_risk:
                risk_qs = qs.filter(final_score__lt=40).values(
                    "student_id", "student__user__first_name", "student__user__last_name",
                    "student__admission_number", "school_class__name",
                ).annotate(failed_subjects=Count("id")).order_by("-failed_subjects", "student__user__last_name")
                threshold_match = re.search(r"(?:at least|more than|over)\s+(\d+)", q)
                if threshold_match:
                    minimum_failed = int(threshold_match.group(1)) + (1 if any(x in q for x in ("more than", "over")) else 0)
                    risk_qs = risk_qs.filter(failed_subjects__gte=minimum_failed)
                elif any(x in q for x in ("three or more", "3 or more")):
                    minimum_failed = 3
                    risk_qs = risk_qs.filter(failed_subjects__gte=minimum_failed)
                risk_rows = list(risk_qs[:MAX_LIST])
                lines.extend(["", "### Students requiring academic support"])
                if risk_rows:
                    for row in risk_rows:
                        name = (row["student__user__first_name"] + " " + row["student__user__last_name"]).strip() or row["student__admission_number"]
                        lines.append(f"- **{name}** — {row['failed_subjects']} subject result(s) below 40%; {row['school_class__name'] or 'class not assigned'}")
                else:
                    lines.append("No completed subject results are below the 40% pass threshold in this period.")
                data["students_below_threshold"] = [{"student_id": str(r["student_id"]), "name": ((r["student__user__first_name"] or "") + " " + (r["student__user__last_name"] or "")).strip() or r["student__admission_number"], "failed_subjects": r["failed_subjects"], "class": r["school_class__name"]} for r in risk_rows]
                if len(risk_rows) == MAX_LIST:
                    lines.append(f"\n*Showing up to {MAX_LIST} students.*")

            if wants_trend:
                previous = next((t for t in available_terms if t.end_date < term.start_date), None)
                lines.extend(["", "### Term comparison"])
                if previous:
                    prior = base.filter(academic_term=previous)
                    if class_name:
                        prior = prior.filter(school_class__name__iexact=class_name)
                    if subject_name:
                        prior = prior.filter(subject__iexact=subject_name)
                    prior_metrics = prior.aggregate(value=Avg("final_score"), result_count=Count("id"))
                    prior_avg = prior_metrics["value"]
                    if prior_avg is not None:
                        prior_value = float(prior_avg)
                        delta = average - prior_value
                        direction = "improved" if delta > 0 else "declined" if delta < 0 else "remained unchanged"
                        lines.append(f"Compared with **{previous.name} ({previous.academic_year.name})**, the average {direction} by **{abs(delta):.2f} percentage points** (previous average: {prior_value:.2f}% across {prior_metrics['result_count']:,} completed result(s)).")
                        data["previous_term"] = {"term": previous.name, "average_percentage": round(prior_value, 2), "result_count": prior_metrics["result_count"], "change_percentage_points": round(delta, 2)}
                        if any(x in q for x in ("declining", "declined", "dropped")):
                            trend_qs = base.filter(academic_term__in=[term, previous])
                            if class_name:
                                trend_qs = trend_qs.filter(school_class__name__iexact=class_name)
                            if subject_name:
                                trend_qs = trend_qs.filter(subject__iexact=subject_name)
                            trend_rows = list(trend_qs.values(
                                "student_id", "student__user__first_name", "student__user__last_name",
                                "student__admission_number", "school_class__name", "academic_term_id",
                            ).annotate(average=Avg("final_score")))
                            by_student = {}
                            for row in trend_rows:
                                by_student.setdefault(row["student_id"], {"current": None, "previous": None, "row": row})
                                by_student[row["student_id"]]["current" if row["academic_term_id"] == term.pk else "previous"] = float(row["average"] or 0)
                            declining = []
                            for item in by_student.values():
                                if item["current"] is None or item["previous"] is None or item["current"] >= item["previous"]:
                                    continue
                                row = item["row"]
                                name = ((row["student__user__first_name"] or "") + " " + (row["student__user__last_name"] or "")).strip() or row["student__admission_number"]
                                declining.append({"name": name, "class": row["school_class__name"], "current_average": round(item["current"], 2), "previous_average": round(item["previous"], 2), "change": round(item["current"] - item["previous"], 2)})
                            declining.sort(key=lambda item: item["change"])
                            lines.extend(["", "### Students with declining averages"])
                            if declining:
                                for item in declining[:MAX_LIST]:
                                    lines.append(f"- **{item['name']}** — {item['class'] or 'class not assigned'}: {item['previous_average']:.2f}% to {item['current_average']:.2f}% ({item['change']:.2f} percentage points)")
                            else:
                                lines.append("No students with comparable results in both terms showed a decline.")
                            data["declining_students"] = declining[:MAX_LIST]
                    else:
                        lines.append(f"No comparable completed results were found for {previous.name}.")
                else:
                    lines.append("There is no earlier term with completed results available for comparison.")

            lines.extend(["", "**Data note:** Only COMPLETE terminal results with a final score are included. The pass threshold is 40%, matching the terminal-result grading rules. Missing or draft results are not counted as failures. Averages are calculated across recorded student-subject results; comparisons can be affected by differences in completed subject coverage between terms."])
            return {"answer": "\n".join(lines), "data": data, **self.meta()}
        except Exception:
            logger.exception("Academic performance intelligence failed")
            return {"answer": "I could not safely verify the requested academic performance information from the school database. No unverified figures were provided.", **self.meta("database_error")}

    def academic_summary(self, q):
        risk_intelligence = self.academic_risk_intelligence(q)
        if risk_intelligence is not None:
            return risk_intelligence
        intelligence = self.academic_performance_intelligence(q)
        if intelligence is not None:
            return intelligence
        if not any(x in q for x in ("result", "results", "assessment", "assessments", "exam", "exams", "marks", "scores", "performance")):
            return None
        if not self.can("academics"):
            return self.denied("academic information")
        if not any(x in q for x in ("how many", "number of", "count", "total", "average", "highest", "lowest", "summary")):
            return None
        try:
            from assessments.models import Assessment, Grade, TerminalResult
            assessments = Assessment.objects.filter(school=self.school)
            grade_qs = Grade.objects.filter(assessment__school=self.school, student__school=self.school)
            terminal_qs = TerminalResult.objects.filter(school=self.school, student__school=self.school)
            if self.allowed_students is not None:
                try:
                    grade_qs = grade_qs.filter(student__in=self.allowed_students.values("pk"))
                    terminal_qs = terminal_qs.filter(student__in=self.allowed_students.values("pk"))
                except Exception:
                    logger.exception("Could not apply authorized student scope to academic summary")
                    return {"answer": "I couldn't verify your authorized student scope, so I stopped this academic query.", **self.meta("scope_verification_failed")}
            # Explicit average requests must return a numeric average, not model counts.
            if "average" in q or "highest" in q or "lowest" in q:
                grades = list(grade_qs.select_related("assessment"))
                percentages = []
                for grade in grades:
                    maximum = getattr(grade.assessment, "max_score", None)
                    if maximum and maximum > 0 and grade.score_achieved is not None:
                        percentages.append((float(grade.score_achieved) / float(maximum)) * 100.0)
                if not percentages:
                    return {"answer": "There are no scored assessment grade records available in your authorized school scope, so I cannot calculate an average assessment percentage.", "data": {"grade_records": grade_qs.count(), "average_percentage": None}, **self.meta("database_unavailable")}
                average = sum(percentages) / len(percentages)
                if "highest" in q:
                    value = max(percentages)
                    label = "highest"
                elif "lowest" in q:
                    value = min(percentages)
                    label = "lowest"
                else:
                    value = average
                    label = "average"
                return {"answer": f"The {label} recorded assessment score is **{value:.2f}%** across **{len(percentages):,} graded assessment entries**. Scores are normalized against each assessment's maximum score.", "data": {"metric": label, "percentage": round(value, 2), "graded_entries": len(percentages), "assessment_count": assessments.count()}, **self.meta()}
            assessment_count = assessments.count()
            grade_count = grade_qs.count()
            terminal_count = terminal_qs.count()
            if "terminal" in q or "report result" in q:
                return {"answer": f"There are **{terminal_count:,} terminal result records** in the authorized school scope.", "data": {"terminal_results": terminal_count}, **self.meta()}
            return {"answer": f"## Academic Records\n\n- **Assessments:** {assessment_count:,}\n- **Graded entries:** {grade_count:,}\n- **Terminal results:** {terminal_count:,}", "data": {"assessments": assessment_count, "grades": grade_count, "terminal_results": terminal_count}, **self.meta()}
        except Exception:
            logger.exception("Academic summary failed")
            return {"answer": "I could not safely verify the requested academic information. No unverified answer was provided.", **self.meta("database_error")}

    def online_exams(self, q):
        """Verified operational summaries for the online examination module.

        Never expose question text, correct answers, or another teacher's
        private exam records. Teacher access is limited to exams they created;
        student attempt metrics are additionally constrained to authorized
        students when the caller supplies that scope.
        """
        if not any(x in q for x in ("online exam", "online exams", "online examination", "online examinations", "exam attempt", "exam attempts", "online test", "online tests")):
            return None
        if not self.can("exams"):
            return self.denied("online examination information")
        try:
            from online_exams.models import OnlineExam, ExamAttempt
            exams = OnlineExam.objects.filter(school=self.school)
            attempts = ExamAttempt.objects.filter(exam__school=self.school, student__school=self.school)

            # Teachers can inspect only examinations they created and attempts
            # attached to those examinations. Further limit attempt data to
            # the teacher's authorized students when that scope is available.
            if str(getattr(self.user, "role", "")).upper() == "TEACHER":
                exams = exams.filter(created_by=self.user)
                attempts = attempts.filter(exam__created_by=self.user)
                if self.allowed_students is not None:
                    try:
                        attempts = attempts.filter(student__in=self.allowed_students.values("pk"))
                    except Exception:
                        logger.exception("Could not apply authorized student scope to online exam attempts")
                        return {"answer": "I couldn't verify your authorized student scope, so I stopped this online-examination query.", **self.meta("scope_verification_failed")}

            if any(x in q for x in ("average", "mean score", "average score")) and "attempt" not in q:
                graded = attempts.filter(exam__in=exams, grading_status="GRADED", total_marks__gt=0).only("score_awarded", "total_marks")
                percentages = [float(row.score_awarded) * 100.0 / float(row.total_marks) for row in graded]
                if not percentages:
                    return {"answer": "There are no graded online-exam attempts with a valid maximum mark in your authorized scope, so I cannot calculate an average.", "data": {"graded_attempts": 0, "average_percentage": None}, **self.meta("database_unavailable")}
                average = sum(percentages) / len(percentages)
                return {"answer": f"The average score across **{len(percentages):,} graded online-exam attempts** is **{average:.2f}%**.", "data": {"graded_attempts": len(percentages), "average_percentage": round(average, 2)}, **self.meta()}

            if "attempt" in q:
                if "submitted" in q:
                    attempts = attempts.filter(status="SUBMITTED")
                elif "in progress" in q or "ongoing" in q:
                    attempts = attempts.filter(status="IN_PROGRESS")
                elif "expired" in q:
                    attempts = attempts.filter(status="EXPIRED")
                if "graded" in q or "marked" in q:
                    attempts = attempts.filter(grading_status="GRADED")
                elif "pending" in q or "not graded" in q or "awaiting marking" in q:
                    attempts = attempts.exclude(grading_status="GRADED")
                count = attempts.count()
                if any(x in q for x in ("average", "mean")):
                    graded = attempts.filter(grading_status="GRADED", total_marks__gt=0).only("score_awarded", "total_marks")
                    percentages = [float(row.score_awarded) * 100.0 / float(row.total_marks) for row in graded]
                    if not percentages:
                        return {"answer": "There are no graded online-exam attempts with a valid maximum mark in your authorized scope, so I cannot calculate an average.", "data": {"attempts": count, "average_percentage": None}, **self.meta("database_unavailable")}
                    average = sum(percentages) / len(percentages)
                    return {"answer": f"The average score across **{len(percentages):,} graded online-exam attempts** is **{average:.2f}%**.", "data": {"graded_attempts": len(percentages), "average_percentage": round(average, 2)}, **self.meta()}
                return {"answer": f"There are **{count:,} online-exam attempts** matching your query in your authorized scope.", "data": {"attempts": count, "status": "SUBMITTED" if "submitted" in q else "IN_PROGRESS" if "in progress" in q or "ongoing" in q else "EXPIRED" if "expired" in q else None}, **self.meta()}

            status = next((value for token, value in (("published", "PUBLISHED"), ("draft", "DRAFT"), ("closed", "CLOSED")) if token in q), None)
            if status:
                exams = exams.filter(status=status)
            count = exams.count()
            if any(x in q for x in ("which", "list", "show", "names", "titles")):
                rows = exams.select_related("school_class", "subject").order_by("-opens_at")[:MAX_LIST]
                lines = ["## Online Examinations", ""]
                for exam in rows:
                    lines.append(f"- **{exam.title}** — {exam.school_class.name} / {exam.subject.name} ({exam.get_status_display()})")
                if count == 0:
                    lines.append("No matching online examinations were found.")
                return {"answer": "\n".join(lines), "data": {"count": count, "status": status}, **self.meta()}

            breakdown = {value: exams.model.objects.filter(school=self.school, **({"created_by": self.user} if str(getattr(self.user, "role", "")).upper() == "TEACHER" else {}), status=value).count() for value in ("DRAFT", "PUBLISHED", "CLOSED")}
            return {"answer": f"## Online Examination Summary\n\n- **Matching examinations:** {count:,}\n- Draft: **{breakdown['DRAFT']:,}**\n- Published: **{breakdown['PUBLISHED']:,}**\n- Closed: **{breakdown['CLOSED']:,}**", "data": {"count": count, "status_breakdown": breakdown}, **self.meta()}
        except Exception:
            logger.exception("Online examination intelligence failed")
            return {"answer": "I could not safely verify the online-examination information. No unverified answer was provided.", **self.meta("database_error")}

    def lesson_plan_metrics(self, q):
        """School-scoped lesson-plan submission and review status."""
        if not any(x in q for x in ("lesson plan", "lesson plans", "lesson note", "lesson notes", "weekly plan", "weekly plans")):
            return None
        if not self.can("academics"):
            return self.denied("lesson-plan information")
        try:
            from lesson_plans.models import WeeklyLessonPlan
            qs = WeeklyLessonPlan.objects.filter(school=self.school, teacher__school=self.school)
            if str(getattr(self.user, "role", "")).upper() == "TEACHER":
                qs = qs.filter(teacher__user=self.user)

            status_map = {
                "draft": WeeklyLessonPlan.STATUS_DRAFT,
                "submitted": WeeklyLessonPlan.STATUS_SUBMITTED,
                "pending review": WeeklyLessonPlan.STATUS_SUBMITTED,
                "awaiting review": WeeklyLessonPlan.STATUS_SUBMITTED,
                "revision": WeeklyLessonPlan.STATUS_REVISION,
                "revision requested": WeeklyLessonPlan.STATUS_REVISION,
                "approved": WeeklyLessonPlan.STATUS_APPROVED,
            }
            selected_status = next((value for phrase, value in status_map.items() if phrase in q), None)
            if selected_status:
                qs = qs.filter(status=selected_status)
            count = qs.count()
            if any(x in q for x in ("which", "list", "show", "topics", "titles")):
                rows = qs.select_related("teacher__user", "school_class", "subject").order_by("-week_start")[:MAX_LIST]
                lines = ["## Lesson Plans", ""]
                for plan in rows:
                    # Teacher users see only their own plans due to the filter above.
                    teacher_name = plan.teacher.user.get_full_name().strip() or plan.teacher.user.username
                    lines.append(f"- **{plan.topic}** — {plan.school_class.name} / {plan.subject.name}; {teacher_name}; week of {plan.week_start:%d %b %Y}; {plan.get_status_display()}")
                if count == 0:
                    lines.append("No matching lesson plans were found.")
                return {"answer": "\n".join(lines), "data": {"count": count, "status": selected_status}, **self.meta()}

            base = WeeklyLessonPlan.objects.filter(school=self.school, teacher__school=self.school)
            if str(getattr(self.user, "role", "")).upper() == "TEACHER":
                base = base.filter(teacher__user=self.user)
            breakdown = {value: base.filter(status=value).count() for value in (WeeklyLessonPlan.STATUS_DRAFT, WeeklyLessonPlan.STATUS_SUBMITTED, WeeklyLessonPlan.STATUS_REVISION, WeeklyLessonPlan.STATUS_APPROVED)}
            return {"answer": f"## Lesson Plan Summary\n\n- **Matching plans:** {count:,}\n- Draft: **{breakdown[WeeklyLessonPlan.STATUS_DRAFT]:,}**\n- Submitted for review: **{breakdown[WeeklyLessonPlan.STATUS_SUBMITTED]:,}**\n- Revision requested: **{breakdown[WeeklyLessonPlan.STATUS_REVISION]:,}**\n- Approved: **{breakdown[WeeklyLessonPlan.STATUS_APPROVED]:,}**", "data": {"count": count, "status_breakdown": breakdown}, **self.meta()}
        except Exception:
            logger.exception("Lesson-plan intelligence failed")
            return {"answer": "I could not safely verify lesson-plan information. No unverified answer was provided.", **self.meta("database_error")}

    def library(self, q):
        if not any(x in q for x in ("book", "books", "library", "borrow", "borrowing", "overdue")):
            return None
        if not self.can("school_intelligence"):
            return self.denied("library information")
        try:
            from library.models import Book, BookBorrowing
            today = timezone.localdate()
            if "overdue" in q:
                qs = BookBorrowing.objects.filter(
                    school=self.school, book__school=self.school,
                    due_date__lt=today, status__in=("ACTIVE", "OVERDUE"), returned_at__isnull=True,
                ).select_related("book", "borrowed_by_student__user", "borrowed_by_staff__user").order_by("due_date")
                count = qs.count()
                if any(x in q for x in ("which", "what", "list", "show", "names")):
                    lines = [f"## Overdue Library Loans — {today:%d %B %Y}", ""]
                    for item in qs[:MAX_LIST]:
                        borrower = item.get_borrower_name()
                        lines.append(f"- **{item.book.title}** by {item.book.author} — borrowed by {borrower}; due {item.due_date:%d %b %Y}")
                    if not count:
                        lines.append("No currently overdue loans were found.")
                    return {"answer": "\n".join(lines), "data": {"overdue_loans": count, "as_of": today.isoformat()}, **self.meta()}
                return {"answer": f"There are **{count:,} currently overdue library loans** as of {today:%d %B %Y}.", "data": {"overdue_loans": count}, **self.meta()}
            if "borrow" in q or "borrowing" in q:
                qs = BookBorrowing.objects.filter(school=self.school, book__school=self.school)
                if "active" in q or "currently" in q:
                    qs = qs.filter(status="ACTIVE")
                count = qs.count()
                return {"answer": f"There are **{count:,} matching library borrowing records** in the school database.", "data": {"count": count}, **self.meta()}
            books = Book.objects.filter(school=self.school)
            total_titles = books.count()
            total_copies = books.aggregate(v=Sum("total_copies"))["v"] or 0
            available = books.aggregate(v=Sum("available_copies"))["v"] or 0
            if any(x in q for x in ("how many", "number of", "count", "total", "summary")):
                return {"answer": f"## Library Summary\n\n- **Book titles:** {total_titles:,}\n- **Total copies:** {total_copies:,}\n- **Available copies:** {available:,}", "data": {"titles": total_titles, "copies": total_copies, "available": available}, **self.meta()}
            return None
        except Exception:
            logger.exception("Library intelligence failed")
            return {"answer": "I could not safely verify the requested library information. No unverified answer was provided.", **self.meta("database_error")}

    def admissions(self, q):
        if not any(x in q for x in ("admission", "admissions", "application", "applications", "applicant", "applicants")):
            return None
        if not any(x in q for x in ("how many", "number of", "count", "total", "list", "show", "status", "submitted", "approved", "rejected", "admitted")):
            return None
        if not self.can("students"):
            return self.denied("admissions information")
        try:
            from admissions.models import AdmissionApplication
            qs = AdmissionApplication.objects.filter(school=self.school)
            for status in ("DRAFT", "SUBMITTED", "REVIEW", "APPROVED", "REJECTED", "ADMITTED"):
                if status.lower() in q:
                    qs = qs.filter(status=status)
                    break
            count = qs.count()
            breakdown = {status: qs.model.objects.filter(school=self.school, status=status).count() for status in ("DRAFT", "SUBMITTED", "REVIEW", "APPROVED", "REJECTED", "ADMITTED")}
            return {"answer": f"## Admission Applications\n\n**{count:,} applications** match your query.\n\n" + "\n".join(f"- {status.title()}: **{number:,}**" for status, number in breakdown.items()), "data": {"count": count, "status_breakdown": breakdown}, **self.meta()}
        except Exception:
            logger.exception("Admissions intelligence failed")
            return {"answer": "I could not safely verify admission applications. No unverified answer was provided.", **self.meta("database_error")}


    # ------------------------------------------------------------------
    # Operational intelligence for registered non-core school modules.
    # These are explicit, model-backed measures; no arbitrary field guessing.
    # ------------------------------------------------------------------
    def operational_metrics(self, q):
        payroll = any(x in q for x in ("payroll", "payslip", "pay slips", "salary", "salaries", "wages", "net pay", "gross pay"))
        workload = any(x in q for x in (
            "teacher workload", "workload", "overloaded teacher", "overloaded teachers",
            "overloaded", "teaching periods", "average teacher", "average workload",
        ))
        timetable = any(x in q for x in ("timetable", "timetables", "timetable conflict", "timetable conflicts", "published timetable"))
        promotion = any(x in q for x in (
            "promotion", "promotions", "promoted", "were promoted", "has been promoted",
            "have been promoted", "repeated", "were repeated", "students repeat",
            "conditionally promoted", "repeated students",
        ))
        inventory = any(x in q for x in ("inventory", "stock", "logistics", "logistic item", "logistic items", "items in stock"))
        transport = any(x in q for x in ("transport route", "transport routes", "transport subscription", "transport subscriptions", "school bus", "bus route", "bus routes"))
        if not any((payroll, workload, timetable, promotion, inventory, transport)):
            return None

        capability = "payroll" if payroll else "academics" if (workload or timetable or promotion) else "finance"
        if not self.can(capability):
            return self.denied("operational information")

        try:
            from django.db.models import Sum, Avg, Count
            from django.utils import timezone

            # Payroll: only approved/paid runs represent authorised payroll.
            if payroll:
                from staff.models import PayrollRun
                paid_by_date = "paid" in q or "payment" in q
                # A question about money actually paid must exclude APPROVED runs;
                # only PAID runs represent completed disbursements.
                statuses = ("PAID",) if paid_by_date else ("APPROVED", "PAID")
                all_runs = PayrollRun.objects.filter(school=self.school)
                qs = all_runs.filter(status__in=statuses)
                today = timezone.localdate()
                period_label = "all approved/paid payroll periods"
                date_field = "payroll_period__payment_date" if paid_by_date else "payroll_period__period_start"
                if "this month" in q or "current month" in q:
                    qs = qs.filter(**{f"{date_field}__year": today.year,
                                      f"{date_field}__month": today.month})
                    period_label = today.strftime("%B %Y")
                elif "this year" in q or "current year" in q:
                    qs = qs.filter(**{f"{date_field}__year": today.year})
                    period_label = str(today.year)
                elif "this term" in q or "current term" in q or "active term" in q:
                    from school.models import AcademicTerm
                    term = AcademicTerm.objects.filter(
                        academic_year__school=self.school, is_active=True
                    ).order_by("-start_date").first()
                    if term:
                        qs = qs.filter(
                            payroll_period__period_start__gte=term.start_date,
                            payroll_period__period_end__lte=term.end_date,
                        )
                        period_label = f"{term.name} ({term.start_date:%d %b %Y}–{term.end_date:%d %b %Y})"
                    else:
                        return {"answer": "I cannot calculate payroll for the current term because no active academic term is configured.", **self.meta("database_unavailable")}
                totals = qs.aggregate(gross=Sum("gross_pay"), net=Sum("net_pay"),
                                      deductions=Sum("total_deductions"), allowances=Sum("total_allowances"))
                count = qs.count()
                all_run_count = all_runs.count()
                status_breakdown = {row["status"]: row["count"] for row in all_runs.values("status").annotate(count=Count("id"))}
                if any(x in q for x in ("how many", "number of", "count", "total runs", "payroll runs")) and not any(x in q for x in ("how much", "total paid", "net pay", "gross pay", "salary", "salaries", "wages")):
                    return {"answer": f"There are **{count:,} approved or paid payroll run records** for **{period_label}**.",
                            "data": {"payroll_runs": count, "period": period_label}, **self.meta()}
                amount_key = "gross" if "gross" in q else "deductions" if "deduction" in q else "allowances" if "allowance" in q else "net"
                amount = totals.get(amount_key) or Decimal("0.00")
                label = {"gross": "gross payroll", "net": "net payroll paid", "deductions": "payroll deductions", "allowances": "payroll allowances"}[amount_key]
                if count:
                    answer = f"Recorded **{label}** for **{period_label}** is **GH₵{amount:,.2f}**, across **{count:,} matching payroll run(s)**."
                else:
                    answer = f"No payroll runs with the required status ({', '.join(statuses)}) match **{period_label}**. The recorded **{label}** is therefore **GH₵0.00** for this filtered query."
                answer += f"\n\n**Evidence:** {all_run_count:,} payroll run(s) exist in the school database across all periods/statuses; status breakdown: " + (", ".join(f"{k}: {v}" for k, v in sorted(status_breakdown.items())) or "no runs") + f".\n\n**Filter:** status {', '.join(statuses)}; date field {date_field}; period {period_label}."
                return {"answer": answer,
                        "data": {"metric": amount_key, "amount": str(amount), "matching_payroll_runs": count, "all_school_payroll_runs": all_run_count, "status_breakdown": status_breakdown, "statuses_included": list(statuses), "date_field": date_field, "period": period_label, "source_model": "staff.PayrollRun"}, **self.meta()}

            if workload:
                from academics.models import TeacherWorkload
                qs = TeacherWorkload.objects.filter(school=self.school)
                term = None
                if any(x in q for x in ("this term", "current term", "active term")):
                    from school.models import AcademicTerm
                    term = AcademicTerm.objects.filter(academic_year__school=self.school, is_active=True).order_by("-start_date").first()
                if term:
                    qs = qs.filter(academic_term=term)
                else:
                    term = qs.select_related("academic_term").order_by("-academic_term__end_date").values_list("academic_term_id", flat=True).first()
                    if term:
                        qs = qs.filter(academic_term_id=term)
                qs = qs.select_related("teacher__user", "academic_term").order_by("-workload_percentage")
                # Workload snapshots are maintained by timetable generation. If they
                # have not been materialized, derive a transparent estimate from the
                # currently published timetable rather than returning a false zero.
                if not qs.exists():
                    from academics.models import TimetableEntry
                    entries = TimetableEntry.objects.filter(
                        timetable__school=self.school, timetable__is_published=True
                    )
                    if term:
                        entries = entries.filter(timetable__academic_term=term)
                    rows = list(entries.values(
                        "teacher_id", "teacher__user__first_name", "teacher__user__last_name",
                        "teacher__user__username"
                    ).annotate(periods=Count("id")).order_by("-periods"))
                    max_periods = 25
                    computed = []
                    for row in rows:
                        name = (f"{row.get('teacher__user__first_name') or ''} "
                                f"{row.get('teacher__user__last_name') or ''}").strip() or row.get("teacher__user__username") or "Teacher"
                        percentage = (row["periods"] / max_periods) * 100
                        computed.append({"name": name, "periods": row["periods"], "percentage": percentage,
                                         "overloaded": percentage > 100})
                    all_computed = list(computed)
                    if "overload" in q:
                        computed = [r for r in all_computed if r["overloaded"]]
                    if any(x in q for x in ("who", "which", "list", "show", "names")):
                        lines = ["## Teacher Workload", "", "*Estimated from entries in the published timetable; 25 periods is the model's default weekly maximum.*", ""]
                        lines.extend(f"- **{r['name']}** — {r['percentage']:.1f}% of default maximum; {r['periods']} periods" + (" — **Overloaded**" if r["overloaded"] else "") for r in computed[:MAX_LIST])
                        if not computed and rows and "overload" in q:
                            lines.append(f"No teacher exceeds the default 25-period weekly maximum. Workload was estimated for {len(all_computed)} teacher(s) from {sum(r['periods'] for r in all_computed)} published timetable entries.")
                        elif not computed:
                            lines.append("No published timetable entries or workload records were found for the selected term. I cannot verify overloaded teachers.")
                        return {"answer": "\n".join(lines), "data": {"count": len(computed), "teachers_with_entries": len(all_computed), "basis": "published_timetable_estimate", "source_model": "academics.TimetableEntry", "selected_term": getattr(term, "name", None) if not isinstance(term, (str, int)) else str(term), "published_entry_count": sum(r["periods"] for r in all_computed), "default_max_periods": max_periods}, **self.meta()}
                    avg = (sum(r["percentage"] for r in computed) / len(computed)) if computed else None
                    overloaded_count = sum(1 for r in computed if r["overloaded"])
                    return {"answer": f"Workload estimates from the published timetable: **{len(computed):,} teachers**; **{overloaded_count:,} overloaded**; average **{avg:.1f}%** of the default 25-period weekly maximum." if computed else "No workload records or published timetable entries are available. I cannot verify the average teacher workload.",
                            "data": {"records": len(computed), "overloaded": overloaded_count, "average_workload_percentage": avg, "basis": "published_timetable_estimate", "source_model": "academics.TimetableEntry", "published_entry_count": sum(r["periods"] for r in computed), "default_max_periods": max_periods}, **self.meta()}
                if "overload" in q:
                    qs = qs.filter(is_overloaded=True)
                count = qs.count()
                if any(x in q for x in ("who", "which", "list", "show", "names")):
                    lines = ["## Teacher Workload", ""]
                    for row in qs[:MAX_LIST]:
                        name = row.teacher.user.get_full_name().strip() or row.teacher.user.username
                        lines.append(f"- **{name}** — {row.workload_percentage:.1f}% of maximum; {row.total_periods} periods (maximum {row.max_periods})" + (" — **Overloaded**" if row.is_overloaded else ""))
                    if not count:
                        lines.append("No teachers are marked overloaded in the selected term's workload records.")
                    return {"answer": "\n".join(lines), "data": {"count": count, "term": getattr(getattr(qs.first(), "academic_term", None), "name", None), "source_model": "academics.TeacherWorkload", "evidence_records": count}, **self.meta()}
                average = qs.aggregate(v=Avg("workload_percentage"))["v"]
                overloaded = qs.filter(is_overloaded=True).count()
                return {"answer": f"Teacher workload records: **{count:,}**; overloaded teachers: **{overloaded:,}**; average workload: **{float(average or 0):.1f}%**.",
                        "data": {"records": count, "overloaded": overloaded, "average_workload_percentage": float(average) if average is not None else None, "source_model": "academics.TeacherWorkload", "evidence_records": count}, **self.meta()}

            if timetable:
                from academics.models import Timetable
                all_qs = Timetable.objects.filter(school=self.school)
                published_qs = all_qs.filter(is_published=True)
                published = published_qs.count()
                conflict_question = "conflict" in q
                if conflict_question:
                    # Conflicts belong to a timetable generation, not additive
                    # school-wide events. Prefer the published version; otherwise
                    # report only the latest generated version.
                    qs = published_qs if published else all_qs.order_by("-generated_at")[:1]
                    scope_label = "published timetable" if published else "latest generated timetable"
                elif "published" in q or "current" in q:
                    qs = published_qs
                    scope_label = "published timetables"
                else:
                    qs = all_qs
                    scope_label = "all timetable records"
                count = qs.count()
                totals = qs.aggregate(hard=Sum("hard_conflicts"), soft=Sum("soft_conflicts"))
                hard, soft = totals["hard"] or 0, totals["soft"] or 0
                from academics.models import TimetableEntry
                selected_entry_count = TimetableEntry.objects.filter(timetable__in=qs.values("pk")).count() if count else 0
                selected_terms = list(qs.values_list("academic_term__name", flat=True).distinct()) if count else []
                if conflict_question:
                    answer = f"Recorded conflicts for the **{scope_label}**: **{hard:,} hard** and **{soft:,} soft**."
                else:
                    answer = f"The school has **{count:,} {scope_label}**, including **{published:,} published timetable(s)**."
                return {"answer": answer,
                        "data": {"timetables": count, "published": published, "hard_conflicts": hard, "soft_conflicts": soft, "conflict_scope": scope_label, "timetable_entry_count": selected_entry_count, "terms": selected_terms, "source_model": "academics.Timetable", "conflict_fields": ["hard_conflicts", "soft_conflicts"]}, **self.meta()}

            if promotion:
                from academics.models import StudentPromotion
                qs = StudentPromotion.objects.filter(school=self.school, student__school=self.school)
                if self.allowed_students is not None:
                    qs = qs.filter(student__in=self.allowed_students.values("pk"))
                status_map = {"promoted": "PROMOTED", "conditional": "CONDITIONAL", "repeated": "REPEATED", "pending": "PENDING", "expelled": "EXPELLED", "transferred": "TRANSFERRED"}
                selected = next((v for k, v in status_map.items() if k in q), None)
                if selected:
                    qs = qs.filter(status=selected)
                base_qs = StudentPromotion.objects.filter(school=self.school, student__school=self.school)
                if self.allowed_students is not None:
                    base_qs = base_qs.filter(student__in=self.allowed_students.values("pk"))
                counts = {status: base_qs.filter(status=status).count() for status in status_map.values()}
                count = qs.count()
                average = qs.aggregate(v=Avg("overall_average"))["v"] if count else None
                avg_text = f"{float(average):.2f}%" if average is not None else "Unavailable (no matching promotion scores recorded)"
                summary = (f"**{count:,} promotion record(s)** match your request. Average recorded overall score: **{avg_text}**." if count else
                           "**No student promotion decisions have been recorded** in the authorized school scope for this query. This does not prove that no students advanced or repeated outside the recorded promotion process.")
                total_records = base_qs.count()
                return {"answer": "## Student Promotion Records\n\n" + summary + "\n\n" +
                        "\n".join(f"- {status.title()}: **{number:,}**" for status, number in counts.items()) +
                        f"\n\n**Evidence source:** academics.StudentPromotion; {total_records:,} total promotion record(s) in the authorized scope.",
                        "data": {"matching_records": count, "total_promotion_records": total_records, "average_overall": float(average) if average is not None else None, "status_counts": counts, "source_model": "academics.StudentPromotion"}, **self.meta()}

            if inventory:
                from finance.models import LogisticItem
                qs = LogisticItem.objects.filter(school=self.school)
                if "inactive" in q:
                    qs = qs.filter(is_active=False)
                else:
                    # Ordinary stock questions describe the current usable
                    # catalog, not archived/inactive items.
                    qs = qs.filter(is_active=True)
                if any(x in q for x in ("out of stock", "zero stock", "no stock")):
                    qs = qs.filter(quantity_in_stock=0)
                count = qs.count()
                total_units = qs.aggregate(v=Sum("quantity_in_stock"))["v"] or 0
                active_catalog = LogisticItem.objects.filter(school=self.school, is_active=True)
                zero_stock_count = active_catalog.filter(quantity_in_stock=0).count()
                if any(x in q for x in ("which", "list", "show", "names", "out of stock")):
                    lines = ["## Inventory Items", ""]
                    for item in qs.order_by("name")[:MAX_LIST]:
                        lines.append(f"- **{item.name}** — {item.quantity_in_stock:,} in stock")
                    if not count:
                        lines.append("No active inventory items currently match the out-of-stock filter (quantity_in_stock = 0)." if any(x in q for x in ("out of stock", "zero stock", "no stock")) else "No inventory items match this request.")
                    lines.append(f"\n**Evidence:** {active_catalog.count():,} active catalog item(s); {zero_stock_count:,} active item(s) have quantity_in_stock = 0. Source: finance.LogisticItem.")
                    return {"answer": "\n".join(lines), "data": {"items": count, "units_in_stock": total_units, "active_catalog_count": active_catalog.count(), "zero_stock_count": zero_stock_count, "stock_field": "quantity_in_stock", "source_model": "finance.LogisticItem"}, **self.meta()}
                return {"answer": f"There are **{count:,} inventory items** with **{total_units:,} total units** in stock.",
                        "data": {"items": count, "units_in_stock": total_units, "active_catalog_count": active_catalog.count(), "zero_stock_count": zero_stock_count, "source_model": "finance.LogisticItem"}, **self.meta()}

            if transport:
                from finance.models import TransportRoute, StudentTransportSubscription
                routes = TransportRoute.objects.filter(school=self.school)
                subscriptions = StudentTransportSubscription.objects.filter(student__school=self.school, route__school=self.school)
                if "inactive" in q:
                    routes = routes.filter(is_active=False)
                    subscriptions = subscriptions.filter(is_active=False)
                elif "active" in q or "currently" in q:
                    routes = routes.filter(is_active=True)
                    subscriptions = subscriptions.filter(is_active=True)
                route_count, subscription_count = routes.count(), subscriptions.count()
                all_routes = TransportRoute.objects.filter(school=self.school)
                all_subscriptions = StudentTransportSubscription.objects.filter(student__school=self.school, route__school=self.school)
                return {"answer": f"The school has **{route_count:,} matching transport routes** and **{subscription_count:,} matching student transport subscriptions**.\n\n**Evidence:** {all_routes.count():,} route record(s) in total ({all_routes.filter(is_active=False).count():,} inactive); {all_subscriptions.count():,} subscription record(s) in total ({all_subscriptions.filter(is_active=False).count():,} inactive). Sources: finance.TransportRoute and finance.StudentTransportSubscription.",
                        "data": {"routes": route_count, "subscriptions": subscription_count, "all_routes": all_routes.count(), "all_subscriptions": all_subscriptions.count(), "source_models": ["finance.TransportRoute", "finance.StudentTransportSubscription"]}, **self.meta()}
        except Exception:
            logger.exception("Operational intelligence failed")
            return {"answer": "I could not safely verify the requested operational information. No unverified answer was provided.", **self.meta("database_error")}
        return None

    # ------------------------------------------------------------------
    # Explicit question planning and domain-first routing
    # ------------------------------------------------------------------
    @classmethod
    def plan_question(cls, question):
        """Classify a factual question before any database handler executes.

        This is deliberately deterministic: it does not infer a metric or
        database field from an LLM response. The plan only selects the safest
        existing ORM handler and records the user's requested operation/period.
        """
        q = cls.norm(question)
        if not q:
            return {"domain": None, "action": "unknown", "period": "unspecified", "ranking": False}

        ranking = any(x in q for x in (
            "best", "top", "highest", "lowest", "rank", "ranking",
            "outstanding", "most effective", "performer", "performing",
        ))
        if any(x in q for x in ("average", "mean score", "average score")):
            action = "average"
        elif any(x in q for x in ("how much", "total amount", "sum of", "total collected", "total paid")):
            action = "sum"
        elif ranking:
            action = "rank"
        elif any(x in q for x in ("how many", "number of", "count", "total")):
            action = "count"
        elif any(x in q for x in ("list", "show", "which", "who", "names")):
            action = "list"
        else:
            action = "detail"

        if any(x in q for x in ("yesterday", "last day")):
            period = "yesterday"
        elif any(x in q for x in ("today", "this morning")):
            period = "today"
        elif any(x in q for x in ("this term", "current term", "term to date", "active term")):
            period = "current_term"
        elif any(x in q for x in ("this year", "current year", "academic year to date")):
            period = "current_year"
        elif any(x in q for x in ("last term", "previous term", "previous academic term")):
            period = "previous_term"
        else:
            period = "unspecified"

        staff = any(x in q for x in ("staff", "employee", "employees", "personnel", "teacher", "teachers"))
        student = any(x in q for x in ("student", "students", "learner", "learners", "pupil", "pupils"))
        attendance = any(x in q for x in (
            "attendance", "absent", "absence", "present", "late", "punctual",
            "punctuality", "attendance rate", "face recognition", "facial recognition",
            "face-recognition", "face attendance",
        ))
        finance = any(x in q for x in (
            "fee", "fees", "finance", "financial", "invoice", "invoices",
            "payment", "payments", "collected", "collection", "outstanding balance",
            "owing", "receivable",
        )) or bool(re.search(r"\bowe\b", q))
        academics = any(x in q for x in (
            "assessment", "assessments", "exam", "exams", "marks", "scores",
            "terminal result", "terminal results", "report card", "report cards",
            "academic performance", "subject average", "subject performance",
            "class performance", "class average", "pass rate", "failure rate",
            "failed subjects", "below 40", "below forty", "declining performance",
            "performance trend", "weakest subject", "strongest subject",
            "best subject", "worst subject", "overall average", "school average",
            "below 40", "below forty", "failed subjects", "subjects below",
            "best class", "worst class", "top class", "class ranking",
            "declined scores", "scores declined", "dropped scores",
            "academic risk", "at risk academically", "early intervention",
            "students at risk", "student at risk", "struggling academically",
            "students struggling", "falling behind", "academic support",
            "failed two or more", "failed three or more", "three or more failed subjects",
            "failing in multiple subjects", "remedial support", "remedial classes", "academic warning",
            "declining grades", "grades declined", "grades have declined", "grade decline",
            "students whose grades declined", "students with declining grades",
            "below 50", "below 60", "poor academic performance",
            "low performing students", "low-performing students", "academic intervention",
        )) or ("subject" in q and any(x in q for x in ("average", "lowest", "highest", "performance", "strongest", "weakest", "best", "worst"))) or ("class" in q and any(x in q for x in ("average", "performance", "lowest", "highest", "best", "worst", "top", "compare", "rank"))) or ("failed" in q and "subject" in q)
        library = any(x in q for x in ("book", "books", "library", "borrow", "borrowing", "overdue loan"))
        admissions = any(x in q for x in ("admission", "admissions", "application", "applications", "applicant", "applicants"))
        leave = any(x in q for x in ("leave", "time off", "annual leave", "sick leave"))
        online_exams = any(x in q for x in ("online exam", "online exams", "online examination", "online examinations", "exam attempt", "exam attempts", "online test", "online tests"))
        lesson_plans = any(x in q for x in ("lesson plan", "lesson plans", "lesson note", "lesson notes", "weekly plan", "weekly plans"))
        operations = any(x in q for x in (
            "payroll", "payslip", "pay slip", "salary", "salaries", "wages",
            "workload", "teacher workload", "overloaded", "timetable", "promotion", "promotions",
            "promoted", "repeated", "inventory", "stock", "logistics", "transport route", "transport subscription",
            "school bus", "bus route",
        ))

        # Resolve the most specific entity first. A status word such as
        # "absent" must not be mistaken for a request for the student directory.
        if staff and attendance and ranking:
            domain = "staff_attendance_ranking"
        elif staff and ranking:
            domain = "staff_performance"
        elif student and ranking:
            domain = "student_academic_ranking"
        elif attendance:
            domain = "attendance"
        elif online_exams:
            domain = "online_exams"
        elif lesson_plans:
            domain = "lesson_plans"
        elif finance:
            domain = "finance"
        elif academics:
            domain = "academics"
        elif library:
            domain = "library"
        elif admissions:
            domain = "admissions"
        elif leave:
            domain = "leave"
        elif operations:
            domain = "operations"
        elif staff:
            domain = "staff"
        elif student:
            domain = "students"
        else:
            domain = "generic"

        return {"domain": domain, "action": action, "period": period, "ranking": ranking}

    def answer(self, question):
        q = self.norm(question)
        if not q:
            return None

        plan = self.plan_question(q)
        # Each domain starts with its most specific handler. Remaining handlers
        # are retained as a controlled fallback, but generic entity matching is
        # always last so a directory/count response cannot hijack a metric query.
        routes = {
            "staff_attendance_ranking": (self.staff_merit_question,),
            "staff_performance": (self.staff_merit_question,),
            "student_academic_ranking": (self.student_merit_ranking,),
            "attendance": (self.attendance,),
            "online_exams": (self.online_exams,),
            "lesson_plans": (self.lesson_plan_metrics,),
            "finance": (self.finance_summary,),
            "academics": (self.academic_summary,),
            "library": (self.library,),
            "admissions": (self.admissions,),
            "leave": (self.leave_question,),
            "operations": (self.operational_metrics,),
            "staff": (self.staff_question,),
            "students": (self.student,),
            "generic": (),
        }
        ordered = [self.school_context]
        ordered.extend(routes.get(plan["domain"], ()))

        # Add the remaining specialist handlers once, preserving existing
        # functionality for mixed or less common school questions.
        fallback = (
            self.student_merit_ranking, self.staff_merit_question,
            self.operational_metrics, self.leave_question, self.staff_question, self.attendance,
            self.online_exams, self.lesson_plan_metrics, self.student, self.finance_summary, self.academic_summary,
            self.library, self.admissions,
        )
        seen = {getattr(fn, "__name__", str(fn)) for fn in ordered}
        for handler in fallback:
            name = getattr(handler, "__name__", str(handler))
            if name not in seen:
                ordered.append(handler)
                seen.add(name)
        ordered.append(self.generic_entity)

        for handler in ordered:
            try:
                result = handler(q)
                if result is not None:
                    # Attach a compact, auditable intent plan to structured data.
                    if isinstance(result, dict):
                        result.setdefault("intent", plan)
                    return result
            except Exception:
                logger.exception("Full V4 database handler failed: %s", getattr(handler, "__name__", handler))
                return {"answer": "I could not safely verify that information from the school database. No unverified answer was provided.", **self.meta("database_error"), "intent": plan}
        return None

    def looks_like_school_fact(self, q):
        q = self.norm(q)
        entities = (
            "school", "student", "students", "staff", "teacher", "employee", "class", "subject", "attendance",
            "fee", "fees", "invoice", "payment", "finance", "payroll", "salary", "leave", "result", "results",
            "exam", "assessment", "book", "library", "announcement", "department", "academic", "timetable",
            "promotion", "transport", "inventory", "stock", "allowance", "deduction", "payslip", "receipt",
            "declining grades", "grades declined", "grade decline", "academic risk",
            "borrowing", "absence", "workload", "room", "term", "year",
            "online exam", "online examination", "exam attempt", "lesson plan", "lesson note", "weekly plan",
            "payroll", "payslip", "salary", "salaries", "wages", "promotion",
            "inventory", "stock", "logistics", "transport", "bus route",
        )
        actions = (
            "how many", "how much", "who", "which", "what is", "what are", "show", "list", "give me", "tell me",
            "total", "count", "number of", "available", "current", "today", "this term", "this year", "outstanding",
            "balance", "owing", "owe", "summary", "active", "inactive",
        )
        return any(e in q for e in entities) and any(a in q for a in actions)
