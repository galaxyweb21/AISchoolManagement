# ai_engine/models.py
from django.db import models
from django.conf import settings
from school.models import School
from school.services import managers
import uuid

# Import GradeLevel from students app
from students.models import GradeLevel


class RiskAssessmentRun(models.Model):
    """One batch computation of dropout-risk scores for every active student."""
    STATUS_CHOICES = (
        ('PENDING', 'Queued'),
        ('RUNNING', 'Assessing'),
        ('COMPLETE', 'Complete'),
        ('FAILED', 'Failed'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='risk_assessment_runs')
    academic_term = models.ForeignKey('school.AcademicTerm', on_delete=models.CASCADE,
                                      related_name='risk_assessment_runs')
    triggered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    computed_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    error_message = models.CharField(max_length=500, blank=True, null=True)
    students_assessed = models.PositiveIntegerField(default=0)
    high_risk_count = models.PositiveIntegerField(default=0)
    critical_risk_count = models.PositiveIntegerField(default=0)

    objects = managers.TenantManager()

    class Meta:
        ordering = ['-computed_at']

    def __str__(self):
        return f"Risk run {self.computed_at:%Y-%m-%d %H:%M} - {self.academic_term} [{self.get_status_display()}]"


class StudentRiskAssessment(models.Model):
    RISK_BANDS = (
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('CRITICAL', 'Critical'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(RiskAssessmentRun, on_delete=models.CASCADE, related_name='assessments')
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='student_risk_assessments')
    student = models.ForeignKey('students.Student', on_delete=models.CASCADE, related_name='risk_assessments')

    risk_score = models.FloatField(help_text="0-100, higher means higher dropout risk.")
    risk_band = models.CharField(max_length=10, choices=RISK_BANDS)

    attendance_rate = models.FloatField(null=True, blank=True)
    attendance_points = models.FloatField(default=0.0)
    grade_average = models.FloatField(null=True, blank=True)
    grade_trend = models.FloatField(null=True, blank=True)
    grade_points = models.FloatField(default=0.0)
    fee_overdue_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    fee_overdue_days = models.PositiveIntegerField(default=0)
    finance_points = models.FloatField(default=0.0)

    contributing_factors = models.JSONField(default=list, blank=True)
    narrative = models.TextField(blank=True, null=True)

    class Meta:
        unique_together = ('run', 'student')
        ordering = ['-risk_score']

    def __str__(self):
        return f"{self.student.user.get_full_name()} - {self.risk_band} ({self.risk_score:.0f})"


class ReportCardBatch(models.Model):
    STATUS_CHOICES = (
        ('PENDING', 'Queued'),
        ('RUNNING', 'Generating'),
        ('COMPLETE', 'Complete'),
        ('FAILED', 'Failed'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='report_card_batches')
    academic_term = models.ForeignKey('school.AcademicTerm', on_delete=models.CASCADE,
                                      related_name='report_card_batches')
    triggered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    error_message = models.CharField(max_length=500, blank=True, null=True)
    students_processed = models.PositiveIntegerField(default=0)
    students_skipped_finalized = models.PositiveIntegerField(default=0)

    objects = managers.TenantManager()

    class Meta:
        ordering = ['-generated_at']

    def __str__(self):
        return f"Report card batch {self.generated_at:%Y-%m-%d %H:%M} - {self.academic_term} [{self.get_status_display()}]"


class ReportCommentBatch(models.Model):
    """Background batch for AI teacher/headteacher report-card comments."""
    STATUS_CHOICES = (
        ('PENDING', 'Queued'),
        ('RUNNING', 'Generating'),
        ('COMPLETE', 'Complete'),
        ('FAILED', 'Failed'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='report_comment_batches')
    academic_term = models.ForeignKey('school.AcademicTerm', on_delete=models.CASCADE, related_name='report_comment_batches')
    school_class = models.ForeignKey('academics.SchoolClass', on_delete=models.SET_NULL, null=True, blank=True, related_name='report_comment_batches')
    triggered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='report_comment_batches')
    generated_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    only_missing = models.BooleanField(default=True)
    regenerate_ai = models.BooleanField(default=False)
    generate_teacher = models.BooleanField(default=True)
    generate_headteacher = models.BooleanField(default=True)
    students_processed = models.PositiveIntegerField(default=0)
    teacher_comments_generated = models.PositiveIntegerField(default=0)
    headteacher_comments_generated = models.PositiveIntegerField(default=0)
    students_skipped_finalized = models.PositiveIntegerField(default=0)
    failures = models.PositiveIntegerField(default=0)
    error_message = models.CharField(max_length=500, blank=True, default='')

    objects = managers.TenantManager()

    class Meta:
        ordering = ['-generated_at']

    def __str__(self):
        return f"Report comments {self.generated_at:%Y-%m-%d %H:%M} - {self.academic_term} [{self.get_status_display()}]"


class ReportCard(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='report_cards')
    student = models.ForeignKey('students.Student', on_delete=models.CASCADE, related_name='report_cards')
    academic_term = models.ForeignKey('school.AcademicTerm', on_delete=models.CASCADE, related_name='report_cards')
    last_batch = models.ForeignKey(ReportCardBatch, on_delete=models.SET_NULL, null=True, related_name='report_cards')

    overall_average = models.FloatField(null=True, blank=True)
    attendance_rate = models.FloatField(null=True, blank=True)
    subject_breakdown = models.JSONField(default=list, blank=True)

    # Enterprise end-of-term result snapshot. These fields make the report
    # card a complete academic document rather than an AI comment record.
    overall_grade = models.CharField(max_length=10, blank=True, default="")
    overall_remark = models.CharField(max_length=100, blank=True, default="")
    total_marks = models.FloatField(default=0)
    total_possible = models.FloatField(default=0)
    overall_position = models.PositiveIntegerField(null=True, blank=True)
    class_size = models.PositiveIntegerField(default=0)
    attendance_present = models.PositiveIntegerField(default=0)
    attendance_absent = models.PositiveIntegerField(default=0)
    attendance_late = models.PositiveIntegerField(default=0)
    attendance_total = models.PositiveIntegerField(default=0)
    ca_weight = models.FloatField(default=30)
    exam_weight = models.FloatField(default=70)
    conduct = models.CharField(max_length=100, blank=True, default="")
    teacher_comment = models.TextField(blank=True, default="")
    headteacher_comment = models.TextField(blank=True, default="")
    promotion_status = models.CharField(max_length=30, blank=True, default="")
    next_term_date = models.DateField(null=True, blank=True)

    COMMENT_SOURCE_CHOICES = (
        ('BLANK', 'Blank'),
        ('AI', 'AI Generated'),
        ('MANUAL', 'Manually Edited'),
    )
    teacher_comment_source = models.CharField(max_length=10, choices=COMMENT_SOURCE_CHOICES, default='BLANK')
    headteacher_comment_source = models.CharField(max_length=10, choices=COMMENT_SOURCE_CHOICES, default='BLANK')
    teacher_comment_generated_at = models.DateTimeField(null=True, blank=True)
    headteacher_comment_generated_at = models.DateTimeField(null=True, blank=True)
    teacher_comment_edited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='edited_teacher_report_comments')
    teacher_comment_edited_at = models.DateTimeField(null=True, blank=True)
    headteacher_comment_edited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='edited_headteacher_report_comments')
    headteacher_comment_edited_at = models.DateTimeField(null=True, blank=True)

    ai_narrative = models.TextField(blank=True, default="")
    ai_last_generated_at = models.DateTimeField(null=True, blank=True)
    edited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='edited_report_cards')
    edited_at = models.DateTimeField(null=True, blank=True)

    is_finalized = models.BooleanField(default=False)
    finalized_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name='finalized_report_cards')
    finalized_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = managers.TenantManager()

    class Meta:
        unique_together = ('student', 'academic_term')
        ordering = ['student__user__first_name']

    def __str__(self):
        status = "Finalized" if self.is_finalized else "Draft"
        return f"{self.student.user.get_full_name()} - {self.academic_term} [{status}]"


class PaymentReminder(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='payment_reminders')
    invoice = models.ForeignKey('finance.Invoice', on_delete=models.CASCADE, related_name='reminders')
    student = models.ForeignKey('students.Student', on_delete=models.CASCADE, related_name='payment_reminders')

    message = models.TextField()
    generated_at = models.DateTimeField(auto_now_add=True)
    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                     related_name='drafted_reminders')
    edited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='edited_reminders')
    edited_at = models.DateTimeField(null=True, blank=True)

    is_sent = models.BooleanField(default=False)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='sent_reminders')
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-generated_at']

    def __str__(self):
        sent = "Sent" if self.is_sent else "Draft"
        return f"Reminder for {self.student.user.get_full_name()} - {self.invoice} [{sent}]"


class ParentChatMessage(models.Model):
    SENDER_CHOICES = (('PARENT', 'Parent'), ('ASSISTANT', 'Assistant'))

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='parent_chat_messages')
    parent = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='parent_chat_messages',
                               limit_choices_to={'role': 'PARENT'})
    student = models.ForeignKey('students.Student', on_delete=models.CASCADE, related_name='parent_chat_messages')
    sender = models.CharField(max_length=10, choices=SENDER_CHOICES)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.sender}: {self.content[:50]}"


class GeneratedExam(models.Model):
    """One AI-generated question set with GES curriculum alignment."""
    DIFFICULTY_CHOICES = (
        ('EASY', 'Easy'),
        ('MEDIUM', 'Medium'),
        ('HARD', 'Hard'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='generated_exams')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    title = models.CharField(max_length=200, help_text="e.g., Mid-Term Mathematics Quiz")
    subject = models.CharField(max_length=100)

    subject_ref = models.ForeignKey(
        'academics.Subject',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='generated_exams'
    )

    topic = models.CharField(max_length=200, blank=True)

    school_class = models.ForeignKey(
        'academics.SchoolClass',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='generated_exams'
    )

    # GES Curriculum Stage - uses GradeLevel.STAGE_CHOICES
    ges_stage = models.CharField(
        max_length=10,
        choices=GradeLevel.STAGE_CHOICES,
        default='OTHER',
        help_text="GES curriculum stage used for generating this exam"
    )

    grade_level = models.CharField(max_length=50, blank=True, help_text="Display name of the grade level")
    difficulty = models.CharField(max_length=10, choices=DIFFICULTY_CHOICES, default='MEDIUM')

    linked_assessment = models.ForeignKey(
        'assessments.Assessment', on_delete=models.SET_NULL, null=True, blank=True, related_name='generated_exam'
    )

    objects = managers.TenantManager()

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.subject}, {self.get_difficulty_display()})"


class GeneratedQuestion(models.Model):
    TYPE_CHOICES = (
        ('MCQ', 'Multiple Choice'),
        ('TRUE_FALSE', 'True / False'),
        ('SHORT_ANSWER', 'Short Answer'),
        ('ESSAY', 'Essay'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    exam = models.ForeignKey(GeneratedExam, on_delete=models.CASCADE, related_name='questions')
    order = models.PositiveIntegerField(default=0)
    question_type = models.CharField(max_length=15, choices=TYPE_CHOICES)
    question_text = models.TextField()
    options = models.JSONField(default=list, blank=True)
    correct_answer = models.TextField()
    points = models.PositiveIntegerField(default=1)

    is_ai_generated = models.BooleanField(default=True)
    edited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='edited_questions')
    edited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"Q{self.order + 1}: {self.question_text[:60]}"


class AIConversation(models.Model):
    # Every other model in this file uses a UUID primary key, and
    # ai_engine/urls.py routes conversation load/delete through
    # <uuid:conversation_id>. Without this field Django falls back to a
    # plain auto-incrementing integer id (1, 2, 3, ...), which can never
    # match a <uuid:...> URL pattern - every "load previous conversation"
    # and "delete conversation" request 404s before it even reaches the
    # view. This was the actual cause of those two features being broken.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_archived = models.BooleanField(default=False)


class AIMessage(models.Model):
    # Individual messages are addressed/returned by id in the Copilot API
    # response payloads and get_conversation_messages formatting - kept as
    # a UUID primary key (matching AIConversation above and every other
    # model in this file) rather than a guessable auto-incrementing int.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ROLE = (("USER", "User"), ("AI", "AI"), ("SYSTEM", "System"))
    conversation = models.ForeignKey(AIConversation, related_name="messages", on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE)
    content = models.TextField()
    execution_time = models.FloatField(default=0)
    model_name = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AITask(models.Model):
    STATUS = (("PENDING", "Pending"), ("RUNNING", "Running"), ("SUCCESS", "Success"), ("FAILED", "Failed"))
    school = models.ForeignKey(School, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    engine = models.CharField(max_length=80)
    prompt = models.TextField()
    response = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default="PENDING")
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)


class AIActivity(models.Model):
    TYPE_CHOICES = [
        ("RISK", "Risk Assessment"),
        ("REPORT_CARD", "Report Card"),
        ("FINANCE", "Finance"),
        ("PAYMENT_REMINDER", "Payment Reminder"),
        ("EXAM", "Exam Generator"),
        ("PARENT_CHAT", "Parent Assistant"),
        ("TIMETABLE", "Timetable"),
        ("LESSON_PLAN", "Lesson Plan"),
        ("GENERAL", "General"),
    ]
    STATUS_CHOICES = [("SUCCESS", "Success"), ("WARNING", "Warning"), ("FAILED", "Failed")]

    school = models.ForeignKey("school.School", on_delete=models.CASCADE, related_name="ai_activities")
    activity_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="SUCCESS")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class AIRequest(models.Model):
    ENGINE_CHOICES = (
    ("RISK", "Risk"), ("REPORT", "Report Card"), ("FINANCE", "Finance"), ("EXAM", "Exam"), ("PARENT", "Parent"),
    ("GENERAL", "General"))
    STATUS = (("SUCCESS", "Success"), ("FAILED", "Failed"), ("RUNNING", "Running"))

    school = models.ForeignKey(School, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    engine = models.CharField(max_length=30, choices=ENGINE_CHOICES)
    prompt = models.TextField()
    response = models.TextField(blank=True)
    model_name = models.CharField(max_length=80, blank=True)
    execution_time = models.FloatField(default=0)
    status = models.CharField(max_length=20, choices=STATUS, default="RUNNING")
    created_at = models.DateTimeField(auto_now_add=True)


class AIConfiguration(models.Model):
    school = models.OneToOneField(School, on_delete=models.CASCADE)
    provider = models.CharField(max_length=30, default="Groq")
    model_name = models.CharField(max_length=100, default="llama-3.3-70b-versatile")
    temperature = models.FloatField(default=0.3)
    max_tokens = models.IntegerField(default=2048)
    enable_exam_ai = models.BooleanField(default=True)
    enable_finance_ai = models.BooleanField(default=True)
    enable_risk_ai = models.BooleanField(default=True)
    enable_parent_ai = models.BooleanField(default=True)
    enable_report_ai = models.BooleanField(default=True)


class SubstituteAssignment(models.Model):
    STATUS_CHOICES = (('SUGGESTED', 'Suggested'), ('CONFIRMED', 'Confirmed'), ('UNCOVERED', 'No substitute available'))

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='substitute_assignments')
    absence = models.ForeignKey('staff.TeacherAbsence', on_delete=models.CASCADE, related_name='substitute_assignments')
    timetable_entry = models.ForeignKey('academics.TimetableEntry', on_delete=models.CASCADE,
                                        related_name='substitute_assignments')

    suggested_substitute = models.ForeignKey('staff.Teacher', on_delete=models.SET_NULL, null=True, blank=True,
                                             related_name='+')
    confirmed_substitute = models.ForeignKey('staff.Teacher', on_delete=models.SET_NULL, null=True, blank=True,
                                             related_name='substitute_cover_assignments')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='SUGGESTED')

    handover_note = models.TextField(blank=True)
    note_edited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='+')
    note_edited_at = models.DateTimeField(null=True, blank=True)

    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name='+')
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('absence', 'timetable_entry')
        ordering = ['timetable_entry__timeslot__period_index']

    def __str__(self):
        return f"Cover for {self.timetable_entry} ({self.get_status_display()})"


class AIInsight(models.Model):
    LEVELS = (("INFO", "Info"), ("SUCCESS", "Success"), ("WARNING", "Warning"), ("CRITICAL", "Critical"))

    school = models.ForeignKey("school.School", on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    message = models.TextField()
    level = models.CharField(max_length=20, choices=LEVELS, default="INFO")
    source = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]


class AIAutomationTask(models.Model):
    # ai_engine/urls.py routes task approval through <uuid:task_id> (see
    # approve_task in views/automation.py), so this needs a real UUID
    # primary key for the same reason AIConversation/AIMessage do above -
    # without it every "approve" request 404s before reaching the view.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    STATUS_CHOICES = (
    ("PENDING", "Pending"), ("APPROVED", "Approved"), ("RUNNING", "Running"), ("COMPLETED", "Completed"),
    ("FAILED", "Failed"), ("CANCELLED", "Cancelled"))
    PRIORITY_CHOICES = (("LOW", "Low"), ("MEDIUM", "Medium"), ("HIGH", "High"), ("CRITICAL", "Critical"))

    school = models.ForeignKey("school.School", on_delete=models.CASCADE, related_name="automation_tasks")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    task_type = models.CharField(max_length=100)
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default="MEDIUM")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="created_ai_tasks")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="approved_ai_tasks")
    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["school", "status"]), models.Index(fields=["task_type"]),
                   models.Index(fields=["priority"])]

    def __str__(self):
        return self.title


# ============================================================================
# STEP 1 — AI TOOL REGISTRY: SECURE EXECUTION AUDIT LOG
# ============================================================================

class ToolExecutionLog(models.Model):
    """
    Audit trail for every AI tool invocation that goes through the
    secure ToolRegistry executor (ai_engine.services.tool_registry).

    This is distinct from AIActivity (human-readable activity feed) and
    AIRequest (chat-level request/response log): this table records the
    low-level tool call itself — what tool, with what arguments, whether
    it was authorized, how long it took, and whether it succeeded — so
    that tool execution can be audited independently of the higher-level
    conversation.
    """
    STATUS_CHOICES = (
        ("SUCCESS", "Success"),
        ("DENIED", "Permission Denied"),
        ("INVALID", "Invalid Arguments"),
        ("TIMEOUT", "Timed Out"),
        ("ERROR", "Error"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey("school.School", on_delete=models.CASCADE,
                                related_name="tool_execution_logs", null=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                              null=True, blank=True, related_name="tool_execution_logs")
    tool_name = models.CharField(max_length=100, db_index=True)
    required_capability = models.CharField(max_length=100, blank=True)
    arguments = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="SUCCESS")
    result_summary = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["school", "tool_name"]),
            models.Index(fields=["school", "status"]),
        ]

    def __str__(self):
        return f"{self.tool_name} [{self.status}] {self.created_at:%Y-%m-%d %H:%M}"


# ============================================================================
# STEP 2 — SCHOOL AI MEMORY
# ============================================================================

class SchoolAIMemory(models.Model):
    """
    Persistent memory the AI copilot can draw on across conversations.

    Two scopes:
      - SCHOOL: shared facts/preferences about how the school operates
        (e.g. "Term 2 always starts the first Monday of May",
        "Reports go out through the Registrar, not Bursar").
      - USER: facts specific to one staff member's working style
        (e.g. "Mr. Mensah prefers report narratives in a formal tone").

    Memories are plain facts recorded by the system or confirmed by a
    user — never silently inferred and injected without being stored
    through remember(). Expired or deactivated memories are excluded
    from recall automatically.
    """
    SCOPE_CHOICES = (
        ("SCHOOL", "School-wide"),
        ("USER", "User-specific"),
    )
    MEMORY_TYPE_CHOICES = (
        ("FACT", "Fact"),
        ("PREFERENCE", "Preference"),
        ("DECISION", "Decision"),
        ("POLICY", "School Policy"),
        ("CONTEXT", "Situational Context"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey("school.School", on_delete=models.CASCADE,
                                related_name="ai_memories")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              null=True, blank=True, related_name="ai_memories")
    scope = models.CharField(max_length=10, choices=SCOPE_CHOICES, default="SCHOOL")
    memory_type = models.CharField(max_length=20, choices=MEMORY_TYPE_CHOICES, default="FACT")
    key = models.CharField(max_length=150, blank=True,
                            help_text="Short stable label, e.g. 'term_start_policy'. "
                                      "Used to find/update the same memory instead of duplicating it.")
    content = models.TextField()
    importance = models.PositiveSmallIntegerField(default=2,
                                                    help_text="1=low, 2=normal, 3=high — higher ranks first in recall.")
    source = models.CharField(max_length=100, blank=True,
                               help_text="Where this memory came from, e.g. 'chat', 'briefing', 'admin'.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="+")
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-importance", "-updated_at"]
        indexes = [
            models.Index(fields=["school", "scope", "is_active"]),
            models.Index(fields=["school", "user", "is_active"]),
            models.Index(fields=["school", "key"]),
        ]

    def __str__(self):
        return f"[{self.scope}] {self.key or self.content[:40]}"


# ============================================================================
# STEP 3 — GHANA EDUCATION RAG / KNOWLEDGE BASE
# ============================================================================

class GhanaEducationKnowledgeDocument(models.Model):
    """
    Curated, locally-stored Ghana education knowledge — the actual
    content the RAG layer searches over, as opposed to
    ghana_education.GHANA_EDUCATION_DOMAINS (which is just a topic
    taxonomy used for routing, with no retrievable content of its own).

    Deliberately NOT tenant-scoped: general Ghana education knowledge
    (GES/NaCCA/MoE/WAEC structure and policy) is the same for every
    school on the platform, so one curated library serves all of them.
    School-specific facts belong in SchoolAIMemory instead.

    Every document must be traceable to an official source (source_name
    + source_url) so the citation engine (Step 4) always has something
    genuine to cite — this table is the thing that makes citations
    possible instead of the AI inventing them.
    """
    SOURCE_CHOICES = (
        ("GES", "Ghana Education Service"),
        ("NACCA", "National Council for Curriculum and Assessment"),
        ("MOE", "Ministry of Education"),
        ("WAEC", "West African Examinations Council"),
        ("OTHER", "Other Official Source"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    domain = models.CharField(max_length=80, db_index=True,
                               help_text="Matches a key in ghana_education.GHANA_EDUCATION_DOMAINS, "
                                         "e.g. 'nacca', 'bece', 'shs'.")
    title = models.CharField(max_length=255)
    source_name = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="OTHER")
    source_url = models.URLField()
    content = models.TextField(help_text="Curated excerpt/summary in plain language, not a verbatim "
                                          "copy of copyrighted material.")
    effective_date = models.DateField(null=True, blank=True,
                                       help_text="When this fact/policy took effect, if known.")
    last_verified_at = models.DateField(null=True, blank=True,
                                         help_text="Last time a human confirmed this is still accurate.")
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["domain", "title"]
        indexes = [
            models.Index(fields=["domain", "is_active"]),
            models.Index(fields=["source_name"]),
        ]

    def __str__(self):
        return f"[{self.source_name}] {self.title}"