# academics/forms.py (create this file)
from django import forms
from .models import TimeSlot


class TimeSlotForm(forms.ModelForm):
    class Meta:
        model = TimeSlot
        fields = ['day', 'period_index', 'start_time', 'end_time']
        widgets = {
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'type': 'time'}),
        }

    def clean_start_time(self):
        start_time = self.cleaned_data.get('start_time')
        if start_time:
            # Ensure it's a time object
            return start_time
        return None

    def clean_end_time(self):
        end_time = self.cleaned_data.get('end_time')
        if end_time:
            return end_time
        return None

    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')

        if start_time and end_time and start_time >= end_time:
            raise forms.ValidationError('Start time must be before end time.')

        return cleaned_data


DAY_CHOICES = TimeSlot.DAY_CHOICES


class GESScheduleForm(forms.Form):
    """
    Lets an admin generate a full week of TimeSlots from the GES
    standard 8-period day (or a customized variant of it) instead of
    entering each period by hand.
    """
    start_time = forms.TimeField(
        initial='08:00',
        widget=forms.TimeInput(attrs={'type': 'time'}),
        help_text="When the first period of the day begins.",
    )
    period_length_minutes = forms.IntegerField(
        initial=50, min_value=10, max_value=180,
        help_text="GES standard: 50 minutes per period.",
    )
    periods_per_day = forms.IntegerField(
        initial=8, min_value=1, max_value=15,
        help_text="GES standard: 8 periods per day.",
    )
    first_break_after_period = forms.IntegerField(
        initial=2, min_value=1,
        help_text="Mid-morning break, placed after this period.",
    )
    first_break_minutes = forms.IntegerField(initial=30, min_value=0, max_value=120)
    second_break_after_period = forms.IntegerField(
        initial=5, min_value=1,
        help_text="Lunch break, placed after this period.",
    )
    second_break_minutes = forms.IntegerField(initial=30, min_value=0, max_value=120)
    days = forms.MultipleChoiceField(
        choices=DAY_CHOICES,
        initial=[code for code, _ in DAY_CHOICES],
        widget=forms.CheckboxSelectMultiple,
    )
    replace_existing = forms.BooleanField(
        required=False, initial=False,
        help_text="Delete and fully regenerate periods for the selected days. "
                   "Leave unchecked to only fill in periods that don't exist yet.",
    )

    def clean(self):
        cleaned_data = super().clean()
        periods_per_day = cleaned_data.get('periods_per_day')
        first_after = cleaned_data.get('first_break_after_period')
        second_after = cleaned_data.get('second_break_after_period')

        if periods_per_day and first_after and first_after >= periods_per_day:
            self.add_error(
                'first_break_after_period',
                f"Must be less than the total periods per day ({periods_per_day})."
            )
        if periods_per_day and second_after and second_after >= periods_per_day:
            self.add_error(
                'second_break_after_period',
                f"Must be less than the total periods per day ({periods_per_day})."
            )
        if first_after and second_after and first_after == second_after:
            self.add_error(
                'second_break_after_period',
                "The two breaks can't be placed after the same period."
            )
        return cleaned_data

    def to_service_kwargs(self):
        """Translate cleaned form data into generate_ges_standard_timeslots() kwargs."""
        data = self.cleaned_data
        breaks = {}
        if data.get('first_break_minutes'):
            breaks[data['first_break_after_period']] = data['first_break_minutes']
        if data.get('second_break_minutes'):
            breaks[data['second_break_after_period']] = data['second_break_minutes']
        return {
            'start_time': data['start_time'],
            'period_length_minutes': data['period_length_minutes'],
            'periods_per_day': data['periods_per_day'],
            'breaks': breaks,
            'days': data['days'],
            'replace_existing': data['replace_existing'],
        }