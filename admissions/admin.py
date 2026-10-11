from django.contrib import admin
from .models import AdmissionApplication


@admin.register(AdmissionApplication)
class AdmissionApplicationAdmin(admin.ModelAdmin):
    list_display = ('application_number', 'applicant_name', 'grade_level', 'status', 'academic_year', 'created_at')
    list_filter = ('status', 'grade_level__stage', 'academic_year')
    search_fields = ('application_number', 'first_name', 'last_name', 'parent_name', 'parent_phone')
    readonly_fields = ('application_number', 'created_at', 'updated_at', 'reviewed_at', 'admitted_at')
