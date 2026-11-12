import json
from django import forms
from django.utils import timezone
from school.models import AcademicTerm
from academics.models import SchoolClass, Subject, TeacherAssignment, TeacherClassAssignment
from .models import OnlineExam, OnlineExamQuestion


class OnlineExamForm(forms.ModelForm):
    opens_at = forms.DateTimeField(input_formats=['%Y-%m-%dT%H:%M'], widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'))
    closes_at = forms.DateTimeField(input_formats=['%Y-%m-%dT%H:%M'], widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'))

    class Meta:
        model = OnlineExam
        fields = ('title', 'topic', 'academic_term', 'school_class', 'subject', 'instructions', 'duration_minutes', 'opens_at', 'closes_at', 'student_access_enabled', 'randomize_questions')
        widgets = {'topic': forms.TextInput(attrs={'maxlength': 200, 'placeholder': 'e.g. Fractions, Photosynthesis, Adinkra symbols'}), 'instructions': forms.Textarea(attrs={'rows': 3}), 'duration_minutes': forms.NumberInput(attrs={'min': 1, 'max': 300}), 'student_access_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields['opens_at'].label = 'Exam opens at'
        self.fields['opens_at'].help_text = 'Students can start only at or after this date and time. Uses the school server timezone.'
        self.fields['closes_at'].label = 'Exam closes at'
        self.fields['closes_at'].help_text = 'The server automatically stops attempts at this deadline.'
        self.fields['student_access_enabled'].label = 'Enable online student access'
        self.fields['student_access_enabled'].help_text = 'When checked, students in the selected class can see and sit this exam after it is published. Uncheck for a staff-managed exam that must not appear in the student portal.'
        school = getattr(user, 'school', None)
        self.fields['academic_term'].queryset = AcademicTerm.objects.filter(academic_year__school=school).select_related('academic_year').order_by('-start_date') if school else AcademicTerm.objects.none()
        self.fields['school_class'].queryset = SchoolClass.objects.filter(school=school, is_active=True).select_related('grade_level').order_by('grade_level__order', 'name') if school else SchoolClass.objects.none()
        self.fields['subject'].queryset = Subject.objects.filter(school=school, is_active=True).order_by('name') if school else Subject.objects.none()
        if user and getattr(user, 'role', '') == 'TEACHER' and school:
            teacher = getattr(user, 'teacher_profile', None)
            if teacher:
                assignments = TeacherAssignment.objects.filter(school=school, teacher=teacher, is_active=True)
                class_ids = list(assignments.values_list('school_class_id', flat=True))
                class_ids += list(TeacherClassAssignment.objects.filter(school=school, teacher=teacher, is_active=True).values_list('school_class_id', flat=True))
                self.fields['school_class'].queryset = self.fields['school_class'].queryset.filter(pk__in=set(class_ids))
                self.fields['subject'].queryset = self.fields['subject'].queryset.filter(pk__in=assignments.values_list('subject_id', flat=True))
        for name, field in self.fields.items():
            field.widget.attrs.setdefault('class', 'form-control' if not isinstance(field.widget, forms.CheckboxInput) else 'form-check-input')
            field.widget.attrs.setdefault('placeholder', field.label)

    def clean(self):
        cleaned = super().clean()
        opens_at, closes_at = cleaned.get('opens_at'), cleaned.get('closes_at')
        if opens_at and closes_at and closes_at <= opens_at:
            self.add_error('closes_at', 'The closing time must be later than the opening time.')
        school_class, subject = cleaned.get('school_class'), cleaned.get('subject')
        if self.user and getattr(self.user, 'role', '') == 'TEACHER' and school_class and subject:
            teacher = getattr(self.user, 'teacher_profile', None)
            assigned = bool(teacher and TeacherAssignment.objects.filter(school=self.user.school, teacher=teacher, school_class=school_class, subject=subject, is_active=True).exists())
            if not assigned:
                self.add_error('subject', 'You can only schedule an examination for a class and subject assigned to you.')
        return cleaned


class OnlineExamQuestionForm(forms.ModelForm):
    options_text = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 4, 'placeholder': 'Enter one option per line'}), help_text='For multiple choice, enter one option per line.')

    class Meta:
        model = OnlineExamQuestion
        fields = ('question_type', 'question_text', 'correct_answer', 'marks')
        widgets = {'question_text': forms.Textarea(attrs={'rows': 3}), 'correct_answer': forms.TextInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['options_text'].initial = '\n'.join(self.instance.options or [])
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')

    def clean(self):
        cleaned = super().clean()
        kind = cleaned.get('question_type')
        options = [line.strip() for line in (cleaned.get('options_text') or '').splitlines() if line.strip()]
        answer = (cleaned.get('correct_answer') or '').strip()
        if kind == 'MCQ':
            if len(options) < 2:
                self.add_error('options_text', 'Enter at least two answer options.')
            if answer and options and answer not in options:
                self.add_error('correct_answer', 'The correct answer must exactly match one of the options.')
            if not answer:
                self.add_error('correct_answer', 'Enter the correct option so the system can mark this question.')
        elif kind == 'TRUE_FALSE':
            options = ['True', 'False']
            if answer.lower() not in ('true', 'false'):
                self.add_error('correct_answer', 'Enter True or False as the correct answer.')
            else:
                answer = 'True' if answer.lower() == 'true' else 'False'
        elif kind in ('SHORT_ANSWER', 'ESSAY'):
            options = []
            if kind == 'SHORT_ANSWER' and not answer:
                self.fields['correct_answer'].help_text = 'Optional for manual marking; enter a reference answer to enable exact-match auto-marking.'
        cleaned['parsed_options'] = options
        cleaned['normalized_correct_answer'] = answer
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.options = self.cleaned_data.get('parsed_options', [])
        instance.correct_answer = self.cleaned_data.get('normalized_correct_answer', '')
        if commit:
            instance.save()
        return instance
