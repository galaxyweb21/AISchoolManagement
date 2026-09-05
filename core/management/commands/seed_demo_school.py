"""Create a safe, repeatable fictional school dataset for demonstrations/UAT.

Usage:
    python manage.py seed_demo_school
    python manage.py seed_demo_school --reset
    python manage.py seed_demo_school --password 'YourDemoPassword'

Only the school identified by DEMO_SUBDOMAIN is touched. --reset deletes that
one demo school and its related records before rebuilding it.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from school.models import School, AcademicYear, AcademicTerm
from students.models import Student, GradeLevel, StudentEnrollmentType
from academics.models import Subject, SchoolClass, ClassSubject, TeacherAssignment, TeacherClassAssignment
from staff.models import (
    Department, StaffGrade, StaffProfile, Teacher,
    SalaryStructure, PayrollPeriod, PayrollRun, Payslip,
    LeaveType, StaffGradeLeavePolicy, LeaveRequest,
)
from attendance.models import Attendance
from assessments.models import Assessment, Grade, TerminalResult
from finance.models import FeeCategory, FeeStructure, FeeStructureItem, Invoice, Payment
from finance.services.ledger import create_payment_ledger_entry
from library.models import BookCategory, Book, BookBorrowing
from communication.models import Announcement, NotificationLog, NotificationCategory, NotificationChannel, NotificationStatus
from ai_engine.models import AIConfiguration, AIActivity, ReportCardBatch, ReportCard
from ai_engine.services.report_card_engine import ReportCardEngine


DEMO_SUBDOMAIN = "eduai-demo"
DEMO_SCHOOL = "EduAI Demonstration School"
DEMO_PASSWORD = "Demo@2026!"


class Command(BaseCommand):
    help = "Seed a realistic fictional school dataset for controlled demonstrations and UAT."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete and rebuild only the EduAI demo school.")
        parser.add_argument("--password", default=DEMO_PASSWORD, help="Password assigned to demo accounts.")
        parser.add_argument("--students", type=int, default=18, help="Number of demo students (default: 18).")

    def handle(self, *args, **options):
        if options["students"] < 6:
            raise CommandError("Use at least 6 students so the demo has meaningful class/ranking data.")
        password = options["password"]
        if len(password) < 10:
            raise CommandError("Demo password must be at least 10 characters.")

        with transaction.atomic():
            if options["reset"]:
                School.objects.filter(subdomain=DEMO_SUBDOMAIN).delete()

            school, _ = School.objects.get_or_create(
                subdomain=DEMO_SUBDOMAIN,
                defaults={
                    "name": DEMO_SCHOOL,
                    "address": "Accra, Greater Accra Region, Ghana",
                    "contact_email": "demo@eduai.school",
                    "phone_number": "+233 30 200 0000",
                    "is_active": True,
                },
            )
            school.name = DEMO_SCHOOL
            school.address = "Accra, Greater Accra Region, Ghana"
            school.contact_email = "demo@eduai.school"
            school.phone_number = "+233 30 200 0000"
            school.is_active = True
            school.save()

            # Core reference data.
            self._call_seeds()
            year, term = self._academic_calendar(school)
            admin = self._user(school, "demo_admin", "Demo", "Administrator", "SCHOOL_ADMIN", password)
            bursar = self._user(school, "demo_bursar", "Demo", "Bursar", "BURSAR", password)
            registrar = self._user(school, "demo_registrar", "Demo", "Registrar", "REGISTRAR", password)
            hod = self._user(school, "demo_hod", "Demo", "Head of Department", "HOD", password)
            secretary = self._user(school, "demo_secretary", "Demo", "Secretary", "SECRETARY", password)
            librarian = self._user(school, "demo_librarian", "Demo", "Librarian", "SCHOOL_ADMIN", password)
            parent_users = [
                self._user(school, f"demo_parent{i}", "Demo Parent", str(i), "PARENT", password)
                for i in range(1, 4)
            ]

            grades = {g.name: g for g in GradeLevel.objects.filter(school=school)}
            classes = self._classes(school, grades)
            departments, staff_grade = self._staff_reference(school)
            teachers = self._teachers(school, admin, departments, staff_grade, password)
            classes["Basic 4"].homeroom_teacher = teachers[0]["teacher"]
            classes["Basic 4"].save(update_fields=["homeroom_teacher"])
            classes["Basic 5"].homeroom_teacher = teachers[1]["teacher"]
            classes["Basic 5"].save(update_fields=["homeroom_teacher"])
            classes["JHS 1"].homeroom_teacher = teachers[2]["teacher"]
            classes["JHS 1"].save(update_fields=["homeroom_teacher"])

            subjects = self._subjects(school)
            self._assign_teachers(school, admin, classes, subjects, teachers)
            students = self._students(school, classes, parent_users, options["students"], password)
            self._attendance(school, admin, students)
            self._assessments(school, term, admin, students, classes, subjects)
            self._finance(school, term, admin, bursar, students, classes)
            self._hr_and_leave(school, admin, teachers, staff_grade)
            self._payroll(school, admin, teachers)
            self._library(school, students, librarian)
            self._communication(school, admin, parent_users, students)
            self._ai(school, admin, term, students)
            self._report_cards(school, admin, term, students)

        self.stdout.write(self.style.SUCCESS("\nEduAI demo school is ready."))
        self.stdout.write("School: EduAI Demonstration School (eduai-demo)")
        self.stdout.write(f"Demo password: {password}")
        self.stdout.write("Accounts:")
        for username in ["demo_admin", "demo_bursar", "demo_registrar", "demo_hod", "demo_secretary", "demo_librarian", "demo_parent1", "demo_parent2", "demo_parent3", "demo_student01"]:
            self.stdout.write(f"  - {username}")
        self.stdout.write("\nRun: python manage.py verify_demo_school")

    def _call_seeds(self):
        from django.core.management import call_command
        call_command("seed_permissions", verbosity=0)
        call_command("seed_roles", verbosity=0)

    def _academic_calendar(self, school):
        year, _ = AcademicYear.objects.update_or_create(
            school=school,
            name="2026/2027 Academic Year",
            defaults={"start_date": date(2026, 9, 1), "end_date": date(2027, 7, 31), "is_active": True},
        )
        AcademicYear.objects.filter(school=school).exclude(pk=year.pk).update(is_active=False)
        term, _ = AcademicTerm.objects.update_or_create(
            academic_year=year,
            name="First Term",
            defaults={"start_date": date(2026, 9, 1), "end_date": date(2026, 12, 18), "is_active": True},
        )
        AcademicTerm.objects.filter(academic_year=year).exclude(pk=term.pk).update(is_active=False)
        return year, term

    def _user(self, school, username, first, last, role, password):
        user, _ = User.objects.get_or_create(username=username, defaults={"school": school, "role": role})
        user.school = school
        user.role = role
        user.first_name = first
        user.last_name = last
        user.email = f"{username}@eduai.school"
        user.phone_number = "+233200000000"
        user.default_password = password
        user.set_password(password)
        user.is_active = True

        # The primary demo administrator also needs access to Django's built-in
        # admin site. Keeping the same account avoids creating a second set of
        # credentials and remains safe because this command only seeds the
        # fictional EduAI demonstration environment.
        if username == "demo_admin":
            user.is_staff = True
            user.is_superuser = True

        user.save()
        return user

    def _classes(self, school, grades):
        wanted = ["Basic 4", "Basic 5", "JHS 1"]
        result = {}
        for name in wanted:
            grade = grades.get(name)
            if not grade:
                raise CommandError(f"Required GES grade level '{name}' was not seeded.")
            cls, _ = SchoolClass.objects.get_or_create(school=school, grade_level=grade, name=name)
            result[name] = cls
        return result

    def _staff_reference(self, school):
        departments = {}
        for name, code in [("Administration", "ADMIN"), ("Mathematics & Science", "MATH"), ("Languages", "LANG")]:
            departments[code], _ = Department.objects.get_or_create(school=school, code=code, defaults={"name": name})
        grade, _ = StaffGrade.objects.get_or_create(
            school=school, code="ST1",
            defaults={"name": "Senior Teacher", "grade_type": "TEACHING", "level": 5, "base_salary": Decimal("5200.00")},
        )
        return departments, grade

    def _teachers(self, school, admin, departments, grade, password):
        data = [
            ("demo_teacher1", "Ama", "Mensah", "MATHEMATICS", "TCH-001", "MATH"),
            ("demo_teacher2", "Kojo", "Owusu", "SCIENCE", "TCH-002", "MATH"),
            ("demo_teacher3", "Esi", "Asare", "ENGLISH", "TCH-003", "LANG"),
            ("demo_teacher4", "Yaw", "Boateng", "SOCIAL", "TCH-004", "LANG"),
            ("demo_teacher5", "Akua", "Ofori", "ICT", "TCH-005", "MATH"),
        ]
        out = []
        for username, first, last, dept, number, dept_code in data:
            user = self._user(school, username, first, last, "TEACHER", password)
            profile, _ = StaffProfile.objects.get_or_create(school=school, user=user, defaults={"staff_id": number})
            profile.staff_position = "TEACHER"
            profile.staff_grade = grade
            profile.department = departments[dept_code]
            profile.staff_id = number
            profile.default_password = password
            profile.has_changed_password = False
            profile.save()
            teacher, _ = Teacher.objects.get_or_create(school=school, user=user, defaults={"staff_number": number, "department": dept})
            teacher.staff_number = number
            teacher.department = dept
            teacher.is_active = True
            teacher.save()
            out.append({"user": user, "profile": profile, "teacher": teacher, "department": dept})
        return out

    def _subjects(self, school):
        names = [
            ("Mathematics", "MATH"), ("English Language", "ENG"),
            ("Integrated Science", "SCI"), ("Social Studies", "SOC"), ("Computing", "ICT"),
        ]
        result = {}
        for name, code in names:
            subject, _ = Subject.objects.get_or_create(school=school, name=name)
            result[code] = subject
        return result

    def _assign_teachers(self, school, admin, classes, subjects, teachers):
        mapping = [
            ("MATH", 0), ("SCI", 1), ("ENG", 2), ("SOC", 3), ("ICT", 4),
        ]
        for cls in classes.values():
            for code, idx in mapping:
                subject = subjects[code]
                ClassSubject.objects.update_or_create(
                    school_class=cls, subject=subject,
                    defaults={"school": school, "is_core": code != "ICT", "periods_per_week": 4, "is_active": True},
                )
                TeacherAssignment.objects.update_or_create(
                    teacher=teachers[idx]["teacher"], school_class=cls, subject=subject,
                    defaults={"school": school, "periods_per_week": 4, "is_primary": True, "is_active": True, "assigned_by": admin},
                )
                teachers[idx]["teacher"].subjects.add(subject)
            TeacherClassAssignment.objects.update_or_create(
                school_class=cls, teacher=cls.homeroom_teacher,
                defaults={"school": school, "is_active": True, "assigned_by": admin},
            )

    def _students(self, school, classes, parents, count, password):
        enrollment_type = StudentEnrollmentType.objects.get(school=school, code="RETURNING")
        class_list = list(classes.values())
        first_names = ["Kwame", "Abena", "Kofi", "Adwoa", "Yaw", "Akosua", "Nana", "Efua", "Kwadwo", "Ama"]
        last_names = ["Mensah", "Owusu", "Boateng", "Asare", "Ofori", "Addo", "Darko", "Appiah"]
        result = []
        for i in range(1, count + 1):
            username = f"demo_student{i:02d}"
            user, _ = User.objects.get_or_create(username=username, defaults={"school": school, "role": "STUDENT"})
            user.school = school
            user.role = "STUDENT"
            user.first_name = first_names[(i - 1) % len(first_names)]
            user.last_name = last_names[(i - 1) % len(last_names)]
            user.email = f"{username}@eduai.school"
            user.default_password = password
            user.set_password(password)
            user.save()
            cls = class_list[(i - 1) % len(class_list)]
            student, _ = Student.objects.get_or_create(user=user, defaults={"school": school, "date_of_birth": date(2011 + ((i - 1) % 5), 2 + ((i - 1) % 9), 5 + ((i - 1) % 20)), "grade_level": cls.grade_level, "school_class": cls})
            student.school = school
            student.grade_level = cls.grade_level
            student.school_class = cls
            student.enrollment_type = enrollment_type
            student.is_new_student = False
            student.parent = parents[(i - 1) % len(parents)]
            student.address = "Accra, Ghana"
            student.contact_phone = "+233 24 000 0000"
            student.default_password = password
            student.is_active = True
            student.save()
            result.append(student)
        return result

    def _attendance(self, school, marker, students):
        today = timezone.localdate()
        for offset in range(10):
            day = today - timedelta(days=offset)
            if day.weekday() >= 5:
                continue
            for idx, student in enumerate(students):
                status = "ABSENT" if (idx + offset) % 17 == 0 else ("LATE" if (idx + offset) % 11 == 0 else "PRESENT")
                Attendance.objects.update_or_create(
                    school=school, student=student, date=day,
                    defaults={"status": status, "marked_by": marker, "remarks": "Demo attendance record"},
                )

    def _assessments(self, school, term, teacher, students, classes, subjects):
        subject_items = list(subjects.items())
        for code, subject in subject_items:
            for cls in classes.values():
                ca, _ = Assessment.objects.get_or_create(
                    school=school, school_class=cls, academic_term=term,
                    title=f"{subject.name} Continuous Assessment", subject=subject.name,
                    assessment_type="ASSIGNMENT", score_component="CA", defaults={"max_score": 30},
                )
                ex, _ = Assessment.objects.get_or_create(
                    school=school, school_class=cls, academic_term=term,
                    title=f"{subject.name} End of Term Examination", subject=subject.name,
                    assessment_type="EXAM", score_component="EXAM", defaults={"max_score": 70},
                )
                for idx, student in enumerate([s for s in students if s.school_class_id == cls.id]):
                    ca_score = Decimal(str(18 + ((idx * 3 + len(code)) % 12)))
                    ex_score = Decimal(str(42 + ((idx * 5 + len(code)) % 28)))
                    Grade.objects.update_or_create(assessment=ca, student=student, defaults={"score_achieved": ca_score, "graded_by": teacher})
                    Grade.objects.update_or_create(assessment=ex, student=student, defaults={"score_achieved": ex_score, "graded_by": teacher})
                    tr, _ = TerminalResult.objects.get_or_create(
                        school=school, academic_term=term, school_class=cls, student=student, subject=subject.name,
                        defaults={"class_score": ca_score, "exam_score": ex_score, "entered_by": teacher},
                    )
                    tr.class_score = ca_score
                    tr.exam_score = ex_score
                    tr.entry_mode = "WEIGHTED"
                    tr.status = "COMPLETE"
                    tr.entered_by = teacher
                    tr.teacher_note = "Demo terminal result."
                    tr.calculate()
                    tr.save()

    def _finance(self, school, term, admin, bursar, students, classes):
        categories = {}
        for name, typ, optional in [
            ("Tuition", "TUITION", False), ("Books & Stationery", "BOOKS", False),
            ("ICT & Digital Learning", "OTHER", False), ("Transport", "TRANSPORT", True),
        ]:
            categories[name], _ = FeeCategory.objects.get_or_create(
                school=school, name=name,
                defaults={"category_type": typ, "is_optional": optional, "is_recurring": True},
            )
        amounts = {"Tuition": Decimal("2500.00"), "Books & Stationery": Decimal("350.00"), "ICT & Digital Learning": Decimal("250.00"), "Transport": Decimal("600.00")}
        for cls in classes.values():
            fs, _ = FeeStructure.objects.update_or_create(
                school=school, academic_term=term, school_class=cls,
                defaults={"is_published": True},
            )
            for name, amount in amounts.items():
                FeeStructureItem.objects.update_or_create(fee_structure=fs, fee_category=categories[name], defaults={"amount": amount})
        invoices = list(Invoice.objects.filter(school=school, academic_term=term, student__in=students).order_by("created_at"))
        # Students created after fee structures automatically receive invoices. If a deployment has signals disabled,
        # create a clean invoice directly so the demo still has finance data.
        for student in students:
            invoice = Invoice.objects.filter(school=school, student=student, academic_term=term).first()
            if not invoice:
                invoice = Invoice.objects.create(school=school, student=student, academic_term=term, due_date=term.end_date, status="UNPAID")
                for name, amount in amounts.items():
                    from finance.models import InvoiceLineItem
                    InvoiceLineItem.objects.create(invoice=invoice, fee_category=categories[name], description=name, amount=amount)
                from finance.services.ledger import create_invoice_ledger_entries
                create_invoice_ledger_entries(invoice, created_by=admin)
            invoices.append(invoice)
        invoices = list(dict.fromkeys(invoices))
        if invoices:
            for invoice in invoices[:6]:
                if not invoice.payments.filter(status="CONFIRMED").exists():
                    amount = Decimal("1800.00") if invoice.student_id in {s.id for s in students[:3]} else Decimal("3100.00")
                    if amount > invoice.total_amount:
                        amount = invoice.total_amount
                    payment = Payment.objects.create(invoice=invoice, amount=amount, method="MOBILE_MONEY", status="CONFIRMED", recorded_by=bursar, reference_number="DEMO-MOMO")
                    create_payment_ledger_entry(payment, created_by=bursar)
                    invoice.refresh_status()

    def _hr_and_leave(self, school, admin, teachers, grade):
        annual, _ = LeaveType.objects.get_or_create(school=school, code="ANNUAL", defaults={"name": "Annual Leave", "category": "ANNUAL", "default_days": 21, "requires_approval": True})
        sick, _ = LeaveType.objects.get_or_create(school=school, code="SICK", defaults={"name": "Sick Leave", "category": "SICK", "default_days": 10, "requires_approval": True})
        for leave in (annual, sick):
            StaffGradeLeavePolicy.objects.update_or_create(
                school=school, staff_grade=grade, leave_type=leave,
                defaults={"entitlement_days": Decimal("21.0" if leave is annual else "10.0"), "is_paid": True, "allow_carryover": leave is annual, "max_carryover_days": Decimal("5.0" if leave is annual else "0.0")},
            )
        staff = teachers[0]["profile"]
        LeaveRequest.objects.update_or_create(
            school=school, staff=staff, leave_type=annual,
            start_date=date(2026, 10, 12), end_date=date(2026, 10, 14),
            defaults={"requested_days": Decimal("3.0"), "status": "PENDING", "reason": "Personal leave (demo workflow)", "contact_number": "+233 24 000 0000"},
        )

    def _payroll(self, school, admin, teachers):
        for idx, row in enumerate(teachers):
            SalaryStructure.objects.update_or_create(
                staff=row["profile"],
                effective_date=date(2026, 9, 1),
                defaults={"school": school, "staff_grade": row["profile"].staff_grade, "basic_salary": Decimal(str(4800 + idx * 200)), "frequency": "MONTHLY"},
            )
        period, _ = PayrollPeriod.objects.get_or_create(
            school=school, period_start=date(2026, 9, 1), period_end=date(2026, 9, 30),
            defaults={"name": "September 2026 Payroll", "payment_date": date(2026, 9, 30), "status": "OPEN", "created_by": admin},
        )
        for idx, row in enumerate(teachers[:3]):
            basic = Decimal(str(4800 + idx * 200))
            run, _ = PayrollRun.objects.update_or_create(
                staff=row["profile"], payroll_period=period,
                defaults={"school": school, "basic_salary": basic, "total_allowances": Decimal("500.00"), "total_deductions": Decimal("350.00"), "gross_pay": basic + Decimal("500.00"), "net_pay": basic + Decimal("150.00"), "days_worked": 22, "status": "CALCULATED", "processed_by": admin},
            )
            Payslip.objects.update_or_create(
                payroll_run=run,
                defaults={"school": school, "earnings": {"Basic Salary": str(basic), "Teaching Allowance": "500.00"}, "deductions": {"PAYE / Other": "350.00"}, "payment_method": "Bank Transfer", "generated_by": admin},
            )

    def _library(self, school, students, librarian):
        fiction, _ = BookCategory.objects.get_or_create(school=school, name="Fiction")
        science, _ = BookCategory.objects.get_or_create(school=school, name="Science & Technology")
        books = []
        for i, (title, author, category) in enumerate([
            ("The Ghanaian Reader", "A. K. Mensah", fiction),
            ("Young Scientists", "E. Owusu", science),
            ("Computing for Schools", "K. Addo", science),
            ("African Stories for Schools", "N. Asare", fiction),
        ]):
            book, _ = Book.objects.get_or_create(school=school, title=title, author=author, defaults={"category": category, "total_copies": 10, "available_copies": 10, "shelf_location": f"A{i+1}"})
            books.append(book)
        book = books[0]
        borrowing = BookBorrowing.objects.filter(school=school, book=book, borrowed_by_student=students[0], status="ACTIVE").first()
        if not borrowing:
            borrowing = BookBorrowing.objects.create(school=school, book=book, borrowed_by_student=students[0], due_date=timezone.localdate() + timedelta(days=14), status="ACTIVE", notes="Demo borrowing")
            book.available_copies = max(0, book.available_copies - 1)
            book.status = "BORROWED" if book.available_copies < book.total_copies else "AVAILABLE"
            book.save(update_fields=["available_copies", "status"])

    def _communication(self, school, admin, parents, students):
        Announcement.objects.update_or_create(
            school=school, title="Welcome to the First Term",
            defaults={"sender": admin, "content": "Welcome to the new academic year. This announcement is part of the EduAI school demonstration.", "summary": "First-term welcome message", "audience": "ALL", "priority": "NORMAL", "publish_at": timezone.now(), "is_published": True},
        )
        for parent in parents:
            NotificationLog.objects.update_or_create(
                school=school, recipient=parent, category=NotificationCategory.ANNOUNCEMENT,
                subject="Demo school announcement",
                defaults={"sender": admin, "channel": NotificationChannel.IN_APP, "message": "A new school announcement is available.", "status": NotificationStatus.SENT},
            )

    def _ai(self, school, admin, term, students):
        AIConfiguration.objects.update_or_create(
            school=school,
            defaults={"provider": "Groq", "model_name": "openai/gpt-oss-120b", "temperature": 0.3, "max_tokens": 2048, "enable_exam_ai": True},
        )
        AIActivity.objects.create(
            school=school, activity_type="GENERAL", title="Demo AI environment initialized", description="Synthetic demo data is ready for AI School Copilot and analytics testing.", status="SUCCESS", created_by=admin, metadata={"term": str(term), "students": len(students)},
        )

    def _report_cards(self, school, admin, term, students):
        batch, _ = ReportCardBatch.objects.get_or_create(school=school, academic_term=term, status="COMPLETE", defaults={"triggered_by": admin, "students_processed": len(students)})
        if batch.triggered_by_id != admin.id:
            batch.triggered_by = admin
            batch.students_processed = len(students)
            batch.status = "COMPLETE"
            batch.save(update_fields=["triggered_by", "students_processed", "status"])
        for student in students:
            computed = ReportCardEngine.compute(student, term)
            ReportCard.objects.update_or_create(
                student=student, academic_term=term,
                defaults={
                    "school": school, "last_batch": batch,
                    "overall_average": computed["overall_average"], "overall_grade": computed["overall_grade"], "overall_remark": computed["overall_remark"],
                    "total_marks": computed["total_marks"], "total_possible": computed["total_possible"], "overall_position": computed["overall_position"], "class_size": computed["class_size"],
                    "attendance_rate": computed["attendance_rate"], "attendance_present": computed["attendance"]["present"], "attendance_absent": computed["attendance"]["absent"], "attendance_late": computed["attendance"]["late"], "attendance_total": computed["attendance"]["total"],
                    "ca_weight": computed["ca_weight"], "exam_weight": computed["exam_weight"], "subject_breakdown": computed["subject_breakdown"],
                    "teacher_comment": "Good effort this term. Continue building consistent study habits.", "headteacher_comment": "A promising term. Keep working steadily and participate actively in school life.",
                    "teacher_comment_source": "MANUAL", "headteacher_comment_source": "MANUAL", "ai_narrative": "Demo report-card narrative prepared for school testing.",
                    "is_finalized": False,
                },
            )
