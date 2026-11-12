from django.contrib import admin
from .models import (
    Subject, SchoolClass, ClassSubjectRequirement, Room, TimeSlot,
    Timetable, TimetableEntry,
)


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'requires_lab', 'school')
    list_filter = ('requires_lab', 'school')
    search_fields = ('name', 'code')


@admin.register(SchoolClass)
class SchoolClassAdmin(admin.ModelAdmin):
    list_display = ('name', 'grade_level', 'student_count', 'homeroom_teacher', 'school')
    list_filter = ('grade_level', 'school')
    search_fields = ('name',)


@admin.register(ClassSubjectRequirement)
class ClassSubjectRequirementAdmin(admin.ModelAdmin):
    list_display = ('school_class', 'subject', 'periods_per_week')
    list_filter = ('school_class', 'subject')


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ('name', 'capacity', 'is_lab', 'school')
    list_filter = ('is_lab', 'school')


@admin.register(TimeSlot)
class TimeSlotAdmin(admin.ModelAdmin):
    list_display = ('day', 'period_index', 'start_time', 'end_time', 'school')
    list_filter = ('day', 'school')
    ordering = ('day', 'period_index')


class TimetableEntryInline(admin.TabularInline):
    model = TimetableEntry
    extra = 0
    autocomplete_fields = ()


@admin.register(Timetable)
class TimetableAdmin(admin.ModelAdmin):
    list_display = ('academic_term', 'generated_at', 'fitness_score', 'hard_conflicts', 'soft_conflicts', 'is_published', 'school')
    list_filter = ('is_published', 'school')
    inlines = [TimetableEntryInline]
