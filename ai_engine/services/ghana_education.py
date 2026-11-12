# ai_engine/services/ghana_education.py
"""
Ghana Education Knowledge Context
=================================

Provides structured Ghana education-sector knowledge categories
for the AI School Copilot.

IMPORTANT:
This module does not provide access to private school records.

Private school data must continue to come through:
    copilot_context.py

This module is for general Ghana education knowledge and research
topics that can be made available according to the user's AI role.
"""

from __future__ import annotations


# ==============================================================
# OFFICIAL SOURCES
# ==============================================================

OFFICIAL_SOURCES = [
    {
        "name": "Ghana Education Service (GES)",
        "url": "https://ges.gov.gh/",
        "topics": "pre-tertiary administration, policies, guidelines, teacher resources, school administration",
    },
    {
        "name": "National Council for Curriculum and Assessment (NaCCA)",
        "url": "https://nacca.gov.gh/",
        "topics": "curriculum, standards, assessment, approved instructional materials, core competencies",
    },
    {
        "name": "Ministry of Education Ghana",
        "url": "https://moe.gov.gh/",
        "topics": "national education policy, programmes, sector direction",
    },
    {
        "name": "WAEC Ghana",
        "url": "https://waecgh.org/",
        "topics": "BECE, WASSCE, examination regulations, registration and results",
    },
]


def official_sources_text():
    """Return formatted text of official sources."""
    return "\n".join(
        f"- {s['name']}: {s['url']} ({s['topics']})" for s in OFFICIAL_SOURCES
    )


# ==============================================================
# GHANA EDUCATION SYSTEM PROMPT
# ==============================================================

GHANA_EDUCATION_SYSTEM_STRUCTURE = """
┌─────────────────────────────────────────────────────────────┐
│                    GHANA EDUCATION                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                EDUCATION SYSTEM                      │   │
│  │  • Basic Education (KG, Primary, JHS)               │   │
│  │  • Secondary Education (SHS)                        │   │
│  │  • Tertiary Education                                │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              MINISTRY OF EDUCATION                   │   │
│  │  • National Education Policy                        │   │
│  │  • Education Reforms                                 │   │
│  │  • Sector Planning                                   │   │
│  │  • Current Policies & Circulars                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              GHANA EDUCATION SERVICE (GES)           │   │
│  │  • School Administration                             │   │
│  │  • School Leadership                                 │   │
│  │  • Teacher Supervision                               │   │
│  │  • District Education                                │   │
│  │  • School Improvement                                │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              NaCCA - CURRICULUM                      │   │
│  │  • Standards-Based Curriculum                        │   │
│  │  • Common Core Programme (CCP)                      │   │
│  │  • Learning Outcomes                                 │   │
│  │  • Core Competencies                                 │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              CURRICULUM LEVELS                       │   │
│  │  ├── KG (Kindergarten)                              │   │
│  │  │   • Early Childhood Education                    │   │
│  │  │   • Play-based Learning                          │   │
│  │  │   • Foundational Literacy & Numeracy             │   │
│  │  ├── PRIMARY (Basic 1-6)                           │   │
│  │  │   • Literacy, Numeracy, Science                  │   │
│  │  │   • Social Studies, Creative Arts                │   │
│  │  │   • Our World Our People, RME, Ghanaian Lang    │   │
│  │  ├── JHS (Basic 7-9)                               │   │
│  │  │   • Mathematics, English, Science                │   │
│  │  │   • Social Studies, Career Technology             │   │
│  │  │   • Computing, RME, Ghanaian Language            │   │
│  │  │   └── BECE Preparation                           │   │
│  │  └── SHS (1-3)                                     │   │
│  │      • Core Subjects (Math, English, Science)       │   │
│  │      • Elective Subjects (Arts, Science, Biz)      │   │
│  │      └── WASSCE Preparation                        │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              TVET                                    │   │
│  │  • Technical Education                               │   │
│  │  • Vocational Education                              │   │
│  │  • Skills Development                                │   │
│  │  • Career Pathways                                   │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │          TEACHING & LEARNING                         │   │
│  │  • Lesson Planning                                   │   │
│  │  • Teaching Strategies                               │   │
│  │  • Classroom Management                              │   │
│  │  • Differentiated Instruction                        │   │
│  │  • Continuous Assessment                             │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │          SCHOOL ADMINISTRATION                       │   │
│  │  • School Leadership                                 │   │
│  │  • Staff Management                                  │   │
│  │  • Student Records                                   │   │
│  │  • School Reporting                                  │   │
│  │  • Parent Communication                              │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │          STUDENT WELFARE & SUPPORT                   │   │
│  │  • Guidance & Counselling                            │   │
│  │  • Inclusive Education                               │   │
│  │  • Special Educational Needs                         │   │
│  │  • Child Protection                                  │   │
│  │  • School Health                                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │       TEACHER PROFESSIONAL DEVELOPMENT               │   │
│  │  • CPD                                               │   │
│  │  • Teacher Training                                  │   │
│  │  • Professional Learning                             │   │
│  │  • Mentoring & Coaching                              │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │          ICT IN EDUCATION                            │   │
│  │  • Educational Technology                            │   │
│  │  • Digital Learning                                  │   │
│  │  • Computer Literacy                                 │   │
│  │  • E-Learning                                        │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │       EDUCATIONAL PLANNING & STATISTICS              │   │
│  │  • Strategic Planning                                │   │
│  │  • School Development                                │   │
│  │  • Enrolment Statistics                              │   │
│  │  • Completion & Dropout Rates                       │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │     CAREER GUIDANCE & TERTIARY PATHWAYS              │   │
│  │  • Career Counselling                                │   │
│  │  • Career Pathways                                   │   │
│  │  • University Admission                              │   │
│  │  • Scholarships                                      │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │        CURRENT EDUCATION POLICIES                    │   │
│  │  • GES Policies                                      │   │
│  │  • MoE Directives                                    │   │
│  │  • Circulars                                         │   │
│  │  • Policy Updates                                    │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
"""

GHANA_EDUCATION_SYSTEM_PROMPT = f"""
You are AI School Copilot, an education-sector assistant designed for schools in Ghana.

Your Ghana education knowledge covers the complete Ghana Education System:

{GHANA_EDUCATION_SYSTEM_STRUCTURE}

KEY KNOWLEDGE AREAS:
1. EDUCATION SYSTEM: Basic (KG/Primary/JHS), Secondary (SHS), Tertiary pathways
2. MINISTRY OF EDUCATION: National policy, reforms, sector planning
3. GES: School administration, leadership, supervision, improvement
4. NaCCA: Curriculum, standards, Common Core Programme, assessment
5. CURRICULUM LEVELS:
   - KG: Early childhood, play-based, foundational skills
   - PRIMARY: Basic 1-6 core subjects
   - JHS: Basic 7-9, BECE preparation
   - SHS: Core/elective subjects, WASSCE preparation
6. TVET: Technical, vocational, skills development
7. TEACHING & LEARNING: Lesson planning, strategies, classroom management
8. SCHOOL ADMINISTRATION: Leadership, staff, records, reporting
9. STUDENT WELFARE: Guidance, counselling, inclusive education, child protection, health
10. TEACHER DEVELOPMENT: CPD, training, mentoring
11. ICT IN EDUCATION: Edtech, digital learning
12. EDUCATIONAL PLANNING: Strategy, development, statistics
13. CAREER GUIDANCE: Career pathways, tertiary admission, scholarships
14. CURRENT POLICIES: GES/MoE policies, circulars, updates

SOURCE DISCIPLINE:
1. If a question asks for a current policy, circular, official deadline, examination
   date, registration rule, fee or other time-sensitive fact, say that it should be
   verified against the latest official source unless current research results are supplied.
2. Prefer GES, NaCCA, Ministry of Education and WAEC Ghana as authoritative sources.
3. Never present an invented citation, circular number, policy title, examination date,
   syllabus requirement or official rule as fact.
4. Clearly label advice/inference as advice rather than official policy.
5. For school-specific questions, use only the school context supplied by the application.
6. Do not reveal private student, parent, staff, finance or safeguarding information outside
   the user's authorized scope.

SYSTEM STRUCTURE REFERENCE:
{GHANA_EDUCATION_SYSTEM_STRUCTURE}
"""


# ==============================================================
# GHANA EDUCATION KNOWLEDGE DOMAINS - COMPLETE HIERARCHY
# ==============================================================

GHANA_EDUCATION_DOMAINS = {
    # ==========================================================
    # EDUCATION SYSTEM
    # ==========================================================
    "education_system": {
        "label": "Ghana Education System",
        "topics": [
            "Ghana education system",
            "basic education",
            "secondary education",
            "tertiary education",
            "pre-tertiary education",
            "school levels",
            "education pathways",
            "school governance",
            "education structure",
        ],
        "subdomains": ["basic_education", "secondary_education", "tertiary_education"],
    },

    "basic_education": {
        "label": "Basic Education",
        "topics": [
            "basic education",
            "kindergarten",
            "primary school",
            "junior high school",
            "JHS",
            "basic school curriculum",
            "basic education certificate",
            "compulsory education",
            "free compulsory universal basic education",
        ],
        "subdomains": ["kg", "primary", "jhs"],
        "parent": "education_system",
    },

    "secondary_education": {
        "label": "Secondary Education",
        "topics": [
            "secondary education",
            "senior high school",
            "SHS",
            "technical education",
            "vocational education",
            "secondary curriculum",
            "WASSCE",
            "SHS programs",
        ],
        "subdomains": ["shs", "tvet"],
        "parent": "education_system",
    },

    "tertiary_education": {
        "label": "Tertiary Education",
        "topics": [
            "tertiary education",
            "university",
            "higher education",
            "polytechnic",
            "college of education",
            "university admission",
            "tertiary programs",
            "degree programs",
            "postgraduate education",
        ],
        "parent": "education_system",
    },

    # ==========================================================
    # MINISTRY OF EDUCATION
    # ==========================================================
    "ministry_of_education": {
        "label": "Ministry of Education",
        "topics": [
            "Ministry of Education Ghana",
            "education policy",
            "national education policy",
            "education reforms",
            "education sector development",
            "education planning",
            "education statistics",
            "policy implementation",
            "sector plans",
        ],
        "subdomains": ["current_policies"],
    },

    # ==========================================================
    # GHANA EDUCATION SERVICE (GES)
    # ==========================================================
    "ges": {
        "label": "Ghana Education Service",
        "topics": [
            "Ghana Education Service",
            "GES",
            "teacher responsibilities",
            "school administration",
            "headteacher responsibilities",
            "headmaster responsibilities",
            "school leadership",
            "education supervision",
            "district education",
            "education directorate",
            "school improvement",
            "academic supervision",
        ],
        "subdomains": ["school_administration", "school_leadership"],
    },

    # ==========================================================
    # NaCCA - CURRICULUM
    # ==========================================================
    "nacca": {
        "label": "NaCCA and Curriculum",
        "topics": [
            "NaCCA",
            "National Council for Curriculum and Assessment",
            "Ghana curriculum",
            "curriculum standards",
            "learning outcomes",
            "standards-based curriculum",
            "Common Core Programme",
            "CCP",
            "curriculum planning",
            "curriculum review",
            "approved materials",
            "instructional materials",
        ],
        "subdomains": ["curriculum", "assessment"],
    },

    # ==========================================================
    # CURRICULUM
    # ==========================================================
    "curriculum": {
        "label": "Curriculum",
        "topics": [
            "curriculum",
            "standards-based curriculum",
            "competency-based curriculum",
            "learning outcomes",
            "curriculum content",
            "subject standards",
            "curriculum implementation",
            "curriculum review",
            "core competencies",
            "learning areas",
            "strands",
            "indicators",
        ],
        "subdomains": ["kg", "primary", "jhs", "shs"],
    },

    # ==========================================================
    # KINDERGARTEN (KG)
    # ==========================================================
    "kg": {
        "label": "Kindergarten",
        "topics": [
            "kindergarten",
            "KG",
            "early childhood education",
            "pre-primary",
            "kindergarten curriculum",
            "foundational literacy",
            "foundational numeracy",
            "play-based learning",
            "early learning",
            "child development",
            "kindergarten assessment",
            "KG education",
        ],
        "parent": "curriculum",
    },

    # ==========================================================
    # PRIMARY EDUCATION
    # ==========================================================
    "primary": {
        "label": "Primary Education",
        "topics": [
            "primary education",
            "primary school",
            "Basic 1-6",
            "primary curriculum",
            "primary subjects",
            "literacy",
            "numeracy",
            "science",
            "social studies",
            "creative arts",
            "primary assessment",
            "our world our people",
            "rme",
            "ghanian language",
        ],
        "parent": "curriculum",
    },

    # ==========================================================
    # JUNIOR HIGH SCHOOL (JHS)
    # ==========================================================
    "jhs": {
        "label": "Junior High School",
        "topics": [
            "junior high school",
            "JHS",
            "Basic 7-9",
            "JHS curriculum",
            "BECE",
            "BECE preparation",
            "JHS subjects",
            "integrated science",
            "social studies",
            "career technology",
            "computing",
            "rme",
            "mathematics",
            "english",
            "ghanian language",
            # JHS ICT topics
            "introduction to computers",
            "microsoft office applications",
            "word processing",
            "excel spreadsheets",
            "powerpoint presentations",
            "basic programming concepts",
            "internet safety",
            "digital citizenship",
            "computer literacy",
            "scratch programming",
            "basic coding",
            "file management",
        ],
        "parent": "curriculum",
        "subdomains": ["bece"],
    },

    # ==========================================================
    # SENIOR HIGH SCHOOL (SHS)
    # ==========================================================
    "shs": {
        "label": "Senior High School",
        "topics": [
            "senior high school",
            "SHS",
            "SHS 1-3",
            "SHS curriculum",
            "WASSCE",
            "WASSCE preparation",
            "SHS subjects",
            "core subjects",
            "elective subjects",
            "science",
            "arts",
            "business",
            "vocational",
            "academic pathways",
            # SHS ICT topics (Elective ICT)
            "computer hardware and software",
            "networking fundamentals",
            "database management",
            "web development",
            "programming languages",
            "python programming",
            "java programming",
            "visual basic programming",
            "cyber security",
            "operating systems",
            "computer architecture",
            "network topologies",
            "sql databases",
            "html and css",
            "javascript",
            "object-oriented programming",
            "software development",
        ],
        "parent": "secondary_education",
        "subdomains": ["wassce"],
    },

    # ==========================================================
    # TVET
    # ==========================================================
    "tvet": {
        "label": "Technical and Vocational Education",
        "topics": [
            "technical and vocational education",
            "TVET",
            "vocational education",
            "technical education",
            "skills development",
            "career pathways",
            "vocational training",
            "technical skills",
            "apprenticeship",
            "hands-on learning",
            "tvet curriculum",
            "vocational assessment",
        ],
        "parent": "secondary_education",
    },

    # ==========================================================
    # TEACHING AND LEARNING
    # ==========================================================
    "teaching_and_learning": {
        "label": "Teaching and Learning",
        "topics": [
            "lesson planning",
            "lesson objectives",
            "teaching strategies",
            "classroom management",
            "learner-centred teaching",
            "differentiated instruction",
            "continuous assessment",
            "formative assessment",
            "summative assessment",
            "remedial teaching",
            "teaching methods",
            "pedagogy",
            "active learning",
            "student engagement",
            "learning activities",
        ],
        "subdomains": ["classroom_management", "assessment", "teacher_development"],
    },

    # ==========================================================
    # CLASSROOM MANAGEMENT
    # ==========================================================
    "classroom_management": {
        "label": "Classroom Management",
        "topics": [
            "classroom management",
            "classroom discipline",
            "student behaviour",
            "positive reinforcement",
            "classroom routines",
            "classroom procedures",
            "student motivation",
            "classroom environment",
            "behaviour management",
            "conflict resolution",
            "classroom engagement",
        ],
        "parent": "teaching_and_learning",
    },

    # ==========================================================
    # ASSESSMENT
    # ==========================================================
    "assessment": {
        "label": "Assessment and Examinations",
        "topics": [
            "assessment",
            "continuous assessment",
            "formative assessment",
            "summative assessment",
            "school examinations",
            "internal examinations",
            "BECE",
            "WASSCE",
            "examination preparation",
            "student performance",
            "assessment methods",
            "grading",
            "marking",
            "assessment for learning",
            "assessment of learning",
        ],
        "subdomains": ["bece", "wassce"],
    },

    # ==========================================================
    # BECE
    # ==========================================================
    "bece": {
        "label": "BECE",
        "topics": [
            "BECE",
            "Basic Education Certificate Examination",
            "BECE preparation",
            "BECE subjects",
            "BECE grading",
            "BECE registration",
            "BECE results",
            "BECE past questions",
            "BECE examination rules",
        ],
        "parent": "assessment",
    },

    # ==========================================================
    # WASSCE
    # ==========================================================
    "wassce": {
        "label": "WASSCE",
        "topics": [
            "WASSCE",
            "West African Senior School Certificate Examination",
            "WASSCE preparation",
            "WASSCE subjects",
            "WASSCE grading",
            "WASSCE registration",
            "WASSCE results",
            "WASSCE past questions",
            "WASSCE examination rules",
            "WAEC",
        ],
        "parent": "assessment",
    },

    # ==========================================================
    # SCHOOL ADMINISTRATION
    # ==========================================================
    "school_administration": {
        "label": "School Administration",
        "topics": [
            "school administration",
            "school policies",
            "student records",
            "attendance management",
            "staff management",
            "school leadership",
            "academic administration",
            "school reporting",
            "school operations",
            "administrative procedures",
            "school calendar",
            "school events",
            "parent communication",
        ],
        "subdomains": ["school_leadership", "student_welfare"],
    },

    # ==========================================================
    # SCHOOL LEADERSHIP
    # ==========================================================
    "school_leadership": {
        "label": "School Leadership",
        "topics": [
            "school leadership",
            "headteacher",
            "headmaster",
            "school principal",
            "leadership skills",
            "school management",
            "strategic planning",
            "staff supervision",
            "school improvement",
            "vision setting",
            "educational leadership",
        ],
        "parent": "school_administration",
    },

    # ==========================================================
    # STUDENT WELFARE
    # ==========================================================
    "student_welfare": {
        "label": "Student Welfare",
        "topics": [
            "student welfare",
            "student guidance",
            "academic support",
            "remedial support",
            "student motivation",
            "inclusive education",
            "special educational needs",
            "child protection",
            "school health",
            "student counselling",
            "wellbeing",
            "mental health",
            "safeguarding",
            "student safety",
        ],
        "subdomains": ["guidance_counselling", "inclusive_education", "child_protection", "school_health"],
    },

    # ==========================================================
    # GUIDANCE & COUNSELLING
    # ==========================================================
    "guidance_counselling": {
        "label": "Guidance and Counselling",
        "topics": [
            "guidance",
            "counselling",
            "student guidance",
            "career guidance",
            "career pathways",
            "academic counselling",
            "personal counselling",
            "student support",
            "mental health support",
            "peer counselling",
        ],
        "parent": "student_welfare",
    },

    # ==========================================================
    # INCLUSIVE EDUCATION
    # ==========================================================
    "inclusive_education": {
        "label": "Inclusive Education",
        "topics": [
            "inclusive education",
            "special educational needs",
            "SEN",
            "learning disabilities",
            "differentiated instruction",
            "accessibility",
            "special needs support",
            "inclusive practices",
            "equity in education",
            "diversity",
            "special education",
        ],
        "parent": "student_welfare",
    },

    # ==========================================================
    # CHILD PROTECTION
    # ==========================================================
    "child_protection": {
        "label": "Child Protection",
        "topics": [
            "child protection",
            "safeguarding",
            "child safety",
            "child rights",
            "reporting abuse",
            "safe schools",
            "student safety",
            "protection policies",
            "child welfare",
            "school safety",
        ],
        "parent": "student_welfare",
    },

    # ==========================================================
    # SCHOOL HEALTH
    # ==========================================================
    "school_health": {
        "label": "School Health",
        "topics": [
            "school health",
            "school health programme",
            "student health",
            "health education",
            "nutrition",
            "hygiene",
            "school feeding",
            "health services",
            "health promotion",
            "wellness",
        ],
        "parent": "student_welfare",
    },

    # ==========================================================
    # TEACHER PROFESSIONAL DEVELOPMENT
    # ==========================================================
    "teacher_development": {
        "label": "Teacher Professional Development",
        "topics": [
            "teacher professional development",
            "teacher training",
            "professional learning",
            "classroom practice",
            "teaching reflection",
            "instructional improvement",
            "CPD",
            "continuous professional development",
            "teacher growth",
            "mentoring",
            "coaching",
            "professional standards",
        ],
        "subdomains": ["teaching_and_learning"],
    },

    # ==========================================================
    # ICT IN EDUCATION - UPDATED WITH DETAILED TOPICS
    # ==========================================================
    "ict_in_education": {
        "label": "ICT in Education",
        "topics": [
            "ICT in education",
            "educational technology",
            "edtech",
            "digital learning",
            "technology integration",
            "computer literacy",
            "digital skills",
            "e-learning",
            "educational software",
            "online learning",
            "digital resources",
            # Basic ICT topics
            "introduction to computers",
            "microsoft office applications",
            "word processing",
            "spreadsheets",
            "presentation software",
            "basic programming concepts",
            "internet and online safety",
            "digital citizenship",
            # Advanced ICT topics
            "computer hardware and software",
            "networking fundamentals",
            "database management",
            "web development",
            "programming languages",
            "python programming",
            "java programming",
            "visual basic programming",
            "computer components",
            "operating systems",
            "LAN and WAN",
            "HTML and CSS",
            "cyber security",
            "data management",
            "computer architecture",
            "software installation",
            "system maintenance",
            "network security",
            "object-oriented programming",
            "scratch programming",
            "basic coding",
            "file management",
        ],
    },

    # ==========================================================
    # EDUCATIONAL PLANNING
    # ==========================================================
    "educational_planning": {
        "label": "Educational Planning",
        "topics": [
            "educational planning",
            "education planning",
            "strategic planning",
            "school development",
            "education sector planning",
            "resource planning",
            "budget planning",
            "institutional planning",
            "planning processes",
        ],
    },

    # ==========================================================
    # CAREER GUIDANCE
    # ==========================================================
    "career_guidance": {
        "label": "Career Guidance",
        "topics": [
            "career guidance",
            "career pathways",
            "career counselling",
            "job readiness",
            "career choices",
            "career exploration",
            "vocational guidance",
            "further education",
            "tertiary pathways",
            "career development",
        ],
        "subdomains": ["tertiary_pathways"],
    },

    # ==========================================================
    # TERTIARY PATHWAYS
    # ==========================================================
    "tertiary_pathways": {
        "label": "Tertiary Pathways",
        "topics": [
            "tertiary education",
            "university admission",
            "tertiary pathways",
            "higher education",
            "university application",
            "tertiary courses",
            "degree programmes",
            "vocational tertiary",
            "tertiary alternatives",
        ],
        "parent": "career_guidance",
    },

    # ==========================================================
    # SCHOLARSHIPS
    # ==========================================================
    "scholarships": {
        "label": "Scholarships",
        "topics": [
            "scholarships",
            "scholarship opportunities",
            "bursaries",
            "financial aid",
            "student grants",
            "scholarship programmes",
            "aid for needy students",
            "GES scholarships",
            "educational grants",
        ],
    },

    # ==========================================================
    # CURRENT EDUCATION POLICIES
    # ==========================================================
    "current_policies": {
        "label": "Current Education Policies",
        "topics": [
            "education policies",
            "current policies",
            "GES policies",
            "MoE policies",
            "policy updates",
            "education reforms",
            "policy implementation",
            "new education policies",
            "policy changes",
            "circulars",
            "directives",
            "education regulations",
        ],
        "parent": "ministry_of_education",
    },

    # ==========================================================
    # EDUCATION STATISTICS
    # ==========================================================
    "education_statistics": {
        "label": "Education Statistics",
        "topics": [
            "education statistics",
            "enrolment statistics",
            "completion rates",
            "dropout rates",
            "education indicators",
            "school statistics",
            "performance statistics",
            "education data",
            "student statistics",
            "teacher statistics",
        ],
    },
}


# ==============================================================
# DOMAIN PARENT RELATIONSHIPS (for building hierarchy)
# ==============================================================

def get_domain_hierarchy():
    """Build a nested hierarchy of all domains."""
    hierarchy = {}

    # First pass: collect all top-level domains
    for key, domain in GHANA_EDUCATION_DOMAINS.items():
        if 'parent' not in domain:
            hierarchy[key] = {
                'label': domain['label'],
                'topics': domain['topics'],
                'children': []
            }

    # Second pass: attach children to parents
    for key, domain in GHANA_EDUCATION_DOMAINS.items():
        parent_key = domain.get('parent')
        if parent_key and parent_key in hierarchy:
            hierarchy[parent_key]['children'].append({
                'key': key,
                'label': domain['label'],
                'topics': domain['topics'],
            })

    return hierarchy


# ==============================================================
# SEARCH FUNCTION
# ==============================================================

def search_ghana_education(query, limit=8):
    """
    Lightweight, offline keyword search over the local Ghana Education
    knowledge domain index (GHANA_EDUCATION_DOMAINS).

    This is distinct from research_service.EducationResearchService, which
    does LIVE web research against official sources (Tavily) for
    time-sensitive facts. This function is instant and local: "which of our
    known Ghana-education knowledge areas does this question touch?" -- used
    to ground the Copilot's system prompt with relevant domain context even
    when live research isn't triggered.

    Returns a list of dicts, most relevant first:
        [{"domain": "nacca", "label": "NaCCA and Curriculum",
          "matched_topics": [...], "score": 2}, ...]
    """
    if not query:
        return []

    normalized = str(query).lower()

    scored = []
    for domain_key, domain in GHANA_EDUCATION_DOMAINS.items():
        matched_topics = [
            topic for topic in domain["topics"]
            if topic.lower() in normalized or normalized in topic.lower()
        ]
        if matched_topics:
            scored.append({
                "domain": domain_key,
                "label": domain["label"],
                "matched_topics": matched_topics,
                "score": len(matched_topics),
                "subdomains": domain.get("subdomains", []),
                "parent": domain.get("parent"),
            })

    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:limit]


# ==============================================================
# ROLE ACCESS
# ==============================================================

GHANA_EDUCATION_AI_ACCESS = {
    "SUPER_ADMIN": True,
    "SCHOOL_ADMIN": True,
    "HEADMASTER": True,
    "PRINCIPAL": True,
    "TEACHER": True,
    "HOD": True,
    "REGISTRAR": True,
    "SECRETARY": True,
    "BURSAR": True,
    "PARENT": True,
    "STUDENT": True,
}


# ==============================================================
# BASIC ACCESS CHECK
# ==============================================================

def can_access_ghana_education(user):
    """
    Determine whether a user may use the general Ghana Education
    knowledge capability.

    This is separate from access to private school records.
    """

    if not user or not getattr(user, "is_authenticated", False):
        return False

    role = getattr(user, "role", None)

    return bool(
        role
        and GHANA_EDUCATION_AI_ACCESS.get(
            role,
            False,
        )
    )


# ==============================================================
# DOMAIN LIST
# ==============================================================

def get_ghana_education_domains(user=None):
    """
    Return the available Ghana Education knowledge domains.

    If a user is supplied, access is checked first.
    """

    if user is not None and not can_access_ghana_education(user):
        return {}

    return GHANA_EDUCATION_DOMAINS.copy()


# ==============================================================
# KNOWLEDGE SUMMARY
# ==============================================================

def get_ghana_education_summary(user=None):
    """
    Return a compact description of the Ghana Education knowledge
    available to the Copilot.
    """

    if user is not None and not can_access_ghana_education(user):
        return {
            "enabled": False,
            "domains": [],
            "hierarchy": {},
        }

    return {
        "enabled": True,
        "domains": [
            {
                "key": key,
                "label": value["label"],
                "topics": value["topics"],
                "parent": value.get("parent"),
                "subdomains": value.get("subdomains", []),
            }
            for key, value in GHANA_EDUCATION_DOMAINS.items()
        ],
        "hierarchy": get_domain_hierarchy(),
    }