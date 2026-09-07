# library/models.py
from django.db import models
from django.utils import timezone
from django.conf import settings
from school.models import School
from school.services import managers
from students.models import Student
from staff.models import StaffProfile
import uuid


class BookCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='library_categories')
    name = models.CharField(max_length=100, help_text="e.g., Fiction, Science, Mathematics")
    description = models.TextField(blank=True, null=True)

    objects = managers.TenantManager()

    class Meta:
        unique_together = ('school', 'name')
        verbose_name_plural = 'Book Categories'

    def __str__(self):
        return self.name


class Book(models.Model):
    STATUS_CHOICES = (
        ('AVAILABLE', 'Available'),
        ('BORROWED', 'Borrowed'),
        ('LOST', 'Lost'),
        ('DAMAGED', 'Damaged'),
        ('RESERVED', 'Reserved'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='library_books')

    title = models.CharField(max_length=255)
    author = models.CharField(max_length=200)
    isbn = models.CharField(max_length=20, blank=True, null=True, help_text="International Standard Book Number")
    category = models.ForeignKey(BookCategory, on_delete=models.PROTECT, related_name='books')

    # Physical attributes
    shelf_location = models.CharField(max_length=50, blank=True, null=True, help_text="e.g., A1, Shelf 3")
    total_copies = models.PositiveIntegerField(default=1)
    available_copies = models.PositiveIntegerField(default=1)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='AVAILABLE')
    description = models.TextField(blank=True, null=True)
    cover_image = models.ImageField(upload_to='library_covers/', blank=True, null=True)

    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = managers.TenantManager()

    class Meta:
        ordering = ['title']

    def __str__(self):
        return f"{self.title} by {self.author}"


class BookBorrowing(models.Model):
    STATUS_CHOICES = (
        ('ACTIVE', 'Active'),
        ('RETURNED', 'Returned'),
        ('OVERDUE', 'Overdue'),
        ('LOST', 'Lost'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='library_borrowings')

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='borrowings')

    # Polymorphic borrower (Either a Student or a Staff member)
    borrowed_by_student = models.ForeignKey(Student, on_delete=models.CASCADE, null=True, blank=True,
                                            related_name='library_borrowings')
    borrowed_by_staff = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, null=True, blank=True,
                                          related_name='library_borrowings')

    borrowed_at = models.DateTimeField(auto_now_add=True)
    due_date = models.DateField()
    returned_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')
    notes = models.TextField(blank=True, null=True)

    objects = managers.TenantManager()

    class Meta:
        ordering = ['-borrowed_at']

    def get_borrower_name(self):
        if self.borrowed_by_student:
            return self.borrowed_by_student.user.get_full_name()
        elif self.borrowed_by_staff:
            return self.borrowed_by_staff.user.get_full_name()
        return "Unknown"

    def __str__(self):
        return f"{self.book.title} borrowed by {self.get_borrower_name()}"