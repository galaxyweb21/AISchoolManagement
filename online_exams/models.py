import uuid
from datetime import timedelta
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class OnlineExam(models.Model):
    STATUS_CHOICES = (
        ('DRAFT', 'Draft'),
        ('PUBLISHED', 'Published'),
        ('CLOSED', 'Closed'),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey('school.School', on_delete=models.CASCADE, related_name='online_exams')
    academic_term = models.ForeignKey('school.AcademicTerm', on_delete=models.PROTECT, related_name='online_exams')
    school_class = models.ForeignKey('academics.SchoolClass', on_delete=models.PROTECT, related_name='online_exams')
    subject = models.ForeignKey('academics.Subject', on_delete=models.PROTECT, related_name='online_exams')
    title = models.CharField(max_length=200)
    topic = models.CharField(max_length=200, blank=True, default='', help_text='Topic or unit used for AI-assisted question generation.')
    instructions = models.TextField(blank=True, default='')
    duration_minutes = models.PositiveSmallIntegerField(default=45, validators=[MinValueValidator(1), MaxValueValidator(300)])
    opens_at = models.DateTimeField()
    closes_at = models.DateTimeField()
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='DRAFT', db_index=True)
    randomize_questions = models.BooleanField(default=False)
    student_access_enabled = models.BooleanField(
        default=True,
        help_text='When disabled, this examination remains staff-managed and is not shown in the student online examination portal.'
    )
    results_released = models.BooleanField(default=False)
    # Idempotent link to the existing assessment gradebook record.
    assessment_record = models.OneToOneField(
        'assessments.Assessment', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='source_online_exam',
        help_text='Assessment record created when reviewed online exam results are exported.'
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_online_exams')
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-opens_at', '-created_at']
        indexes = [models.Index(fields=['school', 'status', 'opens_at'], name='onex_school_stat_open_idx')]

    def clean(self):
        errors = {}
        if self.school_id and self.school_class_id and self.school_class.school_id != self.school_id:
            errors['school_class'] = 'The selected class belongs to another school.'
        if self.school_id and self.subject_id and self.subject.school_id != self.school_id:
            errors['subject'] = 'The selected subject belongs to another school.'
        if self.school_id and self.academic_term_id and self.academic_term.academic_year.school_id != self.school_id:
            errors['academic_term'] = 'The selected academic term belongs to another school.'
        if self.opens_at and self.closes_at and self.closes_at <= self.opens_at:
            errors['closes_at'] = 'The closing time must be later than the opening time.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return '{} — {}'.format(self.title, self.school_class.name)

    @property
    def total_marks(self):
        return sum(self.questions.values_list('marks', flat=True))

    @property
    def is_open(self):
        now = timezone.now()
        return self.status == 'PUBLISHED' and self.opens_at <= now < self.closes_at


class OnlineExamQuestion(models.Model):
    TYPE_CHOICES = (
        ('MCQ', 'Multiple choice'),
        ('TRUE_FALSE', 'True / False'),
        ('SHORT_ANSWER', 'Short answer'),
        ('ESSAY', 'Essay'),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    exam = models.ForeignKey(OnlineExam, on_delete=models.CASCADE, related_name='questions')
    order = models.PositiveIntegerField(default=1)
    question_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='MCQ')
    question_text = models.TextField()
    options = models.JSONField(default=list, blank=True, help_text='Options for multiple-choice questions.')
    correct_answer = models.TextField(blank=True, default='')
    marks = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(100)])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'created_at']
        constraints = [models.UniqueConstraint(fields=['exam', 'order'], name='onex_q_order_uniq')]

    def __str__(self):
        return 'Question {} — {}'.format(self.order, self.exam.title)


class ExamAttempt(models.Model):
    STATUS_CHOICES = (
        ('IN_PROGRESS', 'In progress'),
        ('SUBMITTED', 'Submitted'),
        ('EXPIRED', 'Expired'),
    )
    GRADING_CHOICES = (
        ('PENDING', 'Pending'),
        ('REVIEW_REQUIRED', 'Teacher review required'),
        ('GRADED', 'Graded'),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    exam = models.ForeignKey(OnlineExam, on_delete=models.CASCADE, related_name='attempts')
    student = models.ForeignKey('students.Student', on_delete=models.CASCADE, related_name='online_exam_attempts')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='IN_PROGRESS', db_index=True)
    grading_status = models.CharField(max_length=20, choices=GRADING_CHOICES, default='PENDING', db_index=True)
    started_at = models.DateTimeField(default=timezone.now)
    submitted_at = models.DateTimeField(null=True, blank=True)
    score_awarded = models.PositiveIntegerField(default=0)
    total_marks = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-started_at']
        constraints = [models.UniqueConstraint(fields=['exam', 'student'], name='onex_one_attempt_student')]

    @property
    def deadline(self):
        duration_deadline = self.started_at + timedelta(minutes=self.exam.duration_minutes)
        return min(duration_deadline, self.exam.closes_at)

    @property
    def percentage(self):
        if not self.total_marks:
            return 0
        return round((self.score_awarded / self.total_marks) * 100, 1)


class ExamAnswer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.ForeignKey(ExamAttempt, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(OnlineExamQuestion, on_delete=models.CASCADE, related_name='answers')
    answer_text = models.TextField(blank=True, default='')
    is_correct = models.BooleanField(null=True, blank=True)
    marks_awarded = models.PositiveIntegerField(null=True, blank=True)
    saved_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['attempt', 'question'], name='onex_answer_question_uniq')]
