"""
Ghana Education Knowledge Layer
================================

Provides a reliable knowledge layer for Ghana education questions.

This layer is deliberately separate from school database context.

IMPORTANT:
- Never put Student, Staff, Parent, face encoding, ID numbers,
  passwords, tokens or other school records here.
- This module handles educational knowledge only.
- School-specific operational questions must continue through
  the authorized school-data context.
"""

import re


# ---------------------------------------------------------------------------
# CORE GHANA EDUCATION KNOWLEDGE
# ---------------------------------------------------------------------------

GHANA_EDUCATION_KNOWLEDGE = {

    "early_childhood_education": {
        "title": "Early Childhood Education in Ghana",

        "keywords": [
            "early childhood education",
            "early childhood",
            "early years education",
            "early learning",
            "early childhood development",
            "ecd",
            "ecc",
            "ecced",
            "kindergarten",
            "kindergarden",
            "kg education",
            "kg1",
            "kg2",
        ],

        "answer": """
Early childhood education in Ghana refers to education and development
support provided to young children before and during the early years of
formal basic education.

In Ghana, Kindergarten (KG) forms an important part of the basic education
system. The country provides two years of Kindergarten education, commonly
referred to as KG 1 and KG 2.

The purpose of early childhood education is not simply to teach children
academic content. It is intended to provide a strong foundation for the
child's physical, cognitive, language, social, emotional and creative
development.

Ghana's Kindergarten curriculum places strong emphasis on child-centred
and play-based learning. Young children learn through activities such as
play, exploration, stories, songs, interaction, practical activities and
creative experiences.

The Ghanaian early-years approach recognizes that children develop at
different rates. Teaching therefore needs to provide developmentally
appropriate experiences rather than treating every child as though they
learn in exactly the same way.

Important areas of early childhood education include:

1. Language and literacy
   Children develop listening, speaking, vocabulary, communication and
   early reading and writing skills.

2. Numeracy
   Children develop early mathematical thinking, counting, number
   recognition, patterns, shapes, measurement and problem-solving skills.

3. Creative development
   Drawing, music, movement, drama, construction and other creative
   activities help children develop imagination and expression.

4. Social and emotional development
   Children learn to communicate, cooperate, share, manage emotions,
   develop relationships and become increasingly independent.

5. Physical development
   Children need opportunities for movement, coordination, fine-motor
   development and healthy physical activity.

6. Cognitive development
   Children develop curiosity, observation, reasoning, memory,
   classification, problem solving and early critical-thinking skills.

7. Health, nutrition and protection
   Early childhood development is broader than classroom instruction.
   Children's health, nutrition, safety, protection and responsive
   caregiving are important foundations for learning.

8. Family and community involvement
   Parents and caregivers play an important role in supporting children's
   development and connecting learning at home with learning at school.

Ghana's early childhood approach therefore aims to prepare children for
successful progression into primary education while supporting their
overall development.

For a school implementing early childhood education, the most important
principles are developmentally appropriate teaching, play-based learning,
positive relationships, inclusion, observation of children's progress,
family engagement and a safe and stimulating learning environment.
""",

        "key_points": [
            "Ghana provides two years of Kindergarten education.",
            "The two years are commonly referred to as KG 1 and KG 2.",
            "Early childhood education is concerned with holistic child development.",
            "Ghana's KG curriculum emphasizes play-based and child-centred learning.",
            "Language and literacy are important foundations.",
            "Numeracy is an important early learning area.",
            "Creative development is part of early childhood learning.",
            "Social and emotional development is important.",
            "Physical development and wellbeing are important.",
            "Parents and caregivers have an important role.",
            "Inclusion and developmentally appropriate learning are important.",
        ],

        "source_note": (
            "The knowledge is aligned with Ghana's Kindergarten curriculum "
            "and Ghana-focused early childhood development materials."
        ),
    },


    "ghana_education_system": {
        "title": "Education System in Ghana",

        "keywords": [
            "education system in ghana",
            "ghana education system",
            "ghanaian education system",
            "education in ghana",
        ],

        "answer": """
Ghana's education system includes early childhood education, basic
education, secondary education and tertiary education.

At the pre-tertiary level, the system includes Kindergarten, primary
education, Junior High School and Senior High School or equivalent
secondary pathways.

Ghana's education system places increasing emphasis on competencies,
learning outcomes, inclusion, foundational literacy and numeracy,
critical thinking, creativity, digital skills and preparation for further
education and productive participation in society.

At the Kindergarten level, the curriculum emphasizes developmentally
appropriate and play-based learning. At the primary and secondary levels,
learners progressively develop subject knowledge, competencies, skills
and values.

The education system is supported by institutions including the Ministry
of Education, Ghana Education Service, National Council for Curriculum
and Assessment and other education-sector agencies.
""",
    },


    "ghana_education_service": {
        "title": "Ghana Education Service",

        "keywords": [
            "ghana education service",
            "ges",
            "what is ges",
            "functions of ges",
        ],

        "answer": """
The Ghana Education Service (GES) is a major institution responsible for
the administration and implementation of pre-tertiary education in Ghana.

Its responsibilities include supporting the delivery and management of
pre-tertiary education, implementing education policies, supporting
schools and teachers, and working to improve access, quality and learning
outcomes.

For a school management system, GES-related information can therefore be
particularly relevant when discussing school administration, teachers,
basic education, school supervision, curriculum implementation and
education policy.
""",
    },


    "nacca": {
        "title": "NaCCA",

        "keywords": [
            "nacca",
            "national council for curriculum and assessment",
            "functions of nacca",
        ],

        "answer": """
The National Council for Curriculum and Assessment (NaCCA) is Ghana's
national body responsible for curriculum and assessment matters within
its mandate.

NaCCA has an important role in the development and review of curricula,
assessment standards and related educational resources.

For schools, NaCCA is particularly relevant when discussing curriculum
standards, learning outcomes, assessment, teaching and learning
materials, and curriculum implementation.
""",
    },


    "inclusive_education": {
        "title": "Inclusive Education in Ghana",

        "keywords": [
            "inclusive education in ghana",
            "inclusive education",
            "special education ghana",
            "inclusive schooling",
        ],

        "answer": """
Inclusive education means creating an education system in which learners,
including learners with disabilities and other diverse learning needs,
can participate meaningfully in education.

In the Ghanaian context, inclusive education is connected to equitable
access, participation, appropriate support and the removal of barriers
that prevent learners from learning effectively.

A school implementing inclusive education should consider accessibility,
teacher capacity, differentiated instruction, appropriate learning
materials, learner support, safeguarding, family engagement and continuous
assessment of individual learning needs.
""",
    },


    "waec": {
        "title": "WAEC (West African Examinations Council)",

        "keywords": [
            "waec",
            "west african examinations council",
            "what is waec",
            "who administers bece",
            "who administers wassce",
        ],

        "answer": """
The West African Examinations Council (WAEC) is the regional body
responsible for conducting standardised examinations across West Africa,
including Ghana, Nigeria, Sierra Leone, The Gambia and Liberia.

In Ghana, WAEC administers the two examinations that matter most to
schools: the Basic Education Certificate Examination (BECE), taken at
the end of Junior High School, and the West African Senior School
Certificate Examination (WASSCE), taken at the end of Senior High
School. WAEC sets the syllabi coverage, conducts and marks these exams,
and issues the certificates and results slips schools and students rely
on for placement and progression.

For a school management system, WAEC is relevant whenever discussing
exam registration, mock exams, exam preparation, results processing, or
BECE/WASSCE placement and progression.
""",
    },


    "bece": {
        "title": "BECE (Basic Education Certificate Examination)",

        "keywords": [
            "bece",
            "basic education certificate examination",
            "what is bece",
            "bece exam",
            "bece results",
            "bece registration",
            "junior high school exam",
            "jhs exam",
            "jhs 3 exam",
        ],

        "answer": """
The Basic Education Certificate Examination (BECE) is the national
examination taken by students at the end of Junior High School 3 (JHS 3)
in Ghana, marking the completion of basic education.

BECE is conducted by the West African Examinations Council (WAEC) and
covers the core JHS subjects, including English Language, Mathematics,
Integrated Science, and Social Studies, alongside elective subjects.
A student's BECE aggregate score (the sum of their six best subject
grades) is the main basis for placement into Senior High School (SHS)
through Ghana's Computerised School Selection and Placement System
(CSSPS) - a lower aggregate is better, with 6 being the best possible
score.

For a school, BECE relevance shows up throughout the JHS 3 academic
year: registration deadlines, mock exam scheduling and performance
tracking, syllabus completion, revision planning, and eventually results
processing and SHS placement support for students and parents.
""",
    },


    "wassce": {
        "title": "WASSCE (West African Senior School Certificate Examination)",

        "keywords": [
            "wassce",
            "west african senior school certificate examination",
            "what is wassce",
            "wassce results",
            "wassce registration",
            "senior high school exam",
            "shs exam",
            "shs 3 exam",
            "waec results",
        ],

        "answer": """
The West African Senior School Certificate Examination (WASSCE) is the
national examination taken by students at the end of Senior High School
3 (SHS 3) in Ghana, marking the completion of secondary education.

WASSCE is conducted by the West African Examinations Council (WAEC) and
covers core subjects (English Language, Mathematics/Core Maths,
Integrated Science, Social Studies) plus elective subjects chosen
according to the student's programme (e.g. General Science, General Arts,
Business, Visual Arts, Home Economics, Technical/Vocational). WASSCE
results are the main requirement for admission into tertiary institutions
in Ghana and across West Africa, and are graded on a scale from A1
(highest) to F9 (fail).

For a school, WASSCE relevance covers SHS 3 registration, mock exams and
revision tracking, subject/elective combinations, syllabus completion,
and results processing to support students' tertiary applications.
""",
    },
}


# ---------------------------------------------------------------------------
# NORMALIZATION
# ---------------------------------------------------------------------------

def _normalize(text):
    text = str(text or "").lower()
    text = re.sub(r"[^a-z0-9\s'-]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ---------------------------------------------------------------------------
# FIND KNOWLEDGE TOPIC
# ---------------------------------------------------------------------------

def find_ghana_education_topic(question):
    """
    Return the best matching Ghana education knowledge topic.

    Returns:
        dict or None
    """

    q = _normalize(question)

    if not q:
        return None

    best_topic = None
    best_score = 0

    for topic_key, topic in GHANA_EDUCATION_KNOWLEDGE.items():

        score = 0

        for keyword in topic.get("keywords", []):

            keyword_normalized = _normalize(keyword)

            if not keyword_normalized:
                continue

            if keyword_normalized in q:

                # Longer phrases are stronger matches.
                words = len(keyword_normalized.split())

                score += 10 + (words * 5)

        if score > best_score:
            best_score = score
            best_topic = topic

    return best_topic


# ---------------------------------------------------------------------------
# DETECT GHANA EDUCATION QUESTION
# ---------------------------------------------------------------------------

def is_ghana_education_question(question):
    """
    Returns True when the question matches the Ghana education knowledge
    layer.
    """

    return find_ghana_education_topic(question) is not None


# ---------------------------------------------------------------------------
# GET DIRECT KNOWLEDGE ANSWER
# ---------------------------------------------------------------------------

def get_ghana_education_answer(question):
    """
    Return a reliable Ghana education answer when a known topic matches.

    Returns:
        dict with:
            found
            title
            answer
            key_points
            source_note
    """

    topic = find_ghana_education_topic(question)

    if not topic:
        return {
            "found": False,
            "title": "",
            "answer": "",
            "key_points": [],
            "source_note": "",
        }

    return {
        "found": True,
        "title": topic.get("title", ""),
        "answer": topic.get("answer", "").strip(),
        "key_points": topic.get("key_points", []),
        "source_note": topic.get("source_note", ""),
    }