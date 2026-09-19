from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'

    def ready(self):
        # Register RBAC cache invalidation signals once the app registry is ready.
        from . import rbac_signals  # noqa: F401
