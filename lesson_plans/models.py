import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.core.validators import FileExtensionValidator
from school.models import School, AcademicTerm
from academics.models import SchoolClass, Subject
from staff.models import Teacher


class WeeklyLessonPlan(models.Model):
    STATUS_DRAFT = 'DRAFT'
    STATUS_SUBMITTED = 'SUBMITTED'
    STATUS_REVISION = 'REVISION_REQUESTED'
    STATUS_APPROVED = 'APPROVED'
    METHOD_MANUAL = 'MANUAL'
    METHOD_AI = 'AI'
    METHOD_UPLOAD = 'UPLOAD'
    METHOD_CHOICES = (
        (METHOD_MANUAL, 'Type lesson note manually'),
        (METHOD_AI, 'Generate with AI and review'),
        (METHOD_UPLOAD, 'Upload an existing document'),
    )

    STATUS_CHOICES = (
        (STATUS_DRAFT, 'Draft'),
        (STATUS_SUBMITTED, 'Submitted for review'),
        (STATUS_REVISION, 'Revision requested'),
        (STATUS_APPROVED, 'Approved'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='weekly_lesson_plans')
    teacher = models.ForeignKey(Teacher, on_delete=models.PROTECT, related_name='weekly_lesson_plans')
    academic_term = models.ForeignKey(AcademicTerm, on_delete=models.PROTECT, related_name='weekly_lesson_plans')
    week_start = models.DateField(help_text='Monday of the teaching week')
    school_class = models.ForeignKey(SchoolClass, on_delete=models.PROTECT, related_name='weekly_lesson_plans')
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name='weekly_lesson_plans')
    submission_method = models.CharField(max_length=12, choices=METHOD_CHOICES, default=METHOD_MANUAL)
    topic = models.CharField(max_length=200)
    subtopic = models.CharField(max_length=200, blank=True)
    learning_objectives = models.TextField()
    teaching_resources = models.TextField(blank=True)
    introduction = models.TextField()
    lesson_development = models.TextField()
    conclusion = models.TextField(blank=True)
    assessment = models.TextField()
    reflection = models.TextField(blank=True)
    supporting_document = models.FileField(
        upload_to='lesson_plan_documents/%Y/%m/',
        blank=True,
        null=True,
        validators=[FileExtensionValidator(allowed_extensions=['pdf', 'doc', 'docx'])],
        help_text='Optional lesson note document (PDF, DOC or DOCX; maximum 10 MB).',
    )
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    teacher_submitted_at = models.DateTimeField(null=True, blank=True)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_lesson_plans')
    reviewer_comment = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-week_start', 'school_class__name', 'subject__name']
        constraints = [
            models.UniqueConstraint(
                fields=['school', 'teacher', 'academic_term', 'week_start', 'school_class', 'subject'],
                name='uniq_weekly_lesson_plan_scope',
            ),
        ]
        indexes = [
            models.Index(fields=['school', 'status', 'week_start'], name='lesson_school_status_week_idx'),
            models.Index(fields=['teacher', 'week_start'], name='lesson_teacher_week_idx'),
        ]

    def __str__(self):
        return f'{self.topic} — {self.school_class} / {self.subject} ({self.week_start})'

    def mark_submitted(self):
        self.status = self.STATUS_SUBMITTED
        self.teacher_submitted_at = timezone.now()
        self.reviewer = None
        self.reviewed_at = None
        self.reviewer_comment = ''
