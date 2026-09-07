from django.contrib import admin
from .models import Assessment, AssessmentQuestion, Grade, TerminalResult


@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = ('title', 'subject', 'score_component', 'assessment_type', 'academic_term', 'max_score', 'school')
    list_filter = ('score_component', 'assessment_type', 'academic_term', 'school')
    search_fields = ('title', 'subject')


@admin.register(AssessmentQuestion)
class AssessmentQuestionAdmin(admin.ModelAdmin):
    list_display = ('assessment', 'order', 'question_type', 'marks')
    list_filter = ('question_type',)
    search_fields = ('question_text',)


@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ('student', 'assessment', 'score_achieved', 'graded_by', 'updated_at')
    list_filter = ('assessment__score_component', 'assessment')
    search_fields = ('student__user__first_name', 'student__user__last_name', 'student__admission_number')


@admin.register(TerminalResult)
class TerminalResultAdmin(admin.ModelAdmin):
    list_display = ('student', 'school_class', 'subject', 'academic_term', 'class_score', 'exam_score', 'final_score', 'grade', 'status')
    list_filter = ('academic_term', 'school_class', 'status', 'grade')
    search_fields = ('student__user__first_name', 'student__user__last_name', 'student__admission_number', 'subject')
    readonly_fields = ('final_score', 'grade', 'remark', 'created_at', 'updated_at')
