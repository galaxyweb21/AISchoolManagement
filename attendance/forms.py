from django import forms
from .models import StaffAttendanceSettings


class StaffAttendanceSettingsForm(forms.ModelForm):
    class Meta:
        model = StaffAttendanceSettings
        fields = ['check_in_start', 'check_in_end', 'school_end', 'enforce_time_windows']
        widgets = {
            'check_in_start': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'check_in_end': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'school_end': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'enforce_time_windows': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
