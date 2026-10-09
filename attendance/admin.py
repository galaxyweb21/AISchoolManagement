from django.contrib import admin

from .models import Attendance, StaffAttendance, StaffFaceProfile


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('student', 'school', 'date', 'status', 'marked_by')
    list_filter = ('school', 'date', 'status')
    search_fields = ('student__user__first_name', 'student__user__last_name', 'student__admission_number')


@admin.register(StaffAttendance)
class StaffAttendanceAdmin(admin.ModelAdmin):
    list_display = ('staff', 'school', 'date', 'status', 'method', 'check_in', 'check_out')
    list_filter = ('school', 'date', 'status', 'method')
    search_fields = ('staff__user__first_name', 'staff__user__last_name', 'staff__staff_id')
    date_hierarchy = 'date'


@admin.register(StaffFaceProfile)
class StaffFaceProfileAdmin(admin.ModelAdmin):
    list_display = ('staff', 'school', 'is_active', 'registered_at', 'registered_by')
    list_filter = ('school', 'is_active')
    search_fields = ('staff__user__first_name', 'staff__user__last_name', 'staff__staff_id')
