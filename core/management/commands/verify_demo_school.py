from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum

from school.models import School, AcademicTerm
from accounts.models import User
from students.models import Student
from academics.models import SchoolClass, Subject
from staff.models import StaffProfile, Teacher, LeaveRequest, Payslip
from attendance.models import Attendance
from assessments.models import Assessment, Grade, TerminalResult
from finance.models import Invoice, Payment
from library.models import Book, BookBorrowing
from communication.models import Announcement
from ai_engine.models import ReportCard, AIConfiguration


class Command(BaseCommand):
    help = "Verify the EduAI fictional demo dataset and report any obvious gaps."

    def handle(self, *args, **options):
        school = School.objects.filter(subdomain="eduai-demo").first()
        if not school:
            raise CommandError("Demo school not found. Run: python manage.py seed_demo_school")
        term = AcademicTerm.objects.filter(academic_year__school=school, is_active=True).first()
        checks = [
            ("Users", User.objects.filter(school=school).count(), 8),
            ("Students", Student.objects.filter(school=school, is_active=True).count(), 6),
            ("Classes", SchoolClass.objects.filter(school=school).count(), 3),
            ("Subjects", Subject.objects.filter(school=school).count(), 5),
            ("Staff profiles", StaffProfile.objects.filter(school=school).count(), 5),
            ("Teachers", Teacher.objects.filter(school=school).count(), 5),
            ("Attendance records", Attendance.objects.filter(school=school).count(), 10),
            ("Assessments", Assessment.objects.filter(school=school, academic_term=term).count(), 6),
            ("Grades", Grade.objects.filter(assessment__school=school).count(), 6),
            ("Terminal results", TerminalResult.objects.filter(school=school, academic_term=term).count(), 6),
            ("Invoices", Invoice.objects.filter(school=school, academic_term=term).count(), 6),
            ("Payments", Payment.objects.filter(invoice__school=school).count(), 1),
            ("Books", Book.objects.filter(school=school).count(), 4),
            ("Borrowings", BookBorrowing.objects.filter(school=school).count(), 1),
            ("Announcements", Announcement.objects.filter(school=school).count(), 1),
            ("Leave requests", LeaveRequest.objects.filter(school=school).count(), 1),
            ("Payslips", Payslip.objects.filter(school=school).count(), 1),
            ("Report cards", ReportCard.objects.filter(school=school, academic_term=term).count(), 6),
        ]
        failed = []
        self.stdout.write(f"\nDemo school: {school.name} ({school.subdomain})")
        for label, actual, minimum in checks:
            ok = actual >= minimum
            mark = "PASS" if ok else "FAIL"
            style = self.style.SUCCESS if ok else self.style.ERROR
            self.stdout.write(style(f"[{mark}] {label}: {actual}"))
            if not ok:
                failed.append(label)
        ai_ok = AIConfiguration.objects.filter(school=school).exists()
        self.stdout.write((self.style.SUCCESS if ai_ok else self.style.ERROR)(f"[{'PASS' if ai_ok else 'FAIL'}] AI configuration"))
        if failed or not ai_ok:
            raise CommandError("Demo verification found gaps: " + ", ".join(failed or ["AI configuration"]))
        self.stdout.write(self.style.SUCCESS("\nAll core demo-data checks passed. Proceed with browser/UAT testing."))
