# ai_engine/services/navigation_tree.py
"""
Navigation Tree Mapping for Ghana Education System
Maps UI navigation nodes to backend domain slugs
"""

from .ghana_education_context import GHANA_EDUCATION_DOMAINS


def get_nav_tree():
    """
    Build the navigation tree from the Ghana Education domains.
    Returns a nested dictionary structure for the sidebar.
    """
    # Define the main categories and their children
    nav_tree = {
        "education_system": {
            "label": "Education System",
            "icon": "bi bi-diagram-3",
            "slug": "education_system",
            "children": {
                "basic_education": {
                    "label": "Basic Education",
                    "icon": "bi bi-book",
                    "slug": "basic_education",
                    "children": {
                        "kg": {"label": "Kindergarten", "icon": "bi bi-child", "slug": "kg"},
                        "primary": {"label": "Primary (Basic 1-6)", "icon": "bi bi-journal", "slug": "primary"},
                        "jhs": {"label": "Junior High (Basic 7-9)", "icon": "bi bi-mortarboard", "slug": "jhs"},
                    }
                },
                "secondary_education": {
                    "label": "Secondary Education",
                    "icon": "bi bi-building",
                    "slug": "secondary_education",
                    "children": {
                        "shs": {"label": "Senior High (SHS 1-3)", "icon": "bi bi-mortarboard-fill", "slug": "shs"},
                        "tvet": {"label": "TVET", "icon": "bi bi-tools", "slug": "tvet"},
                    }
                }
            }
        },
        "curriculum": {
            "label": "Curriculum & Assessment",
            "icon": "bi bi-file-earmark-text",
            "slug": "curriculum",
            "children": {
                "nacca": {"label": "NaCCA Standards", "icon": "bi bi-list-check", "slug": "nacca"},
                "assessment": {"label": "Assessment & Exams", "icon": "bi bi-pencil-square", "slug": "assessment"},
                "bece": {"label": "BECE", "icon": "bi bi-award", "slug": "bece"},
                "wassce": {"label": "WASSCE", "icon": "bi bi-trophy", "slug": "wassce"},
            }
        },
        "teaching_learning": {
            "label": "Teaching & Learning",
            "icon": "bi bi-chalkboard",
            "slug": "teaching_and_learning",
            "children": {
                "classroom_management": {"label": "Classroom Management", "icon": "bi bi-people",
                                         "slug": "classroom_management"},
                "teacher_development": {"label": "Teacher Development", "icon": "bi bi-person-up",
                                        "slug": "teacher_development"},
                "ict_in_education": {"label": "ICT in Education", "icon": "bi bi-laptop", "slug": "ict_in_education"},
            }
        },
        "school_administration": {
            "label": "School Administration",
            "icon": "bi bi-building-gear",
            "slug": "school_administration",
            "children": {
                "school_leadership": {"label": "School Leadership", "icon": "bi bi-person-badge",
                                      "slug": "school_leadership"},
                "school_health": {"label": "School Health", "icon": "bi bi-heart-pulse", "slug": "school_health"},
                "educational_planning": {"label": "Educational Planning", "icon": "bi bi-bar-chart",
                                         "slug": "educational_planning"},
            }
        },
        "student_support": {
            "label": "Student Support & Welfare",
            "icon": "bi bi-hand-heart",
            "slug": "student_support",
            "children": {
                "guidance_counselling": {"label": "Guidance & Counselling", "icon": "bi bi-chat-dots",
                                         "slug": "guidance_counselling"},
                "inclusive_education": {"label": "Inclusive Education", "icon": "bi bi-universal-access",
                                        "slug": "inclusive_education"},
                "child_protection": {"label": "Child Protection", "icon": "bi bi-shield-check",
                                     "slug": "child_protection"},
                "career_guidance": {"label": "Career Guidance", "icon": "bi bi-compass", "slug": "career_guidance"},
                "scholarships": {"label": "Scholarships", "icon": "bi bi-coin", "slug": "scholarships"},
            }
        },
        "policy_research": {
            "label": "Policy & Research",
            "icon": "bi bi-newspaper",
            "slug": "current_policies",
            "children": {
                "current_policies": {"label": "Current Education Policies", "icon": "bi bi-file-earmark-lock",
                                     "slug": "current_policies"},
                "education_statistics": {"label": "Education Statistics", "icon": "bi bi-graph-up",
                                         "slug": "education_statistics"},
            }
        }
    }

    return nav_tree


def get_topic_context(topic_slug):
    """
    Get the full context for a Ghana Education topic slug.
    """
    # Get the domain data from GHANA_EDUCATION_DOMAINS
    domain_data = GHANA_EDUCATION_DOMAINS.get(topic_slug, {})

    return {
        'slug': topic_slug,
        'label': domain_data.get('label', topic_slug.title()),
        'topics': domain_data.get('topics', []),
        'subdomains': domain_data.get('subdomains', []),
        'parent': domain_data.get('parent'),
    }