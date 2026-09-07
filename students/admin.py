from django.contrib import admin
from .models import Student


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('user', 'admission_number', 'grade_level', 'parent', 'is_active', 'school')
    list_filter = ('grade_level', 'is_active', 'school')
    search_fields = ('admission_number', 'user__first_name', 'user__last_name')
