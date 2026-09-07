"""Central role access policy used by the final application pass.

The project historically mixed hard-coded role lists with the database RBAC
system.  This module gives the application one predictable policy while
remaining backwards compatible with the existing User.role field.
"""
from .permissions import has_permission

ROLE_POLICY = {
    'SUPER_ADMIN': {'*': {'*'}},
    'SCHOOL_ADMIN': {'*': {'view', 'create', 'edit', 'delete', 'approve', 'export', 'print'}},
    'BURSAR': {
        'dashboard': {'view'}, 'students': {'view'}, 'finance': {'view', 'create', 'edit', 'delete', 'approve', 'export', 'print'},
        'reports': {'view', 'export', 'print'}, 'communication': {'view', 'create', 'edit'},
    },
    'REGISTRAR': {
        'dashboard': {'view'}, 'students': {'view', 'create', 'edit', 'export', 'print'}, 'parents': {'view', 'create', 'edit'},
        'academics': {'view'}, 'attendance': {'view', 'export', 'print'}, 'reports': {'view', 'export', 'print'},
    },
    'HOD': {
        'dashboard': {'view'}, 'students': {'view'}, 'academics': {'view', 'create', 'edit', 'export', 'print'},
        'exams': {'view', 'create', 'edit', 'export', 'print'}, 'reports': {'view', 'approve', 'export', 'print'},
        'attendance': {'view', 'export', 'print'}, 'ai': {'view'},
    },
    'SECRETARY': {
        'dashboard': {'view'}, 'students': {'view', 'create', 'edit', 'export', 'print'}, 'parents': {'view', 'create', 'edit'},
        'attendance': {'view', 'create', 'edit', 'export', 'print'}, 'communication': {'view', 'create', 'edit'},
        'reports': {'view', 'export', 'print'},
    },
    'TEACHER': {
        'dashboard': {'view'}, 'students': {'view'}, 'academics': {'view'}, 'attendance': {'view', 'create', 'edit'},
        'exams': {'view', 'create', 'edit', 'export', 'print'}, 'reports': {'view', 'export', 'print'}, 'ai': {'view'},
    },
    'STUDENT': {
        'dashboard': {'view'}, 'reports': {'view', 'print'}, 'academics': {'view'}, 'finance': {'view'},
    },
    'PARENT': {
        'dashboard': {'view'}, 'parents': {'view'}, 'reports': {'view', 'print'}, 'finance': {'view'}, 'attendance': {'view'},
    },
}


def role_allows(user, module, action='view'):
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_superuser', False) or getattr(user, 'role', None) == 'SUPER_ADMIN':
        return True
    if has_permission(user, f'{module}.{action}'):
        return True
    role = getattr(user, 'role', None)
    policy = ROLE_POLICY.get(role, {})
    return action in policy.get(module, set()) or action in policy.get('*', set())


def allowed_modules(user):
    role = getattr(user, 'role', None)
    if getattr(user, 'is_superuser', False) or role == 'SUPER_ADMIN':
        return ['*']
    return sorted(ROLE_POLICY.get(role, {}).keys())
