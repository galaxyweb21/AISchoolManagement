from django.contrib import admin
from .models import OnlineExam, OnlineExamQuestion, ExamAttempt, ExamAnswer

class OnlineExamQuestionInline(admin.TabularInline):
    model = OnlineExamQuestion
    extra = 0

@admin.register(OnlineExam)
class OnlineExamAdmin(admin.ModelAdmin):
    list_display = ('title', 'school', 'school_class', 'subject', 'status', 'opens_at', 'closes_at')
    list_filter = ('status', 'school', 'academic_term')
    search_fields = ('title', 'school_class__name', 'subject__name')
    inlines = [OnlineExamQuestionInline]

@admin.register(ExamAttempt)
class ExamAttemptAdmin(admin.ModelAdmin):
    list_display = ('exam', 'student', 'status', 'grading_status', 'score_awarded', 'total_marks', 'submitted_at')
    list_filter = ('status', 'grading_status', 'exam__school')
    search_fields = ('exam__title', 'student__user__first_name', 'student__user__last_name')

admin.site.register(ExamAnswer)
