# ai_engine/services/intent_detector.py
"""
Advanced Intent Detection for School Operations

Detects the user's intent from natural language questions
and maps them to the appropriate AI engine.
"""

import re
from typing import Dict, List, Tuple, Optional


class IntentDetector:
    """
    Detects the intent of a user's question and maps it to the appropriate engine.
    """

    # ==========================================================
    # INTENT KEYWORDS MAPPING
    # ==========================================================

    INTENT_KEYWORDS = {
        # ==========================================================
        # STUDENT MANAGEMENT
        # ==========================================================
        "students": {
            "keywords": [
                "student", "students", "learner", "learners", "pupil", "pupils",
                "admission", "enrollment", "enrolled", "register", "registration",
                "list", "all students", "active students",
                "search student", "find student", "student profile",
                "student record", "student details", "student information",
            ],
            "description": "Student management and records",
            "capability": "students",
        },

        # ==========================================================
        # ACADEMICS / TEACHING
        # ==========================================================
        "academics": {
            "keywords": [
                "class", "classes", "subject", "subjects", "course", "courses",
                "grade", "grades", "mark", "marks", "score", "scores",
                "assessment", "assessments", "result", "results",
                "lesson", "lessons", "lesson plan", "lesson planning",
                "curriculum", "syllabus", "teaching", "teacher", "teachers",
                "classroom", "school class", "class list",
                "academic", "performance", "progress",
            ],
            "description": "Academic management and teaching",
            "capability": "academics",
        },

        # ==========================================================
        # TIMETABLING
        # ==========================================================
        "timetable": {
            "keywords": [
                "timetable", "time table", "schedule", "period", "periods",
                "class schedule", "teacher schedule", "room schedule",
                "timetabler", "timetable generator", "auto timetable",
                "clash", "conflict", "free period",
            ],
            "description": "Timetable and scheduling",
            "capability": "timetable",
        },

        # ==========================================================
        # ATTENDANCE
        # ==========================================================
        "attendance": {
            "keywords": [
                "attendance", "present", "absent", "absence", "absences",
                "late", "lateness", "roll call", "register",
                "attendance rate", "attendance report",
                "today's attendance", "daily attendance",
                "class attendance", "student attendance",
                "attendance tracking", "attendance record",
            ],
            "description": "Attendance tracking and reporting",
            "capability": "attendance",
        },

        # ==========================================================
        # EXAMS & ASSESSMENTS
        # ==========================================================
        "exam": {
            "keywords": [
                "exam", "exams", "examination", "examinations",
                "question", "questions", "quiz", "test", "tests",
                "generate exam", "create exam", "ai exam",
                "bece", "wassce", "waec", "external exam",
                "exam result", "exam grade", "assessment",
                "question bank", "practice questions",
            ],
            "description": "Exam generation and management",
            "capability": "exam",
        },

        # ==========================================================
        # RISK & EARLY WARNING
        # ==========================================================
        "risk": {
            "keywords": [
                "risk", "risks", "dropout", "drop out", "dropping out",
                "early warning", "intervention", "at-risk",
                "warning", "alert", "alerts",
                "high risk", "critical risk", "student risk",
                "risk assessment", "risk prediction",
                "warning signs", "flag", "flags",
            ],
            "description": "Risk assessment and early warning",
            "capability": "risk",
        },

        # ==========================================================
        # REPORT CARDS
        # ==========================================================
        "report": {
            "keywords": [
                "report", "reports", "report card", "report cards",
                "comment", "comments", "remark", "remarks",
                "narrative", "student report",
                "progress report", "term report",
                "finalize report", "publish report",
                "report narrative", "ai comment",
            ],
            "description": "Report cards and comments",
            "capability": "report",
        },

        # ==========================================================
        # FINANCE & FEES
        # ==========================================================
        "finance": {
            "keywords": [
                "fee", "fees", "payment", "payments", "invoice", "invoices",
                "balance", "balances", "billing", "billed",
                "outstanding", "overdue", "debt", "receivable",
                "collection", "collected", "revenue",
                "finance", "financial", "money", "cash",
                "income", "expense", "expenses",
            ],
            "description": "Finance, fees, and invoicing",
            "capability": "finance",
        },

        # ==========================================================
        # STAFF / HR
        # ==========================================================
        "staff": {
            "keywords": [
                "staff", "teacher", "teachers", "employee", "employees",
                "staff list", "teacher list", "staff profile",
                "hire", "recruitment", "staff record",
                "staff information", "staff details",
                "department", "departments", "hod", "head of department",
                "staff leave", "staff absence", "substitute",
                "staff count", "how many staff",
                "active staff", "inactive staff",
            ],
            "description": "Staff management and records",
            "capability": "staff",
        },

        # ==========================================================
        # PAYROLL
        # ==========================================================
        "payroll": {
            "keywords": [
                "payroll", "salary", "salaries", "pay", "wages",
                "payment", "staff payment", "teacher pay",
                "monthly salary", "salary slip", "payslip",
                "payroll report", "payroll summary",
                "earnings", "deduction", "deductions",
                "bank transfer", "salary schedule",
                "gross pay", "net pay", "basic salary",
                "allowance", "allowances",
            ],
            "description": "Staff payroll and salaries",
            "capability": "payroll",
        },

        # ==========================================================
        # PARENT ASSISTANT
        # ==========================================================
        "parent": {
            "keywords": [
                "parent", "parents", "guardian", "guardians",
                "my child", "my children", "child's",
                "parent portal", "family", "family assistant",
                "parent account", "parent access",
            ],
            "description": "Parent assistant and engagement",
            "capability": "parent",
        },

        # ==========================================================
        # GHANA EDUCATION KNOWLEDGE
        # ==========================================================
        "ghana_education": {
            "keywords": [
                "ghana education", "education in ghana", "ghana school",
                "ges", "nacca", "ministry of education", "moe",
                "ghana curriculum", "standards-based curriculum",
                "common core programme", "ccp",
                "ghana education service", "education policy",
                "bece", "wassce", "waec",
                "ghanaian education", "ghana school system",
                "basic education", "secondary education",
                "ges policy", "ges regulations",
            ],
            "description": "Ghana Education System knowledge",
            "capability": "research",
        },

        # ==========================================================
        # RESEARCH
        # ==========================================================
        "research": {
            "keywords": [
                "research", "find out", "look up", "verify",
                "check the latest", "latest", "current",
                "official", "circular", "regulation",
                "deadline", "registration date", "policy update",
                "latest ges", "latest nacca", "latest waec",
                "current policy", "latest policy",
                "official guidance", "official rule",
            ],
            "description": "Research and official information",
            "capability": "research",
        },

        # ==========================================================
        # GENERAL / HELP
        # ==========================================================
        "general": {
            "keywords": [
                "help", "what can you do", "how to", "guide",
                "tell me about", "explain", "describe",
                "what is", "how does", "why",
                "information", "overview", "summary",
            ],
            "description": "General assistance",
            "capability": "general",
        },
    }

    # ==========================================================
    # CROSS-CATEGORY PATTERNS
    # ==========================================================

    CROSS_CATEGORY_PATTERNS = [
        # Student + Finance = Fee-related student queries
        {
            "intents": ["students", "finance"],
            "result": "finance",
            "pattern": r"student.*(fee|payment|invoice|balance|owing|unpaid|debt)"
        },
        # Student + Attendance = Attendance tracking
        {
            "intents": ["students", "attendance"],
            "result": "attendance",
            "pattern": r"student.*(attendance|present|absent|late)"
        },
        # Student + Exam = Exam performance
        {
            "intents": ["students", "exam"],
            "result": "exam",
            "pattern": r"student.*(exam|test|assessment|performance|grade)"
        },
        # Student + Risk = Risk assessment
        {
            "intents": ["students", "risk"],
            "result": "risk",
            "pattern": r"student.*(risk|dropout|warning|at-risk)"
        },
        # Staff + Payroll = Payroll queries
        {
            "intents": ["staff", "payroll"],
            "result": "payroll",
            "pattern": r"(staff|teacher|employee).*(salary|pay|wages|payroll)"
        },
        # Staff + Timetable = Schedule queries
        {
            "intents": ["staff", "timetable"],
            "result": "timetable",
            "pattern": r"(teacher|staff).*(schedule|timetable|class|period)"
        },
        # Staff + Leave = Leave management
        {
            "intents": ["staff", "attendance"],
            "result": "staff",
            "pattern": r"(staff|teacher|employee).*(leave|absence|off|holiday)"
        },
        # HOD + Staff = Department staff queries
        {
            "intents": ["staff", "academics"],
            "result": "staff",
            "pattern": r"(hod|head of department|department).*(staff|teacher|employee)"
        },
    ]

    def __init__(self):
        self._compile_patterns()

    def _compile_patterns(self):
        """Compile keyword patterns for faster matching."""
        self._keyword_patterns = {}
        for intent, data in self.INTENT_KEYWORDS.items():
            patterns = []
            for keyword in data["keywords"]:
                escaped = re.escape(keyword)
                patterns.append(rf'\b{escaped}\b')
            self._keyword_patterns[intent] = re.compile('|'.join(patterns), re.IGNORECASE)

        self._cross_patterns = []
        for pattern in self.CROSS_CATEGORY_PATTERNS:
            self._cross_patterns.append({
                "intents": pattern["intents"],
                "result": pattern["result"],
                "pattern": re.compile(pattern["pattern"], re.IGNORECASE)
            })

    def detect(self, question: str) -> Dict[str, any]:
        """
        Detect the intent of a question.

        Returns:
            Dict with:
            - intent: The detected intent key
            - description: Human-readable description
            - capability: The capability required
            - confidence: Confidence score (0-1)
            - keywords: Matched keywords
            - is_question: Boolean indicating if it's a question
        """
        if not question or not question.strip():
            return {
                "intent": "general",
                "description": "General assistance",
                "capability": "general",
                "confidence": 0.0,
                "keywords": [],
                "is_question": False,
            }

        question = question.strip()
        is_question = question.endswith('?') or question.lower().startswith(('what', 'who', 'where', 'when', 'why', 'how', 'is', 'are', 'do', 'does', 'can', 'could', 'would', 'should'))

        # 1. Check cross-category patterns first (highest priority)
        for pattern in self._cross_patterns:
            if pattern["pattern"].search(question):
                intent = pattern["result"]
                return {
                    "intent": intent,
                    "description": self.INTENT_KEYWORDS.get(intent, {}).get("description", intent),
                    "capability": self.INTENT_KEYWORDS.get(intent, {}).get("capability", intent),
                    "confidence": 0.95,
                    "keywords": [intent],
                    "is_question": is_question,
                    "cross_pattern": True,
                }

        # 2. Check each intent's keywords
        matched_intents = []
        for intent, pattern in self._keyword_patterns.items():
            matches = pattern.findall(question)
            if matches:
                matched_intents.append({
                    "intent": intent,
                    "matches": matches,
                    "count": len(matches),
                })

        if matched_intents:
            matched_intents.sort(key=lambda x: x["count"], reverse=True)
            best = matched_intents[0]

            confidence = min(0.95, 0.3 + (best["count"] * 0.15))
            if is_question:
                confidence += 0.05

            return {
                "intent": best["intent"],
                "description": self.INTENT_KEYWORDS[best["intent"]]["description"],
                "capability": self.INTENT_KEYWORDS[best["intent"]]["capability"],
                "confidence": min(confidence, 0.95),
                "keywords": best["matches"],
                "is_question": is_question,
                "all_matches": matched_intents,
            }

        # 3. Default to general
        return {
            "intent": "general",
            "description": "General assistance",
            "capability": "general",
            "confidence": 0.2,
            "keywords": [],
            "is_question": is_question,
        }

    def get_intent_description(self, intent: str) -> str:
        """Get a description for an intent."""
        return self.INTENT_KEYWORDS.get(intent, {}).get("description", intent)

    def get_all_intents(self) -> List[str]:
        """Get all available intents."""
        return list(self.INTENT_KEYWORDS.keys())