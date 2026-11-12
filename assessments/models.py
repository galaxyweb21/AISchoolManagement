# assessments/models.py
import uuid
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import models

from school.models import School
from students.models import Student
from academics.models import SchoolClass


class Assessment(models.Model):
    TYPE_CHOICES = (
        ('EXAM', 'Exam'),
        ('QUIZ', 'Quiz'),
        ('ASSIGNMENT', 'Assignment'),
    )
    SCORE_COMPONENT_CHOICES = (
        ('CA', 'Class / Continuous Assessment'),
        ('EXAM', 'End-of-Term Examination'),
        ('OTHER', 'Other Assessment'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='assessments')
    school_class = models.ForeignKey(
        SchoolClass, on_delete=models.SET_NULL, null=True, blank=True, related_name='assessments',
        help_text='Class this assessment belongs to.'
    )
    academic_term = models.ForeignKey(
        'school.AcademicTerm', on_delete=models.SET_NULL, null=True, blank=True, related_name='assessments',
        help_text='Academic term for this assessment.'
    )
    title = models.CharField(max_length=200, null=True, help_text='e.g., End of Term Mathematics Examination')
    subject = models.CharField(max_length=100, help_text='e.g., Mathematics, Science')
    assessment_type = models.CharField(max_length=15, choices=TYPE_CHOICES)
    score_component = models.CharField(
        max_length=10, choices=SCORE_COMPONENT_CHOICES, default='CA', db_index=True,
        help_text='The terminal-results component this assessment contributes to.'
    )
    max_score = models.PositiveIntegerField(default=100)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} ({self.subject})"


class Grade(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name='grades')
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='grades')
    score_achieved = models.DecimalField(max_digits=7, decimal_places=2)
    teacher_notes = models.TextField(blank=True, null=True)
    ai_feedback = models.TextField(blank=True, null=True)
    graded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('assessment', 'student')

    @property
    def percentage(self):
        if not self.assessment.max_score:
            return Decimal('0')
        return (self.score_achieved / Decimal(str(self.assessment.max_score))) * Decimal('100')

    def __str__(self):
        return f"{self.student.user.get_full_name()} - {self.assessment.title}: {self.score_achieved}"


class AssessmentQuestion(models.Model):
    TYPE_CHOICES = (
        ('MCQ', 'Multiple Choice'),
        ('TRUE_FALSE', 'True / False'),
        ('SHORT_ANSWER', 'Short Answer'),
        ('ESSAY', 'Essay'),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name='questions')
    order = models.PositiveIntegerField(default=0)
    question_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='SHORT_ANSWER')
    question_text = models.TextField()
    options = models.JSONField(default=list, blank=True)
    correct_answer = models.TextField(blank=True)
    marks = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"Q{self.order}: {self.question_text[:60]}"


class TerminalResult(models.Model):
    """Authoritative Ghana-style terminal result for one student/subject/term.

    Class score and examination score are stored explicitly on the 30/70 scale.
    Raw marks are retained when a teacher enters marks using a different scale,
    making the conversion auditable without changing the official result.
    """
    ENTRY_MODE_CHOICES = (
        ('WEIGHTED', 'Weighted 30/70'),
        ('RAW', 'Raw marks converted to 30/70'),
        ('CALCULATED', 'Calculated from recorded assessments'),
    )
    STATUS_CHOICES = (
        ('DRAFT', 'Draft'),
        ('COMPLETE', 'Complete'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='terminal_results')
    academic_term = models.ForeignKey('school.AcademicTerm', on_delete=models.CASCADE, related_name='terminal_results')
    school_class = models.ForeignKey(SchoolClass, on_delete=models.PROTECT, related_name='terminal_results')
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='terminal_results')
    subject = models.CharField(max_length=150, db_index=True)

    class_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    exam_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    final_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    grade = models.CharField(max_length=10, blank=True, default='')
    remark = models.CharField(max_length=100, blank=True, default='')

    class_raw_score = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    class_raw_max = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    exam_raw_score = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    exam_raw_max = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    entry_mode = models.CharField(max_length=12, choices=ENTRY_MODE_CHOICES, default='WEIGHTED')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='DRAFT')

    teacher_note = models.TextField(blank=True, default='')
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='entered_terminal_results'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('student', 'academic_term', 'school_class', 'subject')
        ordering = ['student__user__last_name', 'student__user__first_name']
        indexes = [
            models.Index(fields=['school', 'academic_term', 'school_class', 'subject']),
        ]

    @staticmethod
    def _q(value):
        return Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    def calculate(self):
        if self.class_score is not None:
            self.class_score = max(Decimal('0'), min(Decimal('30'), self._q(self.class_score)))
        if self.exam_score is not None:
            self.exam_score = max(Decimal('0'), min(Decimal('70'), self._q(self.exam_score)))
        if self.class_score is None and self.exam_score is None:
            self.final_score, self.grade, self.remark = None, '', ''
            self.status = 'DRAFT'
            return self
        self.final_score = self._q((self.class_score or Decimal('0')) + (self.exam_score or Decimal('0')))
        if self.class_score is None or self.exam_score is None:
            self.grade, self.remark = '', ''
            self.status = 'DRAFT'
            return self
        value = float(self.final_score)
        if value >= 90:
            self.grade, self.remark = 'A+', 'Outstanding'
        elif value >= 80:
            self.grade, self.remark = 'A', 'Excellent'
        elif value >= 70:
            self.grade, self.remark = 'B', 'Very Good'
        elif value >= 60:
            self.grade, self.remark = 'C', 'Good'
        elif value >= 50:
            self.grade, self.remark = 'D', 'Satisfactory'
        elif value >= 40:
            self.grade, self.remark = 'E', 'Pass'
        else:
            self.grade, self.remark = 'F', 'Needs Improvement'
        self.status = 'COMPLETE' if self.class_score is not None and self.exam_score is not None else 'DRAFT'
        return self

    def save(self, *args, **kwargs):
        self.calculate()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.student.user.get_full_name()} - {self.subject}: {self.final_score}/100"
