from django.core.management.base import BaseCommand

from ai_engine.services.services import AIService


class Command(BaseCommand):
    help = "Test the configured Groq connection without exposing the API key."

    def handle(self, *args, **options):
        result = AIService._call_groq(
            "You are a concise test assistant.",
            "Reply with exactly: GROQ CONNECTION OK",
            max_tokens=20,
            temperature=0,
            model=None,
        )
        if result:
            self.stdout.write(self.style.SUCCESS(result))
            return
        self.stderr.write(self.style.ERROR(
            "Groq connection failed: %s" % (AIService.LAST_ERROR or "Unknown error")
        ))
