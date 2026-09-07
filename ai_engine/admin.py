from django.contrib import admin
from .models import *


class StudentRiskAssessmentInline(admin.TabularInline):
    model = StudentRiskAssessment
    extra = 0
    fields = ('student', 'risk_score', 'risk_band', 'attendance_rate', 'grade_average', 'fee_overdue_amount')
    readonly_fields = fields


@admin.register(RiskAssessmentRun)
class RiskAssessmentRunAdmin(admin.ModelAdmin):
    list_display = ('academic_term', 'computed_at', 'status', 'students_assessed', 'high_risk_count', 'critical_risk_count', 'school')
    list_filter = ('status', 'school')
    inlines = [StudentRiskAssessmentInline]


@admin.register(StudentRiskAssessment)
class StudentRiskAssessmentAdmin(admin.ModelAdmin):
    list_display = ('student', 'risk_band', 'risk_score', 'attendance_rate', 'grade_average', 'fee_overdue_amount', 'school')
    list_filter = ('risk_band', 'school')
    search_fields = ('student__user__first_name', 'student__user__last_name', 'student__admission_number')


class ReportCardInline(admin.TabularInline):
    model = ReportCard
    extra = 0
    fields = ('student', 'overall_average', 'attendance_rate', 'is_finalized')
    readonly_fields = fields


@admin.register(ReportCardBatch)
class ReportCardBatchAdmin(admin.ModelAdmin):
    list_display = ('academic_term', 'generated_at', 'status', 'students_processed', 'students_skipped_finalized', 'school')
    list_filter = ('status', 'school')


@admin.register(ReportCard)
class ReportCardAdmin(admin.ModelAdmin):
    list_display = ('student', 'academic_term', 'overall_average', 'attendance_rate', 'is_finalized', 'school')
    list_filter = ('is_finalized', 'school')
    search_fields = ('student__user__first_name', 'student__user__last_name', 'student__admission_number')


@admin.register(PaymentReminder)
class PaymentReminderAdmin(admin.ModelAdmin):
    list_display = ('student', 'invoice', 'is_sent', 'generated_at', 'sent_at', 'school')
    list_filter = ('is_sent', 'school')
    search_fields = ('student__user__first_name', 'student__user__last_name')


class GeneratedQuestionInline(admin.TabularInline):
    model = GeneratedQuestion
    extra = 0
    fields = ('order', 'question_type', 'question_text', 'points', 'is_ai_generated')


@admin.register(GeneratedExam)
class GeneratedExamAdmin(admin.ModelAdmin):
    list_display = ('title', 'subject', 'grade_level', 'difficulty', 'created_by', 'created_at', 'school')
    list_filter = ('subject', 'difficulty', 'school')
    search_fields = ('title', 'subject', 'topic')
    inlines = [GeneratedQuestionInline]


@admin.register(ParentChatMessage)
class ParentChatMessageAdmin(admin.ModelAdmin):
    list_display = ('parent', 'student', 'sender', 'created_at', 'school')
    list_filter = ('sender', 'school')
    search_fields = ('parent__username', 'student__user__first_name', 'student__user__last_name')


@admin.register(AIRequest)
class AIRequestAdmin(admin.ModelAdmin):

    list_display = (
        "created_at",
        "school",
        "user",
        "engine",
        "status",
        "execution_time",
    )

    list_filter = (
        "engine",
        "status",
        "created_at",
    )

    search_fields = (
        "user__username",
        "prompt",
        "response",
    )

    readonly_fields = (
        "execution_time",
        "created_at",
    )

admin.site.register(AIConversation)
admin.site.register(AIMessage)
admin.site.register(AITask)

@admin.register(AIActivity)
class AIActivityAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "activity_type",
        "status",
        "school",
        "created_at",
    )

    list_filter = (
        "activity_type",
        "status",
        "school",
    )

    search_fields = (
        "title",
        "description",
    )

    ordering = ("-created_at",)


@admin.register(SubstituteAssignment)
class SubstituteAssignmentAdmin(admin.ModelAdmin):
    list_display = ('absence', 'timetable_entry', 'suggested_substitute', 'confirmed_substitute', 'status', 'school')
    list_filter = ('status', 'school')


@admin.register(AIInsight)
class AIInsightAdmin(admin.ModelAdmin):

    list_display=(

        "title",

        "level",

        "source",

        "school",

        "created_at",

        "is_read",

    )

    list_filter=(

        "level",

        "source",

        "is_read",

    )

    search_fields=(

        "title",

        "message",

    )


@admin.register(AIAutomationTask)
class AIAutomationTaskAdmin(admin.ModelAdmin):

    list_display = (

        "title",

        "task_type",

        "priority",

        "status",

        "school",

        "created_at",

    )

    list_filter = (

        "priority",

        "status",

        "task_type",

    )

    search_fields = (

        "title",

        "description",

    )

    readonly_fields = (

        "created_at",

        "completed_at",

        "approved_at",

    )


# ============================================================================
# STEP 1 — TOOL EXECUTION AUDIT LOG
# ============================================================================

@admin.register(ToolExecutionLog)
class ToolExecutionLogAdmin(admin.ModelAdmin):
    list_display = ('tool_name', 'status', 'user', 'school', 'duration_ms', 'created_at')
    list_filter = ('status', 'tool_name', 'school')
    search_fields = ('tool_name', 'error_message', 'user__username')
    readonly_fields = (
        'id', 'school', 'user', 'tool_name', 'required_capability', 'arguments',
        'status', 'result_summary', 'error_message', 'duration_ms', 'created_at',
    )
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# ============================================================================
# STEP 2 — SCHOOL AI MEMORY
# ============================================================================

@admin.register(SchoolAIMemory)
class SchoolAIMemoryAdmin(admin.ModelAdmin):
    list_display = ('key', 'scope', 'memory_type', 'importance', 'school', 'user', 'is_active', 'updated_at')
    list_filter = ('scope', 'memory_type', 'importance', 'is_active', 'school')
    search_fields = ('key', 'content', 'user__username')
    readonly_fields = ('id', 'created_at', 'updated_at')
    ordering = ('-updated_at',)


# ============================================================================
# STEP 3 — GHANA EDUCATION KNOWLEDGE BASE (RAG)
# ============================================================================

@admin.register(GhanaEducationKnowledgeDocument)
class GhanaEducationKnowledgeDocumentAdmin(admin.ModelAdmin):
    list_display = ('title', 'domain', 'source_name', 'is_active', 'last_verified_at', 'updated_at')
    list_filter = ('domain', 'source_name', 'is_active')
    search_fields = ('title', 'content', 'domain')
    readonly_fields = ('id', 'created_at', 'updated_at')
    ordering = ('domain', 'title')


@admin.register(ReportCommentBatch)
class ReportCommentBatchAdmin(admin.ModelAdmin):
    list_display = ('generated_at', 'academic_term', 'school_class', 'status', 'students_processed', 'teacher_comments_generated', 'headteacher_comments_generated', 'failures')
    list_filter = ('status', 'only_missing', 'regenerate_ai', 'generate_teacher', 'generate_headteacher')
    search_fields = ('school__name', 'academic_term__name', 'school_class__name')
    readonly_fields = ('generated_at',)
