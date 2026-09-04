from django.core.management.base import BaseCommand
from accounts.models import Permission, Role, RolePermission
from accounts.access import ROLE_POLICY

class Command(BaseCommand):
    help = 'Create/update the standard school roles and their permissions.'

    descriptions = {
        'SUPER_ADMIN': 'Full platform and school administration access.',
        'SCHOOL_ADMIN': 'Full operational access for one school.',
        'BURSAR': 'Finance, billing, payments and financial reporting.',
        'REGISTRAR': 'Student records, admissions and academic administration.',
        'HOD': 'Departmental academic oversight, examinations and results review.',
        'SECRETARY': 'Front-office, student records, attendance and communication.',
        'TEACHER': 'Assigned classes, attendance, assessments and report-card review.',
        'STUDENT': 'Own academic, finance and report-card information.',
        'PARENT': 'Children, finance, attendance and published report cards.',
    }

    def handle(self, *args, **kwargs):
        permission_cache = {}
        modules = set()
        actions = set()
        for module_map in ROLE_POLICY.values():
            for module, module_actions in module_map.items():
                if module == '*':
                    continue
                modules.add(module)
                actions.update(module_actions)
        for module in modules:
            for action in actions:
                permission_cache[(module, action)] = Permission.objects.get_or_create(
                    module=module, action=action,
                    defaults={'name': f'{module.title()} - {action.title()}'},
                )[0]

        for role_name, module_map in ROLE_POLICY.items():
            role, _ = Role.objects.get_or_create(
                name=role_name,
                defaults={'description': self.descriptions.get(role_name, ''), 'is_system': True},
            )
            role.description = self.descriptions.get(role_name, role.description)
            role.is_system = True
            role.is_active = True
            role.save(update_fields=['description', 'is_system', 'is_active'])
            perms = []
            if module_map.get('*'):
                perms = list(permission_cache.values())
            else:
                for module, actions_for_module in module_map.items():
                    for action in actions_for_module:
                        perm = permission_cache.get((module, action))
                        if perm:
                            perms.append(perm)
            role.permissions.set(perms)
        self.stdout.write(self.style.SUCCESS('Standard school roles and permissions are ready.'))
