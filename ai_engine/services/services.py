# ai_engine/services.py
from django.conf import settings


class AIService:
    """Central AI gateway used by the school-management application.

    Groq is accessed through the official Groq SDK first and a small HTTP
    fallback second.  The fallback is intentional: it prevents an SDK/version
    mismatch from making the report-card comment engine look offline.
    """

    LAST_ERROR = ""

    @staticmethod
    def _api_key():
        # Read settings and the process environment.  Reading the environment
        # at call time is useful on Render/Docker where variables may be
        # injected by the process rather than by the local .env file.
        import os
        return (
            getattr(settings, 'GROQ_API_KEY', '')
            or os.getenv('GROQ_API_KEY', '')
            or os.getenv('GROQ_API_TOKEN', '')
        ).strip().strip('\"').strip("'")

    @staticmethod
    def _model_candidates(preferred=None):
        configured = preferred or getattr(settings, 'GROQ_MODEL', '') or 'openai/gpt-oss-120b'
        candidates = [configured]
        # GPT-OSS 20B is a lighter production model and is an excellent fit
        # for short report-card comments.  Keep 120B as the fallback.
        for model in ('openai/gpt-oss-20b', 'openai/gpt-oss-120b'):
            if model not in candidates:
                candidates.append(model)
        return candidates

    @staticmethod
    def _call_groq(system_prompt, user_prompt, max_tokens=200, temperature=0.7, model=None):
        import requests

        api_key = AIService._api_key()
        AIService.LAST_ERROR = ""
        if not api_key:
            AIService.LAST_ERROR = 'GROQ_API_KEY is not configured.'
            return None

        timeout = int(getattr(settings, 'GROQ_TIMEOUT', 60) or 60)
        base_url = (getattr(settings, 'GROQ_API_BASE_URL', '') or
                    'https://api.groq.com/openai/v1').rstrip('/')
        endpoint = base_url + '/chat/completions'
        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ]
        last_error = ''

        # 1) Official Groq SDK.
        try:
            from groq import Groq
            client = Groq(api_key=api_key, timeout=timeout)
            for candidate in AIService._model_candidates(model):
                try:
                    response = client.chat.completions.create(
                        model=candidate,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        include_reasoning=False,
                        reasoning_effort='low',
                    )
                    content = response.choices[0].message.content if response.choices else ''
                    if content and content.strip():
                        return content.strip()
                    last_error = f'Groq returned an empty response for {candidate}.'
                except Exception as exc:
                    last_error = str(exc)
                    # If this is an authentication, quota, or network error,
                    # the next HTTP attempt is more useful than another model.
                    text = last_error.lower()
                    if any(x in text for x in ('401', '403', '429', 'authentication', 'invalid api key', 'rate limit', 'timeout', 'connection')):
                        break
        except Exception as exc:
            last_error = str(exc)

        # 2) Official OpenAI-compatible Groq HTTP endpoint.
        # This also handles installations where the groq SDK is old/broken.
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }
        for candidate in AIService._model_candidates(model):
            payload = {
                'model': candidate,
                'messages': messages,
                'max_tokens': max_tokens,
                'temperature': temperature,
                'include_reasoning': False,
                'reasoning_effort': 'low',
            }
            try:
                response = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
                if response.ok:
                    data = response.json()
                    content = (((data.get('choices') or [{}])[0].get('message') or {}).get('content') or '')
                    if content.strip():
                        return content.strip()
                    last_error = f'Groq returned an empty response for {candidate}.'
                else:
                    try:
                        error_data = response.json()
                        error_message = ((error_data.get('error') or {}).get('message') or response.text)
                    except Exception:
                        error_message = response.text
                    last_error = f'HTTP {response.status_code}: {error_message}'
                    # Don't retry a bad key/quota endlessly. Model fallback is
                    # useful for model-specific 400/404/403 errors only.
                    if response.status_code in (401, 429):
                        break
            except requests.RequestException as exc:
                last_error = str(exc)
                break

        AIService.LAST_ERROR = (last_error or 'Unknown Groq API error')[:1000]
        return None

    @staticmethod
    def generate_student_report(student_name, subject, grade, attendance_percentage, teacher_notes):
        """
        Calls Groq to auto-generate school-ready report feedback for a
        single assessment/subject.

        NOTE: this previously called the `openai` package/API, but this
        project's settings.py and requirements.txt are both configured for
        Groq (GROQ_API_KEY, groq==0.33.0) - the `openai` package isn't even
        installed, so this would raise ModuleNotFoundError on import. Fixed
        to use the Groq client, which is API-compatible with the OpenAI
        chat.completions shape used below.
        """
        if not getattr(settings, 'GROQ_API_KEY', ''):
            return "AI feedback generation offline. (API Key missing)"

        prompt = f"""
        You are an expert school academic advisor. Write a constructive, professional, and encouraging 
        report card evaluation for a student based on these parameters:

        - Student Name: {student_name}
        - Subject: {subject}
        - Grade achieved: {grade}
        - Attendance rate: {attendance_percentage}%
        - Teacher raw observations: "{teacher_notes}"

        Deliver a paragraph (3-4 sentences) that highlights their performance, addresses potential attendance 
        impacts if any, and suggests practical ways to improve or excel further. Use a highly encouraging but objective tone.
        """
        try:
            result = AIService._call_groq(
                "You are an experienced, professional school educator.", prompt, max_tokens=200
            )
            return result if result is not None else "AI feedback generation offline. (API Key missing)"
        except Exception as e:
            return f"Error generating automated feedback: {str(e)}"

    @staticmethod
    def generate_report_comment(prompt, role='school teacher'):
        """Generate one official report-card comment. Returns empty string on API failure."""
        try:
            result = AIService._call_groq(
                f"You are a professional Ghanaian school {role}. Write concise, factual report-card comments.",
                prompt, max_tokens=220, temperature=0.45,
                model=getattr(settings, 'GROQ_COMMENT_MODEL', 'openai/gpt-oss-20b'),
            )
            return (result or '').strip()
        except Exception:
            return ''

    @staticmethod
    def generate_report_card_narrative(student_name, academic_term_name, overall_average, subject_breakdown, attendance_rate):
        """
        Holistic, whole-term comment for a student's report card - covers
        every subject and attendance together, the way a form/homeroom
        teacher's summary comment actually reads, rather than one isolated
        paragraph per subject. Returns '' if the API key is missing/invalid
        or the call fails - callers must handle an empty narrative
        gracefully (the report card is still usable without it).
        """
        subject_lines = "\n".join(
            f"- {s['subject']}: {s['average']}% average across {s['assessment_count']} assessment(s)"
            for s in subject_breakdown
        ) or "- No graded assessments on record yet this term."

        attendance_line = (
            f"{attendance_rate}% attendance this term." if attendance_rate is not None
            else "No attendance data recorded yet this term."
        )

        prompt = f"""
        You are a form/homeroom teacher writing the summary comment on a student's report card.

        Student: {student_name}
        Term: {academic_term_name}
        Overall average: {overall_average if overall_average is not None else "N/A"}%
        {attendance_line}

        Subject performance:
        {subject_lines}

        Write a 3-4 sentence report card comment for the parent/guardian: acknowledge genuine
        strengths, name the subject(s) that need the most attention if any stand out, and give one
        concrete, practical suggestion for next term. Professional, warm, and honest - do not
        exaggerate praise for a weak term or undersell a strong one.
        """
        try:
            result = AIService._call_groq(
                "You are a warm, honest, professional form/homeroom teacher writing report card comments.",
                prompt,
                max_tokens=220,
                temperature=0.6,
            )
            return result or ""
        except Exception:
            return ""

    @staticmethod
    def generate_payment_reminder(student_name, fee_category_name, total_amount, balance_due, overdue_days, due_date):
        """
        Drafts a payment reminder for one overdue/at-risk invoice, for an
        admin to review, edit, and send themselves - there's no SMS/email/
        WhatsApp gateway wired into this project, so this returns text to
        copy, not a dispatched message.

        Deliberately not shaming or alarmist: this goes to a parent, in a
        Ghanaian school context where a blunt automated demand can do real
        relationship damage. Returns a clear offline message (like
        generate_student_report) rather than a silent empty string, since
        this is a single manual action a user is actively waiting on.
        """
        if not getattr(settings, 'GROQ_API_KEY', ''):
            return "AI reminder drafting offline. (API Key missing)"

        overdue_line = (
            f"{overdue_days} day(s) past the due date of {due_date}." if overdue_days > 0
            else f"due on {due_date} (not yet overdue - a friendly advance reminder)."
        )

        # This school operates in Ghana - all amounts are in Ghana Cedis, never US dollars.
        total_amount_display = f"GH₵{total_amount:,.2f}"
        balance_due_display = f"GH₵{balance_due:,.2f}"

        prompt = f"""
        You are a school administrator's assistant drafting a fee payment reminder message, to be sent
        to a parent/guardian by WhatsApp, SMS, or email.

        Student: {student_name}
        Fee: {fee_category_name}
        Total amount: {total_amount_display}
        Balance still owed: {balance_due_display}
        Status: {overdue_line}

        Write a short, polite, professional reminder (3-5 sentences). Be warm and non-accusatory - many
        families are dealing with real financial hardship. State the facts plainly (what's owed, since
        when), invite them to reach out if they need a payment plan or have already paid and this
        crossed in the mail, and thank them. Do not threaten consequences (no mention of expulsion,
        withholding results, etc). Sign off generically as "The School Administration Office".

        Currency: this school is in Ghana. All amounts are in Ghana Cedis. Always use the symbol "GH₵"
        exactly as given above (e.g. "GH₵1,200.00") - never use "$", "USD", or any other currency symbol.
        """
        try:
            result = AIService._call_groq(
                "You are a courteous, professional school administration office drafting a fee reminder.",
                prompt,
                max_tokens=220,
                temperature=0.5,
            )
            return result if result is not None else "AI reminder drafting offline. (API Key missing)"
        except Exception as e:
            return f"Error generating reminder draft: {str(e)}"

    @staticmethod
    def generate_substitute_handover_note(substitute_name, subject_name, class_name, period_label,
                                            is_subject_qualified, absent_teacher_name):
        """
        Drafts a short briefing for a substitute covering one period.
        Honest limitation: this system has no lesson-plan/topic data
        anywhere, so the note can't reference what the class was actually
        covering - it gives sound generic guidance instead (attendance,
        review/independent work, classroom management) rather than
        pretending to know today's lesson content.
        """
        if not getattr(settings, 'GROQ_API_KEY', ''):
            return "AI handover note offline. (API Key missing)"

        qualification_line = (
            f"{substitute_name} is qualified to teach {subject_name}."
            if is_subject_qualified else
            f"{substitute_name} is NOT a specialist in {subject_name} - this is general supervision cover, "
            f"not a subject lesson."
        )

        prompt = f"""
        Write a short handover note (3-4 sentences) for a substitute teacher covering one class period.

        Substitute: {substitute_name}
        Covering for: {absent_teacher_name} (absent today)
        Subject: {subject_name}
        Class: {class_name}
        Period: {period_label}
        {qualification_line}

        No lesson plan or topic information is available for this specific period, so do NOT invent what
        the class was covering. Instead give practical, generic guidance: take attendance first, then
        either continue independent/review work appropriate to the subject if the substitute feels
        comfortable, or supervise quiet study if not. Keep tone calm and reassuring - this is a routine
        cover assignment, not a crisis.
        """
        try:
            result = AIService._call_groq(
                "You are a calm, practical school administration assistant briefing a substitute teacher.",
                prompt,
                max_tokens=180,
                temperature=0.5,
            )
            return result if result is not None else "AI handover note offline. (API Key missing)"
        except Exception as e:
            return f"Error generating handover note: {str(e)}"