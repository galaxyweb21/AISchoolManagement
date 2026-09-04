from ai_engine.models import AIActivity


class AIActivityService:

    @staticmethod
    def log(
        school,
        activity_type,
        title,
        description="",
        created_by=None,
        status="SUCCESS",
        metadata=None,
    ):
        return AIActivity.objects.create(
            school=school,
            activity_type=activity_type,
            title=title,
            description=description,
            created_by=created_by,
            status=status,
            metadata=metadata or {},
        )