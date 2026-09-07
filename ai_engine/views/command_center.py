# ai_engine/views/command_center.py
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from ai_engine.services.command_center_service import CommandCenterService
from ai_engine.services.predictive_engine import PredictiveIntelligenceService
from ai_engine.services.role_ai_policy import ROLE_POLICIES
from ai_engine.services.role_command_center import RoleCommandCenterService
from students.models import Student
from ai_engine.services.permissions import (
    get_ai_permissions
)
from ai_engine.services.context import (
    SchoolAIContext
)

from django.http import JsonResponse
from django.views import View
from ai_engine.services.intervention_engine import EarlyWarningInterventionEngine
# Import the allowed_students function
from ai_engine.services.copilot_context import allowed_students

ADMIN_COMMAND_ROLES = {"SUPER_ADMIN", "SCHOOL_ADMIN"}
AI_COMMAND_ROLES = set(ROLE_POLICIES.keys())


@login_required
def ai_command_center(request):
    """
    Role-aware AI School Command Center.

    IMPORTANT:
    The command center must never expose school-wide AI intelligence
    simply because the user belongs to the school.

    The user's role policy determines what data can be presented.
    """

    permissions = get_ai_permissions(request.user)

    if not permissions.can_chat and not permissions.can_research:
        messages.error(
            request,
            "You don't have permission to access the AI School Copilot."
        )

        return redirect("dashboard")

    # ========================================================================
    # SCHOOL
    # ========================================================================

    school = getattr(
        request.user,
        "school",
        None,
    )

    # ========================================================================
    # ROLE-SCOPED COMMAND CENTER
    # ========================================================================

    context = {}

    if school:
        context = RoleCommandCenterService.build(
            request.user,
            school,
        )

    # ========================================================================
    # DETAILED AI CONTEXT
    # ========================================================================

    # Fixed: Properly instantiate and call the build method
    ai_context = SchoolAIContext(
        request.user
    ).build()

    # ========================================================================
    # SCHOOL-WIDE INTELLIGENCE
    # ========================================================================
    #
    # Only roles explicitly granted the capability receive this.
    #
    # This prevents:
    #
    #   TEACHER
    #   PARENT
    #   STUDENT
    #   SECRETARY
    #
    # from automatically receiving:
    #
    #   school-wide risk counts
    #   school-wide parent chats
    #   school-wide invoices
    #   school-wide recommendations
    #   school-wide AI activity
    #
    # ========================================================================

    if (
        school
        and permissions.can_view_school_intelligence
    ):
        try:
            context.update(
                CommandCenterService.build_dashboard(
                    school
                )
            )
        except Exception:
            # Do not allow an intelligence/dashboard failure
            # to break the user's entire command center.
            pass

    # ========================================================================
    # COMMON AI CONTEXT
    # ========================================================================

    context.update({
        "ai_permissions": permissions,
        "ai_context": ai_context,

        "ai_role": getattr(
            request.user,
            "role",
            "",
        ),

        "ai_capabilities": permissions.capabilities,

        "ai_student_scope": permissions.student_scope,

        "ai_class_scope": permissions.class_scope,
    })

    return render(
        request,
        "ai_engine/command_center.html",
        context,
    )


@login_required
def predictive_student_detail(request, student_id):
    if request.user.role not in ADMIN_COMMAND_ROLES:
        messages.error(request, "Predictive student intelligence is restricted to school administrators.")
        return redirect("dashboard:dashboard")

    school = request.user.school
    student = get_object_or_404(
        Student.objects.select_related("user"),
        id=student_id,
        school=school,
        is_active=True,
    )
    try:
        prediction = PredictiveIntelligenceService.predict_student(student)
    except Exception:
        prediction = None
    if not prediction:
        messages.warning(request, "There is not enough data to generate a predictive assessment for this student.")
    return render(request, "ai_engine/predictive_student_detail.html", {"student": student, "prediction": prediction})


@login_required
def intervention_center(request):
    """
    Role-aware Early-Warning Intervention Center.

    Students are ALWAYS restricted through allowed_students().
    """

    permissions = get_ai_permissions(request.user)

    if not permissions.can_view_risk:
        messages.error(
            request,
            "You don't have permission to access predictive risk intelligence."
        )

        return redirect("dashboard:dashboard")

    school = getattr(
        request.user,
        "school",
        None,
    )

    high_risk_students = []

    if school:
        # ================================================================
        # IMPORTANT:
        # NEVER query all students directly here.
        #
        # allowed_students() applies the user's actual student scope.
        # ================================================================

        students = allowed_students(
            request.user,
            school,
        ).select_related(
            "user",
            "school_class",
            "grade_level",
        )[:50]

        for student in students:

            try:
                engine = EarlyWarningInterventionEngine(
                    student
                )

                profile = (
                    engine.calculate_holistic_risk_profile()
                )

                if (
                    profile.get(
                        "composite_risk_score",
                        0,
                    ) > 0.5
                    or profile.get(
                        "recommended_interventions",
                        [],
                    )
                ):
                    student.risk_profile = profile
                    high_risk_students.append(
                        student
                    )

            except Exception:
                continue

    high_risk_students.sort(
        key=lambda student: getattr(
            student,
            "risk_profile",
            {},
        ).get(
            "composite_risk_score",
            0,
        ),
        reverse=True,
    )

    context = {
        "high_risk_students": high_risk_students,
        "ai_permissions": permissions,
        "ai_student_scope": permissions.student_scope,
    }

    return render(
        request,
        "ai_engine/intervention_center.html",
        context,
    )


class StudentInterventionView(View):
    """
    Role-aware intervention API.

    Every student lookup is performed through allowed_students()
    so the user cannot bypass the Copilot/student authorization
    boundary by manually changing the URL.
    """

    def _get_authorized_student(
        self,
        request,
        student_id,
    ):
        permissions = get_ai_permissions(
            request.user
        )

        if not permissions.can_view_risk:
            return None, permissions

        school = getattr(
            request.user,
            "school",
            None,
        )

        if not school:
            return None, permissions

        student = (
            allowed_students(
                request.user,
                school,
            )
            .select_related(
                "user",
                "school_class",
                "grade_level",
            )
            .filter(
                pk=student_id,
            )
            .first()
        )

        return student, permissions

    def get(
        self,
        request,
        student_id,
    ):
        student, permissions = (
            self._get_authorized_student(
                request,
                student_id,
            )
        )

        if not student:
            return JsonResponse(
                {
                    "status": "error",
                    "message": (
                        "Student not found or you are not "
                        "authorized to access this student."
                    ),
                },
                status=404,
            )

        try:
            engine = EarlyWarningInterventionEngine(
                student
            )

            profile = (
                engine.calculate_holistic_risk_profile()
            )

            return JsonResponse(
                {
                    "status": "success",
                    "data": profile,
                }
            )

        except Exception:
            return JsonResponse(
                {
                    "status": "error",
                    "message": (
                        "Unable to calculate the intervention "
                        "profile at this time."
                    ),
                },
                status=500,
            )

    def post(
        self,
        request,
        student_id,
    ):
        student, permissions = (
            self._get_authorized_student(
                request,
                student_id,
            )
        )

        if not student:
            return JsonResponse(
                {
                    "status": "error",
                    "message": (
                        "Student not found or you are not "
                        "authorized to access this student."
                    ),
                },
                status=404,
            )

        try:
            engine = EarlyWarningInterventionEngine(
                student
            )

            execution = (
                engine.execute_automated_actions(
                    dry_run=False
                )
            )

            return JsonResponse(
                {
                    "status": "success",
                    "data": execution,
                }
            )

        except Exception:
            return JsonResponse(
                {
                    "status": "error",
                    "message": (
                        "Unable to execute the intervention "
                        "at this time."
                    ),
                },
                status=500,
            )