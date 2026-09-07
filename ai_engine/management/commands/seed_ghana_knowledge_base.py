# ai_engine/management/commands/seed_ghana_knowledge_base.py
"""
Seed a starter set of curated Ghana Education knowledge documents.

These are general, well-established structural facts about Ghana's
pre-tertiary education system, written in plain original language
(not copied from any document) so the RAG layer (Step 3) has
something real to ground answers in and the citation engine (Step 4)
has something real to cite, from day one — before a school
administrator has curated anything of their own.

Every entry links to the relevant official body's homepage (the same
URLs already used in ghana_education.OFFICIAL_SOURCES) rather than a
specific article, since that's the one URL we can vouch for without
live verification. `last_verified_at` is left unset deliberately —
an administrator should review and re-verify each entry via the admin
before treating it as authoritative in production.

Run with: python manage.py seed_ghana_knowledge_base
"""

from django.core.management.base import BaseCommand

SEED_DOCUMENTS = [
    {
        "domain": "education_system",
        "title": "Structure of Ghana's pre-tertiary education system",
        "source_name": "GES",
        "source_url": "https://ges.gov.gh/",
        "content": (
            "Ghana's pre-tertiary education generally runs through Kindergarten "
            "(2 years), Primary school (6 years, Basic 1-6), Junior High School "
            "(3 years, JHS 1-3), and Senior High School (3 years, SHS 1-3). "
            "Kindergarten through JHS is commonly referred to as Basic Education. "
            "Schools verify exact current structure and any transitional "
            "arrangements with GES directly, as implementation details can vary "
            "by year and region."
        ),
    },
    {
        "domain": "nacca",
        "title": "Role of NaCCA in curriculum development",
        "source_name": "NACCA",
        "source_url": "https://nacca.gov.gh/",
        "content": (
            "The National Council for Curriculum and Assessment (NaCCA) is "
            "responsible for developing and reviewing Ghana's standards-based "
            "curriculum for pre-tertiary education, including subject syllabi, "
            "core competencies, and approved instructional materials. Schools "
            "and teachers should refer to NaCCA's published curriculum "
            "documents for the current, subject-specific standards rather than "
            "relying on general summaries."
        ),
    },
    {
        "domain": "bece",
        "title": "Basic Education Certificate Examination (BECE) overview",
        "source_name": "WAEC",
        "source_url": "https://waecgh.org/",
        "content": (
            "The Basic Education Certificate Examination (BECE) is administered "
            "by the West African Examinations Council (WAEC) to candidates "
            "completing Junior High School (JHS 3) in Ghana, and is used for "
            "placement into Senior High School. Registration windows, subject "
            "combinations and exact examination dates are set by WAEC each "
            "year and should be confirmed on the official WAEC Ghana site "
            "rather than assumed to repeat from a previous year."
        ),
    },
    {
        "domain": "wassce",
        "title": "West African Senior School Certificate Examination (WASSCE) overview",
        "source_name": "WAEC",
        "source_url": "https://waecgh.org/",
        "content": (
            "The West African Senior School Certificate Examination (WASSCE) "
            "is administered by WAEC to candidates completing Senior High "
            "School (SHS 3) in Ghana, and results are used for tertiary "
            "admissions. As with the BECE, registration timelines and subject "
            "requirements are published by WAEC each academic year and should "
            "be verified directly rather than assumed from prior years."
        ),
    },
    {
        "domain": "school_administration",
        "title": "GES role in pre-tertiary school administration",
        "source_name": "GES",
        "source_url": "https://ges.gov.gh/",
        "content": (
            "The Ghana Education Service (GES) is the implementing agency "
            "responsible for day-to-day administration of pre-tertiary "
            "education, including staffing, school inspection, and rollout of "
            "Ministry of Education policy at the school level. School "
            "administrators should treat GES circulars and directives as the "
            "operative guidance for administrative matters, and verify "
            "current circulars through official GES channels."
        ),
    },
    {
        "domain": "ministry_of_education",
        "title": "Ministry of Education's role in the education sector",
        "source_name": "MOE",
        "source_url": "https://moe.gov.gh/",
        "content": (
            "The Ministry of Education (MoE) sets overall national education "
            "policy and sector direction for Ghana, with implementation "
            "carried out by agencies including GES (pre-tertiary "
            "administration) and NaCCA (curriculum and assessment standards). "
            "For sector-wide policy questions, the Ministry's own "
            "publications are the primary reference."
        ),
    },
]


class Command(BaseCommand):
    help = "Seed starter Ghana Education knowledge base documents (Step 3 RAG layer)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Deactivate existing seeded documents with matching titles before re-creating them.",
        )

    def handle(self, *args, **options):
        from ai_engine.models import GhanaEducationKnowledgeDocument

        created, updated = 0, 0
        for doc in SEED_DOCUMENTS:
            obj, was_created = GhanaEducationKnowledgeDocument.objects.update_or_create(
                title=doc["title"],
                defaults={
                    "domain": doc["domain"],
                    "source_name": doc["source_name"],
                    "source_url": doc["source_url"],
                    "content": doc["content"],
                    "is_active": True,
                },
            )
            created += int(was_created)
            updated += int(not was_created)

        self.stdout.write(self.style.SUCCESS(
            f"Ghana Education knowledge base seeded: {created} created, {updated} updated. "
            f"Review each entry in the admin and set last_verified_at once confirmed."
        ))
