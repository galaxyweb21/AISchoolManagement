from ai_engine.models import AIActivity


class AIActivityLogger:

    @staticmethod
    def log(
        school,
        title,
        description="",
        created_by=None,
    ):

        AIActivity.objects.create(
            school=school,
            title=title,
            description=description,
            created_by=created_by,
        )