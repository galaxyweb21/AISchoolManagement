# ai_engine/views/api.py
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required

import json

from ai_engine.services.services import AIService
from ai_engine.services.ghana_education_context import GHANA_EDUCATION_DOMAINS


@login_required
@require_POST
def api_generate_feedback(request):
    """
    POST API to generate custom feedback on demand.
    Expects JSON payload with student information.
    """
    try:
        data = json.loads(request.body)
        student_name = data.get('student_name')
        subject = data.get('subject')
        grade = data.get('grade')
        attendance = data.get('attendance')
        notes = data.get('notes', '')

        if not all([student_name, subject, grade, attendance]):
            return JsonResponse({'error': 'Missing required fields.'}, status=400)

        ai_feedback = AIService.generate_student_report(
            student_name=student_name,
            subject=subject,
            grade=grade,
            attendance_percentage=attendance,
            teacher_notes=notes
        )
        return JsonResponse({'feedback': ai_feedback})

    except Exception as e:
        return JsonResponse({'error': f"Server error: {str(e)}"}, status=500)


def get_education_tree_api(request):
    """
    Returns the structured hierarchy along with corresponding domain slugs.
    Uses GHANA_EDUCATION_DOMAINS from ghana_education_context.py
    """
    # Build hierarchy from GHANA_EDUCATION_DOMAINS
    hierarchy = []

    # Define the main categories and their children mappings
    category_mappings = {
        "ministry_of_education": {
            "id": "moe",
            "text": "Ministry of Education",
            "icon": "bi-bank",
            "children": ["current_policies"]
        },
        "ges": {
            "id": "ges",
            "text": "Ghana Education Service",
            "icon": "bi-building",
            "children": ["school_administration", "school_leadership"]
        },
        "nacca": {
            "id": "nacca",
            "text": "NaCCA",
            "icon": "bi-book",
            "children": ["curriculum", "assessment"]
        },
        "education_system": {
            "id": "education_system",
            "text": "Education System",
            "icon": "bi-diagram-3",
            "children": ["basic_education", "secondary_education"]
        },
        "teaching_and_learning": {
            "id": "teaching_learning",
            "text": "Teaching & Learning",
            "icon": "bi-chalkboard",
            "children": ["classroom_management", "teacher_development", "ict_in_education"]
        },
        "student_welfare": {
            "id": "student_welfare",
            "text": "Student Welfare",
            "icon": "bi-heart",
            "children": ["guidance_counselling", "inclusive_education", "child_protection", "school_health"]
        },
        "career_guidance": {
            "id": "career_guidance",
            "text": "Career Guidance",
            "icon": "bi-compass",
            "children": ["tertiary_pathways", "scholarships"]
        },
        "educational_planning": {
            "id": "educational_planning",
            "text": "Educational Planning",
            "icon": "bi-bar-chart",
        },
        "education_statistics": {
            "id": "education_statistics",
            "text": "Education Statistics",
            "icon": "bi-graph-up",
        }
    }

    # Build the hierarchy from the mappings
    for slug, config in category_mappings.items():
        node = {
            "id": config["id"],
            "text": config["text"],
            "slug": slug,
            "icon": config.get("icon", "bi-book"),
        }

        # Add children if they exist
        if "children" in config:
            children = []
            for child_slug in config["children"]:
                child_domain = GHANA_EDUCATION_DOMAINS.get(child_slug, {})
                children.append({
                    "id": child_slug,
                    "text": child_domain.get("label", child_slug.replace("_", " ").title()),
                    "slug": child_slug,
                })
            node["children"] = children

        hierarchy.append(node)

    return JsonResponse({"status": "success", "tree": hierarchy})


# ai_engine/views/api.py
# Add these functions

@login_required
def library_search_api(request):
    """API endpoint for library search."""
    if not request.user.school:
        return JsonResponse({'success': False, 'error': 'No school associated with user.'}, status=400)

    query = request.GET.get('q', '').strip()
    if not query:
        return JsonResponse({'success': False, 'error': 'Search query is required.'}, status=400)

    from library.models import Book
    from django.db.models import Q

    books = Book.objects.filter(
        school=request.user.school
    ).filter(
        Q(title__icontains=query) |
        Q(author__icontains=query) |
        Q(category__name__icontains=query)
    )[:20]

    results = []
    for book in books:
        results.append({
            'id': str(book.id),
            'title': book.title,
            'author': book.author,
            'category': book.category.name if book.category else None,
            'status': book.status,
            'available_copies': book.available_copies,
            'shelf_location': book.shelf_location,
        })

    return JsonResponse({'success': True, 'results': results})


@login_required
def library_stats_api(request):
    """API endpoint for library statistics."""
    if not request.user.school:
        return JsonResponse({'success': False, 'error': 'No school associated with user.'}, status=400)

    from library.models import Book, BookBorrowing
    from django.db.models import Count

    school = request.user.school

    stats = {
        'total_books': Book.objects.filter(school=school).count(),
        'available_books': Book.objects.filter(school=school, status='AVAILABLE').count(),
        'borrowed_books': Book.objects.filter(school=school, status='BORROWED').count(),
        'active_borrowings': BookBorrowing.objects.filter(school=school, status='ACTIVE').count(),
        'overdue_borrowings': BookBorrowing.objects.filter(school=school, status='OVERDUE').count(),
        'categories': BookCategory.objects.filter(school=school).annotate(
            book_count=Count('books')
        ).values('name', 'book_count'),
    }

    return JsonResponse({'success': True, 'stats': stats})