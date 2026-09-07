# academics/models.py
from django.db import models
from django.conf import settings
from django.utils.text import slugify
from school.models import School
from school.services import managers
import uuid
from students.models import GradeLevel


# ============================================================
# SUBJECT MODEL
# ============================================================

class Subject(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='subjects')
    name = models.CharField(max_length=150, help_text="e.g., Mathematics, Integrated Science")
    code = models.CharField(max_length=50, blank=True, editable=False)
    requires_lab = models.BooleanField(
        default=False,
        help_text="If true, the timetabler will only place this subject in a lab-equipped room.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = managers.TenantManager()

    class Meta:
        unique_together = ('school', 'name')
        ordering = ['name']

    def save(self, *args, **kwargs):
        if not self.code:
            base_code = slugify(self.name).replace('-', '_').upper()
            existing_codes = Subject.objects.filter(school=self.school)
            if self.pk:
                existing_codes = existing_codes.exclude(pk=self.pk)
            existing_codes = existing_codes.values_list('code', flat=True)
            code = base_code
            counter = 1
            while code in existing_codes:
                code = f"{base_code}_{counter}"
                counter += 1
            self.code = code
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.code})"


# ============================================================
# SCHOOL CLASS MODEL
# ============================================================

class SchoolClass(models.Model):
    """A teaching cohort, e.g. 'Basic 1', 'JHS 2 Gold'."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='classes')
    name = models.CharField(max_length=100, help_text="e.g., Basic 1, JHS 2 Gold")

    # ForeignKey to GradeLevel - this links to the GES-aligned grade level
    grade_level = models.ForeignKey(
        GradeLevel,
        on_delete=models.PROTECT,
        related_name='school_classes'
    )

    student_count = models.PositiveIntegerField(default=0, editable=False)
    homeroom_teacher = models.ForeignKey(
        'staff.Teacher',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='homerooms'
    )
    uses_single_class_teacher = models.BooleanField(
        null=True, blank=True, default=None,
        help_text=(
            "Common in Ghanaian Nursery/KG and lower Primary classes: one class teacher "
            "delivers every subject, rather than a different subject teacher per period. "
            "When True, assigning a class teacher (see homeroom_teacher) automatically "
            "creates the underlying per-subject TeacherAssignment rows the timetabler needs "
            "-- no manual per-subject assignment required. Left as None until first saved, "
            "at which point it defaults from the grade level's GES stage (True for KG/Primary, "
            "False for JHS/SHS) -- but a school can override it per class either way."
        ),
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = managers.TenantManager()

    class Meta:
        unique_together = ('school', 'grade_level', 'name')
        verbose_name_plural = 'School Classes'
        ordering = ['grade_level__order', 'name']

    def save(self, *args, **kwargs):
        if self.uses_single_class_teacher is None:
            # Default on first save only -- a school can still flip this
            # per class afterward without it being silently reset.
            self.uses_single_class_teacher = self.stage in ('KG', 'PRIMARY')
        super().save(*args, **kwargs)

    @property
    def stage(self):
        """Convenience property to get the GES stage from the grade level"""
        return self.grade_level.stage if self.grade_level else 'OTHER'

    @property
    def grade_level_name(self):
        """Get the grade level name"""
        return self.grade_level.name if self.grade_level else 'N/A'

    def __str__(self):
        return f"{self.name} ({self.grade_level.name})"


# ============================================================
# TEACHER ASSIGNMENT MODELS
# ============================================================

class TeacherAssignment(models.Model):
    """
    Assigns a teacher to a specific subject in a specific class.
    This is the core of the teacher-class-subject relationship.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='teacher_assignments')

    teacher = models.ForeignKey(
        'staff.Teacher',
        on_delete=models.CASCADE,
        related_name='assignments'
    )
    school_class = models.ForeignKey(
        SchoolClass,
        on_delete=models.CASCADE,
        related_name='teacher_assignments'
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name='teacher_assignments'
    )

    # Periods per week
    periods_per_week = models.PositiveIntegerField(
        default=4,
        help_text="Number of periods per week for this subject in this class"
    )

    # Status flags
    is_primary = models.BooleanField(
        default=False,
        help_text="Is this the primary teacher for this class?"
    )
    is_active = models.BooleanField(default=True)

    # Timestamps
    assigned_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='assigned_teachers'
    )

    objects = managers.TenantManager()

    class Meta:
        unique_together = ['teacher', 'school_class', 'subject']
        ordering = ['school_class__name', 'subject__name']

    def __str__(self):
        return f"{self.teacher.user.get_full_name()} - {self.subject.name} ({self.school_class.name})"


class ClassSubject(models.Model):
    """
    Subjects offered in a specific class/grade level.
    This defines what subjects a class should have assigned.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='class_subjects')

    school_class = models.ForeignKey(
        SchoolClass,
        on_delete=models.CASCADE,
        related_name='class_subjects'
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name='class_subjects'
    )

    # Subject-specific settings for this class
    is_core = models.BooleanField(
        default=False,
        help_text="Is this a core/compulsory subject?"
    )
    periods_per_week = models.PositiveIntegerField(
        default=4,
        help_text="Default periods per week for this subject in this class"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = managers.TenantManager()

    class Meta:
        unique_together = ['school_class', 'subject']
        ordering = ['school_class__name', 'subject__name']

    def __str__(self):
        return f"{self.school_class.name} - {self.subject.name}"


class TeacherClassAssignment(models.Model):
    """
    Assigns a teacher as a homeroom/form teacher for a class.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='teacher_class_assignments')

    teacher = models.ForeignKey(
        'staff.Teacher',
        on_delete=models.CASCADE,
        related_name='homeroom_assignments'
    )
    school_class = models.ForeignKey(
        SchoolClass,
        on_delete=models.CASCADE,
        related_name='homeroom_teachers'
    )

    is_active = models.BooleanField(default=True)
    assigned_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='assigned_homerooms'
    )

    objects = managers.TenantManager()

    class Meta:
        unique_together = ['school_class', 'teacher']
        ordering = ['school_class__name']

    def __str__(self):
        return f"{self.teacher.user.get_full_name()} - Homeroom: {self.school_class.name}"


# ============================================================
# TIMETABLE MODELS
# ============================================================

class ClassSubjectRequirement(models.Model):
    """
    Defines the subject requirements for a class.
    This is used by the timetabler to know what subjects need scheduling.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='subject_requirements')
    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name='subject_requirements')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='class_requirements')
    periods_per_week = models.PositiveSmallIntegerField(default=1)

    objects = managers.TenantManager()

    class Meta:
        unique_together = ('school_class', 'subject')

    def __str__(self):
        return f"{self.school_class.name} - {self.subject.name} ({self.periods_per_week}/wk)"


class Room(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='rooms')
    name = models.CharField(max_length=100, help_text="e.g., Room 302, Chemistry Lab")
    capacity = models.PositiveIntegerField(default=40)
    is_lab = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = managers.TenantManager()

    class Meta:
        unique_together = ('school', 'name')
        ordering = ['name']

    def __str__(self):
        return self.name


class TimeSlot(models.Model):
    DAY_CHOICES = (
        ('MON', 'Monday'),
        ('TUE', 'Tuesday'),
        ('WED', 'Wednesday'),
        ('THU', 'Thursday'),
        ('FRI', 'Friday'),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='timeslots')
    day = models.CharField(max_length=3, choices=DAY_CHOICES)
    period_index = models.PositiveSmallIntegerField(help_text="1 = first period of the day, 2 = second, etc.")
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)

    objects = managers.TenantManager()

    class Meta:
        unique_together = ('school', 'day', 'period_index')
        ordering = ['day', 'period_index']

    @property
    def slot_id(self):
        return f"{self.day}-{self.start_time.strftime('%H%M')}"

    @property
    def day_display(self):
        return self.get_day_display()

    def __str__(self):
        return f"{self.get_day_display()} P{self.period_index} ({self.start_time.strftime('%H:%M')} - {self.end_time.strftime('%H:%M')})"


class Timetable(models.Model):
    STATUS_CHOICES = (
        ('PENDING', 'Queued'),
        ('RUNNING', 'Generating'),
        ('COMPLETE', 'Complete'),
        ('FAILED', 'Failed'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='timetables')
    academic_term = models.ForeignKey('school.AcademicTerm', on_delete=models.CASCADE, related_name='timetables')
    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    error_message = models.CharField(max_length=500, blank=True, null=True)
    fitness_score = models.FloatField(default=0.0)
    hard_conflicts = models.PositiveIntegerField(default=0)
    soft_conflicts = models.PositiveIntegerField(default=0)
    generations_run = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(
        default=False,
        help_text="The one timetable actively shown to teachers/students."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = managers.TenantManager()

    class Meta:
        ordering = ['-generated_at']

    def __str__(self):
        return f"Timetable {self.generated_at:%Y-%m-%d %H:%M} - {self.academic_term} [{self.get_status_display()}]"


class TimetableEntry(models.Model):
    """
    A single entry in a timetable: a class, subject, teacher, room, and timeslot.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timetable = models.ForeignKey(Timetable, on_delete=models.CASCADE, related_name='entries')
    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name='timetable_entries')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='timetable_entries')
    teacher = models.ForeignKey('staff.Teacher', on_delete=models.CASCADE, related_name='timetable_entries')
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='timetable_entries')
    timeslot = models.ForeignKey(TimeSlot, on_delete=models.CASCADE, related_name='timetable_entries')
    is_lab = models.BooleanField(default=False, help_text="Is this a lab session?")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # No direct `school` FK on this model -- only reachable via
    # timetable.school -- so the shared TenantManager needs the
    # relation path spelled out explicitly.
    objects = managers.TenantManager(school_field="timetable__school")

    class Meta:
        unique_together = ('timetable', 'school_class', 'timeslot')
        ordering = ['school_class__name', 'timeslot__day', 'timeslot__period_index']

    def __str__(self):
        return f"{self.school_class.name}: {self.subject.name} @ {self.timeslot}"


# ============================================================
# TEACHER WORKLOAD MODEL
# ============================================================

class TeacherWorkload(models.Model):
    """
    Tracks teacher workload across the school.
    Used for AI-powered timetabling and workload analysis.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='teacher_workloads')

    teacher = models.ForeignKey(
        'staff.Teacher',
        on_delete=models.CASCADE,
        related_name='workloads'
    )
    academic_term = models.ForeignKey(
        'school.AcademicTerm',
        on_delete=models.CASCADE,
        related_name='teacher_workloads'
    )

    # Calculated workload metrics
    total_periods = models.PositiveIntegerField(
        default=0,
        help_text="Total periods assigned to this teacher this term"
    )
    max_periods = models.PositiveIntegerField(
        default=25,
        help_text="Maximum periods allowed per week for this teacher"
    )
    workload_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        help_text="Percentage of max workload used"
    )

    # Subject breakdown
    subject_breakdown = models.JSONField(
        default=dict,
        help_text="Breakdown of subjects taught: {'subject_name': periods_count, ...}"
    )

    # Class breakdown
    class_breakdown = models.JSONField(
        default=dict,
        help_text="Breakdown of classes taught: {'class_name': periods_count, ...}"
    )

    is_overloaded = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = managers.TenantManager()

    class Meta:
        unique_together = ['teacher', 'academic_term']
        ordering = ['-workload_percentage']

    def __str__(self):
        return f"{self.teacher.user.get_full_name()} - {self.workload_percentage}%"


# academics/models.py - Add these models at the end of the file

# ============================================================
# STUDENT PROMOTION MODELS
# ============================================================

class PromotionRule(models.Model):
    """
    Defines promotion rules for each grade level.
    Schools can configure promotion criteria based on:
    - Minimum passing grade
    - Number of subjects required to pass
    - Promotion percentage threshold
    """
    PROMOTION_MODE_CHOICES = (
        ('AUTO', 'Automatic Promotion'),
        ('MANUAL', 'Manual Promotion'),
        ('HYBRID', 'Hybrid (Auto with Manual Override)'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='promotion_rules')

    # Grade level this rule applies to
    from_grade_level = models.ForeignKey(
        'students.GradeLevel',
        on_delete=models.CASCADE,
        related_name='promotion_rules_from',
        help_text="The grade level students are being promoted FROM"
    )
    to_grade_level = models.ForeignKey(
        'students.GradeLevel',
        on_delete=models.CASCADE,
        related_name='promotion_rules_to',
        help_text="The grade level students are being promoted TO"
    )

    # Promotion criteria
    promotion_mode = models.CharField(
        max_length=10,
        choices=PROMOTION_MODE_CHOICES,
        default='AUTO'
    )

    # Academic criteria
    minimum_passing_grade = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=50.00,
        help_text="Minimum grade percentage to pass a subject"
    )
    minimum_subjects_to_pass = models.PositiveIntegerField(
        default=0,
        help_text="Minimum number of subjects a student must pass to be promoted (0 = all subjects)"
    )
    minimum_overall_average = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=50.00,
        help_text="Minimum overall average to be promoted"
    )

    # Attendance criteria
    minimum_attendance_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=75.00,
        help_text="Minimum attendance percentage required for promotion"
    )

    # Special considerations
    allow_conditional_promotion = models.BooleanField(
        default=False,
        help_text="Allow conditional promotion for students who narrowly miss requirements"
    )
    max_conditional_subjects = models.PositiveIntegerField(
        default=2,
        help_text="Maximum number of subjects a student can fail and still be conditionally promoted"
    )

    # Academic term to evaluate
    evaluation_term_sequence = models.PositiveIntegerField(
        default=3,
        help_text="Which term's results to evaluate (1, 2, 3 - usually 3 for third term)"
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = managers.TenantManager()

    class Meta:
        unique_together = ['school', 'from_grade_level', 'to_grade_level']
        ordering = ['from_grade_level__order', 'to_grade_level__order']

    def __str__(self):
        return f"{self.from_grade_level.name} → {self.to_grade_level.name}"


class StudentPromotion(models.Model):
    """
    Tracks student promotions and their status.
    """
    STATUS_CHOICES = (
        ('PENDING', 'Pending Review'),
        ('PROMOTED', 'Promoted'),
        ('CONDITIONAL', 'Conditionally Promoted'),
        ('REPEATED', 'Repeated'),
        ('EXPELLED', 'Expelled'),
        ('TRANSFERRED', 'Transferred'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='student_promotions')

    student = models.ForeignKey(
        'students.Student',
        on_delete=models.CASCADE,
        related_name='promotions'
    )

    # Promotion details
    from_grade_level = models.ForeignKey(
        'students.GradeLevel',
        on_delete=models.CASCADE,
        related_name='promotions_from',
        help_text="Grade level being promoted FROM"
    )
    from_school_class = models.ForeignKey(
        'SchoolClass',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='promotions_from',
        help_text="Class being promoted FROM"
    )

    to_grade_level = models.ForeignKey(
        'students.GradeLevel',
        on_delete=models.CASCADE,
        related_name='promotions_to',
        help_text="Grade level being promoted TO"
    )
    to_school_class = models.ForeignKey(
        'SchoolClass',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='promotions_to',
        help_text="Class being promoted TO"
    )

    # Academic performance at promotion time
    overall_average = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Overall average at time of promotion"
    )
    subjects_passed = models.PositiveIntegerField(
        default=0,
        help_text="Number of subjects passed"
    )
    subjects_failed = models.PositiveIntegerField(
        default=0,
        help_text="Number of subjects failed"
    )
    failed_subjects = models.JSONField(
        default=list,
        help_text="List of failed subject names"
    )

    # Attendance
    attendance_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Attendance percentage at time of promotion"
    )

    # Status
    status = models.CharField(
        max_length=15,
        choices=STATUS_CHOICES,
        default='PENDING'
    )
    is_automatic = models.BooleanField(
        default=False,
        help_text="Was this promotion automatically processed?"
    )

    # Promotion notes
    notes = models.TextField(blank=True, null=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_promotions'
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    # Promotion batch
    promotion_batch = models.ForeignKey(
        'PromotionBatch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='promotions'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = managers.TenantManager()

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.student.user.get_full_name()} - {self.from_grade_level.name} → {self.to_grade_level.name} ({self.status})"


class PromotionBatch(models.Model):
    """
    Groups promotions together for batch processing.
    """
    STATUS_CHOICES = (
        ('DRAFT', 'Draft'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='promotion_batches')

    name = models.CharField(max_length=200, help_text="e.g., '2025 Academic Year Promotion'")
    academic_year = models.ForeignKey(
        'school.AcademicYear',
        on_delete=models.CASCADE,
        related_name='promotion_batches'
    )
    academic_term = models.ForeignKey(
        'school.AcademicTerm',
        on_delete=models.CASCADE,
        related_name='promotion_batches',
        help_text="The term being evaluated for promotion"
    )

    # Statistics
    total_students = models.PositiveIntegerField(default=0)
    promoted = models.PositiveIntegerField(default=0)
    conditional = models.PositiveIntegerField(default=0)
    repeated = models.PositiveIntegerField(default=0)

    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='DRAFT')
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processed_promotion_batches'
    )
    processed_at = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = managers.TenantManager()

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.academic_year})"