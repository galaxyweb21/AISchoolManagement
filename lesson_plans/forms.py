from django import forms
from .models import WeeklyLessonPlan


class WeeklyLessonPlanForm(forms.ModelForm):
    class Meta:
        model = WeeklyLessonPlan
        fields = [
            'submission_method', 'academic_term', 'week_start', 'school_class', 'subject', 'topic', 'subtopic',
            'learning_objectives', 'teaching_resources', 'introduction', 'lesson_development',
            'conclusion', 'assessment', 'reflection', 'supporting_document',
        ]
        widgets = {
            'submission_method': forms.RadioSelect(attrs={'class': 'form-check-input'}),
            'academic_term': forms.Select(attrs={'class': 'form-select'}),
            'week_start': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'school_class': forms.Select(attrs={'class': 'form-select'}),
            'subject': forms.Select(attrs={'class': 'form-select'}),
            'topic': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Fractions and equivalent fractions'}),
            'subtopic': forms.TextInput(attrs={'class': 'form-control'}),
            'learning_objectives': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'By the end of the lesson, learners should be able to…'}),
            'teaching_resources': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'introduction': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'lesson_development': forms.Textarea(attrs={'class': 'form-control', 'rows': 5}),
            'conclusion': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'assessment': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'reflection': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'supporting_document': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.doc,.docx',
            }),
        }

    def clean_supporting_document(self):
        document = self.cleaned_data.get('supporting_document')
        if document and getattr(document, 'size', 0) > 10 * 1024 * 1024:
            raise forms.ValidationError('The lesson note document must be 10 MB or smaller.')
        return document

    def __init__(self, *args, school=None, teacher=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['academic_term'].queryset = self.fields['academic_term'].queryset.filter(academic_year__school=school).select_related('academic_year').order_by('-academic_year__start_date', '-start_date')
        self.fields['school_class'].queryset = self.fields['school_class'].queryset.filter(school=school, is_active=True).select_related('grade_level').order_by('grade_level__order', 'name')
        if teacher:
            from academics.models import TeacherAssignment
            assigned = TeacherAssignment.objects.filter(school=school, teacher=teacher, is_active=True)
            class_ids = assigned.values_list('school_class_id', flat=True).distinct()
            subject_ids = assigned.values_list('subject_id', flat=True).distinct()
            self.fields['school_class'].queryset = self.fields['school_class'].queryset.filter(id__in=class_ids)
            self.fields['subject'].queryset = self.fields['subject'].queryset.filter(school=school, is_active=True, id__in=subject_ids).order_by('name')
        else:
            self.fields['subject'].queryset = self.fields['subject'].queryset.filter(school=school, is_active=True).order_by('name')
        self.fields['supporting_document'].required = False
        self.fields['supporting_document'].help_text = 'PDF, DOC or DOCX, maximum 10 MB.'
        for name in ('academic_term', 'week_start', 'school_class', 'subject', 'topic'):
            self.fields[name].required = True
        method = (self.data.get('submission_method') if self.is_bound else getattr(self.instance, 'submission_method', None)) or WeeklyLessonPlan.METHOD_MANUAL
        self.fields['submission_method'].required = True
        content_fields = ('learning_objectives', 'introduction', 'lesson_development', 'assessment')
        for name in content_fields:
            self.fields[name].required = method != WeeklyLessonPlan.METHOD_UPLOAD
        if method == WeeklyLessonPlan.METHOD_UPLOAD and self.data.get('action', 'draft') == 'submit':
            self.fields['supporting_document'].required = not bool(getattr(self.instance, 'supporting_document', None))

    def clean(self):
        cleaned = super().clean()
        method = cleaned.get('submission_method')
        if method == WeeklyLessonPlan.METHOD_UPLOAD and not cleaned.get('supporting_document'):
            if self.data.get('action', 'draft') == 'submit':
                self.add_error('supporting_document', 'Attach the lesson note document before submitting it for review.')
        if method in (WeeklyLessonPlan.METHOD_MANUAL, WeeklyLessonPlan.METHOD_AI):
            if not cleaned.get('lesson_development'):
                self.add_error('lesson_development', 'Add the lesson procedure or generate it with AI before saving.')
        return cleaned
