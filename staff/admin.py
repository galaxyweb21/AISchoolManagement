from django.contrib import admin
from .models import Teacher, TeacherAbsence


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ('user', 'staff_number', 'department', 'max_periods_per_week', 'is_active', 'school')
    list_filter = ('department', 'is_active', 'school')
    search_fields = ('staff_number', 'user__first_name', 'user__last_name')
    filter_horizontal = ('subjects',)


@admin.register(TeacherAbsence)
class TeacherAbsenceAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'date', 'reason', 'reported_by', 'school')
    list_filter = ('reason', 'school')
    search_fields = ('teacher__user__first_name', 'teacher__user__last_name')
