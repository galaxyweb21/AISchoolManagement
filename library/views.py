from core.pagination import paginate_queryset
# library/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db import transaction

from .models import Book, BookCategory, BookBorrowing
from students.models import Student
from staff.models import StaffProfile
from django.http import JsonResponse


@login_required
def library_dashboard(request):
    school = request.user.school

    # Metrics
    total_books = Book.objects.filter(school=school).count()
    available_books = Book.objects.filter(school=school, status='AVAILABLE').count()
    active_borrowings = BookBorrowing.objects.filter(school=school, status='ACTIVE').count()
    overdue_borrowings = BookBorrowing.objects.filter(school=school, status='OVERDUE').count()

    recent_borrowings = BookBorrowing.objects.filter(school=school).select_related('book').order_by('-borrowed_at')[:10]

    context = {
        'total_books': total_books,
        'available_books': available_books,
        'active_borrowings': active_borrowings,
        'overdue_borrowings': overdue_borrowings,
        'recent_borrowings': recent_borrowings,
    }
    return render(request, 'library/dashboard.html', context)


@login_required
def book_list(request):
    school = request.user.school
    books = Book.objects.filter(school=school).select_related('category').order_by('title')
    return render(request, 'library/book_list.html', {'books': paginate_queryset(books, request)})


@login_required
def book_detail(request, book_id):
    school = request.user.school
    book = get_object_or_404(Book, id=book_id, school=school)
    return render(request, 'library/book_detail.html', {'book': book})


@login_required
def book_create(request):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school
    categories = BookCategory.objects.filter(school=school)

    if request.method == 'GET':
        return render(request, 'library/book_form_modal.html', {
            'mode': 'create',
            'categories': categories,
            'action_url': 'library:book_create'
        })

    title = request.POST.get('title', '').strip()
    author = request.POST.get('author', '').strip()
    isbn = request.POST.get('isbn', '').strip()
    category_id = request.POST.get('category', '').strip()
    total_copies = int(request.POST.get('total_copies', 1))
    shelf_location = request.POST.get('shelf_location', '').strip()
    description = request.POST.get('description', '').strip()

    if not all([title, author, category_id]):
        return JsonResponse({'success': False, 'error': "Title, Author, and Category are required."})

    category = get_object_or_404(BookCategory, id=category_id, school=school)
    Book.objects.create(
        school=school, title=title, author=author, isbn=isbn,
        category=category, total_copies=total_copies,
        available_copies=total_copies, shelf_location=shelf_location,
        description=description
    )
    return JsonResponse({'success': True, 'message': f"Book '{title}' added successfully."})


@login_required
def book_edit(request, book_id):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school
    book = get_object_or_404(Book, id=book_id, school=school)
    categories = BookCategory.objects.filter(school=school)

    if request.method == 'GET':
        return render(request, 'library/book_form_modal.html', {
            'mode': 'edit',
            'book': book,
            'categories': categories,
            'action_url': 'library:book_edit'
        })

    title = request.POST.get('title', '').strip()
    author = request.POST.get('author', '').strip()
    isbn = request.POST.get('isbn', '').strip()
    category_id = request.POST.get('category', '').strip()
    total_copies = int(request.POST.get('total_copies', book.total_copies))
    shelf_location = request.POST.get('shelf_location', '').strip()
    description = request.POST.get('description', '').strip()

    if not all([title, author, category_id]):
        return JsonResponse({'success': False, 'error': "Title, Author, and Category are required."})

    category = get_object_or_404(BookCategory, id=category_id, school=school)
    book.title = title
    book.author = author
    book.isbn = isbn
    book.category = category
    book.total_copies = total_copies
    book.available_copies = total_copies  # Simplified for demo (you can adjust logic here)
    book.shelf_location = shelf_location
    book.description = description
    book.save()

    return JsonResponse({'success': True, 'message': f"Book '{title}' updated successfully."})


@login_required
def book_delete(request, book_id):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school
    book = get_object_or_404(Book, id=book_id, school=school)

    if request.method == 'GET':
        return render(request, 'library/book_delete_modal.html', {
            'book': book,
            'action_url': 'library:book_delete'
        })

    book.delete()
    return JsonResponse({'success': True, 'message': f"Book '{book.title}' deleted successfully."})


@login_required
def borrowing_list(request):
    school = request.user.school
    borrowings = BookBorrowing.objects.filter(school=school).select_related('book', 'borrowed_by_student__user',
                                                                            'borrowed_by_staff__user').order_by(
        '-borrowed_at')
    return render(request, 'library/borrowing_list.html', {'borrowings': paginate_queryset(borrowings, request)})


@login_required
def borrowing_create(request):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'TEACHER']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school

    if request.method == 'GET':
        books = Book.objects.filter(school=school, status='AVAILABLE')
        students = Student.objects.filter(school=school, is_active=True)
        staff_members = StaffProfile.objects.filter(school=school, is_active=True)

        return render(request, 'library/borrowing_form_modal.html', {
            'books': books,
            'students': students,
            'staff_members': staff_members,
            'action_url': 'library:borrowing_create'
        })

    book_id = request.POST.get('book', '').strip()
    borrower_type = request.POST.get('borrower_type', '').strip()
    borrower_id = request.POST.get('borrower_id', '').strip()
    due_date = request.POST.get('due_date', '').strip()

    # Logging to terminal to help debug if fields are missing
    print(f"DEBUG: book={book_id}, type={borrower_type}, id={borrower_id}, date={due_date}")

    if not all([book_id, borrower_type, borrower_id, due_date]):
        return JsonResponse({
            'success': False,
            'error': "All fields are required. Please ensure you have selected a Book, Borrower Type, Borrower, and Due Date."
        })

    try:
        with transaction.atomic():
            book = get_object_or_404(Book, id=book_id, school=school)

            # Decrease available copies
            if book.available_copies > 0:
                book.available_copies -= 1
                if book.available_copies == 0:
                    book.status = 'BORROWED'
                book.save()

            if borrower_type == 'STUDENT':
                borrower_student = get_object_or_404(Student, id=borrower_id, school=school)
                BookBorrowing.objects.create(
                    school=school, book=book, borrowed_by_student=borrower_student, due_date=due_date
                )
            else:
                borrower_staff = get_object_or_404(StaffProfile, id=borrower_id, school=school)
                BookBorrowing.objects.create(
                    school=school, book=book, borrowed_by_staff=borrower_staff, due_date=due_date
                )

        return JsonResponse({'success': True, 'message': f"Book '{book.title}' borrowed successfully."})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def return_book(request, borrowing_id):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'TEACHER']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school
    borrowing = get_object_or_404(BookBorrowing, id=borrowing_id, school=school)

    if request.method == 'GET':
        return render(request, 'library/borrowing_return_modal.html', {
            'borrowing': borrowing,
            'action_url': 'library:return_book'
        })

    with transaction.atomic():
        borrowing.returned_at = timezone.now()
        borrowing.status = 'RETURNED'
        borrowing.save()

        book = borrowing.book
        book.available_copies += 1
        if book.available_copies > 0:
            book.status = 'AVAILABLE'
        book.save()

    return JsonResponse({'success': True, 'message': f"Book '{borrowing.book.title}' returned."})


@login_required
def mark_lost(request, borrowing_id):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'TEACHER']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school
    borrowing = get_object_or_404(BookBorrowing, id=borrowing_id, school=school)

    if request.method == 'GET':
        return render(request, 'library/borrowing_lost_modal.html', {
            'borrowing': borrowing,
            'action_url': 'library:mark_lost'
        })

    with transaction.atomic():
        borrowing.status = 'LOST'
        borrowing.save()

        book = borrowing.book
        book.status = 'LOST'
        book.available_copies = 0
        book.save()

    return JsonResponse({'success': True, 'message': f"Book '{borrowing.book.title}' marked as lost."})


# ============================================================
# BOOK CATEGORY VIEWS - FULL MODAL SUPPORT
# ============================================================

@login_required
def book_category_list(request):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        messages.error(request, "You don't have permission to manage book categories.")
        return redirect('dashboard')

    school = request.user.school
    categories = BookCategory.objects.filter(school=school).order_by('name')
    return render(request, 'library/book_category_list.html', {'categories': paginate_queryset(categories, request)})


@login_required
def book_category_create(request):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    school = request.user.school

    if request.method == 'GET':
        return render(request, 'library/book_category_form_modal.html', {
            'mode': 'create',
            'action_url': 'library:book_category_create'
        })

    name = request.POST.get('name', '').strip()
    description = request.POST.get('description', '').strip()

    if not name:
        return JsonResponse({'success': False, 'error': "Category name is required."})

    if BookCategory.objects.filter(school=school, name=name).exists():
        return JsonResponse({'success': False, 'error': f"A category named '{name}' already exists."})

    BookCategory.objects.create(school=school, name=name, description=description)
    return JsonResponse({'success': True, 'message': f"Category '{name}' created successfully."})


@login_required
def book_category_edit(request, category_id):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    school = request.user.school
    category = get_object_or_404(BookCategory, id=category_id, school=school)

    if request.method == 'GET':
        return render(request, 'library/book_category_form_modal.html', {
            'mode': 'edit',
            'category': category,
            'action_url': 'library:book_category_edit'
        })

    name = request.POST.get('name', '').strip()
    description = request.POST.get('description', '').strip()

    if not name:
        return JsonResponse({'success': False, 'error': "Category name is required."})

    if BookCategory.objects.filter(school=school, name=name).exclude(id=category.id).exists():
        return JsonResponse({'success': False, 'error': f"A category named '{name}' already exists."})

    category.name = name
    category.description = description
    category.save()
    return JsonResponse({'success': True, 'message': f"Category '{name}' updated successfully."})


@login_required
def book_category_delete(request, category_id):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    school = request.user.school
    category = get_object_or_404(BookCategory, id=category_id, school=school)

    if request.method == 'GET':
        return render(request, 'library/book_category_delete_modal.html', {
            'category': category,
            'action_url': 'library:book_category_delete'
        })

    # Check if any books are assigned to this category
    if category.books.exists():
        return JsonResponse({
            'success': False,
            'error': f"Cannot delete '{category.name}' because it has {category.books.count()} book(s) assigned to it. Please reassign or delete those books first."
        })

    category.delete()
    return JsonResponse({'success': True, 'message': f"Category '{category.name}' deleted successfully."})
