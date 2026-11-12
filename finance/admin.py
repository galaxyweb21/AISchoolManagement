# finance/admin.py - Add admin for new models

from django.contrib import admin
from .models import ClassAddOnStructure, ClassAddOnItem

class ClassAddOnItemInline(admin.TabularInline):
    model = ClassAddOnItem
    extra = 1
    fields = ['grade_level', 'school_class', 'amount', 'first_term_amount', 'second_term_amount', 'third_term_amount', 'is_active']
    raw_id_fields = ['grade_level', 'school_class']

@admin.register(ClassAddOnStructure)
class ClassAddOnStructureAdmin(admin.ModelAdmin):
    list_display = ['name', 'fee_category', 'term_type', 'apply_to_new_students_only', 'is_required', 'is_active']
    list_filter = ['term_type', 'apply_to_new_students_only', 'is_required', 'is_active']
    search_fields = ['name', 'description']
    inlines = [ClassAddOnItemInline]
    fields = ['school', 'name', 'fee_category', 'description', 'term_type', 'custom_terms',
              'apply_to_new_students_only', 'is_required', 'is_active']
