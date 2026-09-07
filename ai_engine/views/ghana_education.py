# ai_engine/views/ghana_education.py
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
import json

from ai_engine.services.ghana_education_context import (
    GHANA_EDUCATION_DOMAINS,
    get_domain_hierarchy,
    can_access_ghana_education,
)
from ai_engine.services.copilot_engine import SchoolCopilotEngine
from ai_engine.services.knowledge_router import get_knowledge_context


def _get_icon_for_slug(slug):
    """Get an icon for a topic slug."""
    icons = {
        'education_system': 'bi bi-diagram-3',
        'basic_education': 'bi bi-book',
        'kg': 'bi bi-child',
        'primary': 'bi bi-journal',
        'jhs': 'bi bi-mortarboard',
        'secondary_education': 'bi bi-building',
        'shs': 'bi bi-mortarboard-fill',
        'tvet': 'bi bi-tools',
        'curriculum': 'bi bi-file-earmark-text',
        'nacca': 'bi bi-list-check',
        'assessment': 'bi bi-pencil-square',
        'bece': 'bi bi-award',
        'wassce': 'bi bi-trophy',
        'teaching_and_learning': 'bi bi-chalkboard',
        'classroom_management': 'bi bi-people',
        'teacher_development': 'bi bi-person-up',
        'ict_in_education': 'bi bi-laptop',
        'school_administration': 'bi bi-building-gear',
        'school_leadership': 'bi bi-person-badge',
        'school_health': 'bi bi-heart-pulse',
        'educational_planning': 'bi bi-bar-chart',
        'student_welfare': 'bi bi-hand-heart',
        'guidance_counselling': 'bi bi-chat-dots',
        'inclusive_education': 'bi bi-universal-access',
        'child_protection': 'bi bi-shield-check',
        'career_guidance': 'bi bi-compass',
        'scholarships': 'bi bi-coin',
        'current_policies': 'bi bi-file-earmark-lock',
        'education_statistics': 'bi bi-graph-up',
        'ministry_of_education': 'bi bi-building',
        'ges': 'bi bi-person-badge',
        'tertiary_pathways': 'bi bi-mortarboard',
    }
    return icons.get(slug, 'bi bi-book')


def _get_breadcrumbs(slug):
    """Build breadcrumb trail for a topic."""
    breadcrumbs = [
        {'label': 'Dashboard', 'url': 'dashboard:dashboard'},
        {'label': 'Ghana Education', 'url': 'ai_engine:ghana_education_home'},
    ]

    # Try to find parent chain
    current = slug
    chain = []

    while current:
        domain = GHANA_EDUCATION_DOMAINS.get(current, {})
        parent = domain.get('parent')
        chain.append({
            'slug': current,
            'label': domain.get('label', current.title()),
        })
        current = parent

    # Reverse to get top-down order
    chain.reverse()
    for item in chain[:-1]:
        breadcrumbs.append({
            'label': item['label'],
            'url': 'ai_engine:ghana_education_topic_detail',
            'slug': item['slug'],
        })

    # Add current page
    if chain:
        breadcrumbs.append({
            'label': chain[-1]['label'],
            'active': True,
        })

    return breadcrumbs


def _calculate_match_score(query, label, topics):
    """Calculate a simple match score for search results."""
    score = 0
    query_lower = query.lower()
    label_lower = label.lower()

    # Exact label match
    if query_lower == label_lower:
        score += 100
    elif query_lower in label_lower:
        score += 50

    # Topic matches
    for topic in topics:
        topic_lower = topic.lower()
        if query_lower == topic_lower:
            score += 30
        elif query_lower in topic_lower:
            score += 15
        elif topic_lower in query_lower:
            score += 10

    return score


@login_required
def ghana_education_home(request):
    """Home page for Ghana Education knowledge base."""
    # Check access
    if not can_access_ghana_education(request.user):
        messages.error(request, "You don't have permission to access Ghana Education resources.")
        return redirect('dashboard:dashboard')

    # Get all domains with their labels
    domains = []
    for key, domain in GHANA_EDUCATION_DOMAINS.items():
        domains.append({
            'slug': key,
            'label': domain.get('label', key.title()),
            'topics': domain.get('topics', [])[:5],
            'parent': domain.get('parent'),
            'subdomains': domain.get('subdomains', []),
        })

    # Get hierarchy
    hierarchy = get_domain_hierarchy()

    context = {
        'domains': domains,
        'total_topics': len(GHANA_EDUCATION_DOMAINS),
        'hierarchy': hierarchy,
    }
    return render(request, 'ai_engine/ghana_education_home.html', context)


@login_required
def ghana_education_topic_detail(request, slug):
    """Detail page for a specific Ghana Education topic."""
    # Check access
    if not can_access_ghana_education(request.user):
        messages.error(request, "You don't have permission to access Ghana Education resources.")
        return redirect('dashboard:dashboard')

    # Get topic data
    topic_data = GHANA_EDUCATION_DOMAINS.get(slug)

    if not topic_data:
        messages.warning(request, f"Topic '{slug}' not found in the knowledge base.")
        return redirect('ai_engine:ghana_education_home')

    # Get related topics (same parent or siblings)
    related_topics = []
    parent = topic_data.get('parent')
    if parent:
        for key, domain in GHANA_EDUCATION_DOMAINS.items():
            if domain.get('parent') == parent and key != slug:
                related_topics.append({
                    'slug': key,
                    'label': domain.get('label', key.title()),
                })

    # Get subdomains (children)
    subdomains = []
    for key, domain in GHANA_EDUCATION_DOMAINS.items():
        if domain.get('parent') == slug:
            subdomains.append({
                'slug': key,
                'label': domain.get('label', key.title()),
                'topics': domain.get('topics', [])[:3],
            })

    # Get knowledge context for this topic
    topic_question = ' '.join(topic_data.get('topics', []))
    knowledge_context = get_knowledge_context(topic_question)

    context = {
        'topic_data': {
            'slug': slug,
            'label': topic_data.get('label'),
            'topics': topic_data.get('topics', []),
            'description': f"Comprehensive information about {topic_data.get('label', slug)} in the Ghana Education context.",
            'icon': _get_icon_for_slug(slug),
            'subtopics': subdomains,
            'key_topics': topic_data.get('topics', [])[:8],
            'subdomains': topic_data.get('subdomains', []),
            'parent': topic_data.get('parent'),
        },
        'related_topics': related_topics[:6],
        'knowledge_context': knowledge_context,
        'breadcrumbs': _get_breadcrumbs(slug),
    }
    return render(request, 'ai_engine/ghana_education_topic_detail.html', context)


@login_required
def ghana_education_search(request):
    """Search Ghana Education topics."""
    # Check access
    if not can_access_ghana_education(request.user):
        messages.error(request, "You don't have permission to access Ghana Education resources.")
        return redirect('dashboard:dashboard')

    query = request.GET.get('q', '').strip()
    results = []

    if query:
        query_lower = query.lower()
        for key, domain in GHANA_EDUCATION_DOMAINS.items():
            label = domain.get('label', '')
            topics = domain.get('topics', [])

            # Search in label and topics
            label_lower = label.lower()
            topic_matches = [t for t in topics if query_lower in t.lower() or t.lower() in query_lower]

            if query_lower in label_lower or topic_matches:
                results.append({
                    'slug': key,
                    'label': label,
                    'topics': topic_matches[:3] if topic_matches else topics[:3],
                    'match_score': _calculate_match_score(query_lower, label_lower, topics),
                    'all_topics': topics,
                })

        # Sort by match score
        results.sort(key=lambda x: x['match_score'], reverse=True)

    context = {
        'query': query,
        'results': results[:20],
        'total_results': len(results),
    }
    return render(request, 'ai_engine/ghana_education_search.html', context)


@login_required
@require_POST
def ghana_education_ask_copilot(request):
    """Ask the Copilot about a specific Ghana Education topic."""
    # Check access
    if not can_access_ghana_education(request.user):
        return JsonResponse({
            'success': False,
            'error': 'You do not have permission to access this resource.'
        }, status=403)

    try:
        data = json.loads(request.body)
        topic_slug = data.get('topic_slug', '')
        question = data.get('question', '')

        if not topic_slug or not question:
            return JsonResponse({
                'success': False,
                'error': 'Topic slug and question are required.'
            }, status=400)

        # Get topic context
        topic_data = GHANA_EDUCATION_DOMAINS.get(topic_slug)

        if not topic_data:
            return JsonResponse({
                'success': False,
                'error': f"Topic '{topic_slug}' not found."
            }, status=404)

        # Build a contextualized question
        contextualized_question = f"""
        Topic: {topic_data.get('label')}
        Related Topics: {', '.join(topic_data.get('topics', [])[:10])}

        User Question: {question}

        Please answer this question with specific reference to the Ghana Education context provided.
        Use only the knowledge available and clearly distinguish between general knowledge and specific Ghana Education information.
        """

        # Get answer from Copilot
        engine = SchoolCopilotEngine(request.user)
        result = engine.answer(
            request.user.school,
            contextualized_question,
            history=[]
        )

        return JsonResponse({
            'success': True,
            'answer': result.get('answer', ''),
            'topic': topic_slug,
            'mode': result.get('mode', 'chat'),
            'sources': result.get('sources', []),
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON payload.'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)