from django.contrib import admin
from .models import WeeklyLessonPlan


@admin.register(WeeklyLessonPlan)
class WeeklyLessonPlanAdmin(admin.ModelAdmin):
    list_display = ('topic', 'school', 'teacher', 'school_class', 'subject', 'week_start', 'status')
    list_filter = ('school', 'status', 'academic_term')
    search_fields = ('topic', 'teacher__user__first_name', 'teacher__user__last_name', 'school_class__name', 'subject__name')
    readonly_fields = ('teacher_submitted_at', 'reviewed_at', 'created_at', 'updated_at')
