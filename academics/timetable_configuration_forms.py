from django import forms

from .timetable_configuration_model import DAY_CHOICES, BLOCK_TYPES, TimetableConfiguration
from .timetable_schedule_block_model import TimetableScheduleBlock


class TimetableConfigurationForm(forms.ModelForm):
    DAYS = forms.MultipleChoiceField(
        choices=DAY_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=True,
        label='School days',
    )

    def __init__(self, *args, config=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = config or self.instance
        self.fields['DAYS'].initial = list((self.config.days if self.config else None) or ['MON', 'TUE', 'WED', 'THU', 'FRI'])

    class Meta:
        model = TimetableConfiguration
        fields = ['template_name', 'start_time', 'period_length_minutes', 'periods_per_day', 'allow_double_periods']
        widgets = {
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'period_length_minutes': forms.NumberInput(attrs={'min': 10, 'max': 180}),
            'periods_per_day': forms.NumberInput(attrs={'min': 1, 'max': 15}),
        }

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('DAYS'):
            self.add_error('DAYS', 'Select at least one school day.')
        cleaned['days'] = cleaned.get('DAYS') or []
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.days = self.cleaned_data['days']
        if commit:
            obj.save()
        return obj


class TimetableScheduleBlockForm(forms.ModelForm):
    day = forms.ChoiceField(
        choices=[('', 'All configured days')] + DAY_CHOICES,
        required=False,
        label='Day',
    )
    block_type = forms.ChoiceField(choices=BLOCK_TYPES, label='Type')

    class Meta:
        model = TimetableScheduleBlock
        fields = ['day', 'block_type', 'label', 'after_period', 'minutes', 'is_active']
        widgets = {
            'label': forms.TextInput(attrs={'placeholder': 'e.g. Morning Break'}),
            'after_period': forms.NumberInput(attrs={'min': 0, 'max': 14}),
            'minutes': forms.NumberInput(attrs={'min': 1, 'max': 180}),
            'is_active': forms.CheckboxInput(),
        }

    def __init__(self, *args, periods_per_day=8, **kwargs):
        super().__init__(*args, **kwargs)
        self.periods_per_day = periods_per_day
        self.fields['after_period'].widget.attrs['max'] = max(0, periods_per_day - 1)

    def clean(self):
        cleaned = super().clean()
        after = cleaned.get('after_period')
        minutes = cleaned.get('minutes')
        if after is not None and after >= self.periods_per_day:
            self.add_error('after_period', f'Must be before the final period ({self.periods_per_day}).')
        if minutes is not None and minutes <= 0:
            self.add_error('minutes', 'Duration must be greater than zero.')
        if not (cleaned.get('label') or '').strip():
            self.add_error('label', 'A block label is required.')
        return cleaned

from django.forms import BaseInlineFormSet, inlineformset_factory


class TimetableScheduleBlockFormSet(BaseInlineFormSet):
    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs['periods_per_day'] = getattr(self, 'periods_per_day', 8)
        return kwargs

    def __init__(self, *args, periods_per_day=8, **kwargs):
        self.periods_per_day = periods_per_day
        super().__init__(*args, **kwargs)

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        seen = set()
        scoped = []
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get('DELETE'):
                continue
            if not form.cleaned_data.get('is_active'):
                continue
            day = form.cleaned_data.get('day') or None
            after = form.cleaned_data.get('after_period')
            if after is None:
                continue
            key = (day, after)
            if key in seen:
                form.add_error('after_period', 'Another active block already uses this position for the same day scope.')
            seen.add(key)
            scoped.append((day, after, form))
        for day, after, form in scoped:
            if day is not None and (None, after) in seen:
                form.add_error('after_period', 'A specific-day block cannot share a position with an all-days block. Remove one or move it to another period.')


TimetableScheduleBlockFormSet = inlineformset_factory(
    TimetableConfiguration,
    TimetableScheduleBlock,
    form=TimetableScheduleBlockForm,
    formset=TimetableScheduleBlockFormSet,
    extra=2,
    can_delete=True,
    max_num=10,
    validate_max=True,
)
