# accounts/forms.py
from django import forms
from .models import User
from .models import *


class LoginForm(forms.Form):
    username = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Username'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password'})
    )


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone_number', 'profile_picture']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control'}),
            'profile_picture': forms.FileInput(attrs={'class': 'form-control'}),
        }


class RoleForm(forms.ModelForm):

    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.filter(
            is_active=True
        ),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:

        model = Role

        fields = [
            "name",
            "description",
            "color",
            "icon",
            "is_active",
            "permissions",
        ]

    def save(self, commit=True):

        role = super().save(commit)

        role.permissions.set(
            self.cleaned_data["permissions"]
        )

        return role


class UserRoleForm(forms.ModelForm):

    class Meta:

        model = UserRole

        fields = [

            "user",

            "role",

            "expires_at",

            "notes",

            "is_active",

        ]

        widgets = {

            "expires_at": forms.DateTimeInput(
                attrs={
                    "type": "datetime-local"
                }
            ),

            "notes": forms.Textarea(
                attrs={
                    "rows": 3
                }
            )

        }
