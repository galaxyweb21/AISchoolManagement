# academics/services/promotion_service.py
"""
Student Promotion Service - Handles automatic and manual student promotions.
"""

from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.db.models import Avg, Count, Q
import logging

from ..models import PromotionRule, PromotionBatch, StudentPromotion, SchoolClass
from assessments.models import Grade, Assessment
from attendance.models import Attendance
from students.models import Student, GradeLevel

logger = logging.getLogger(__name__)


class PromotionService:
    """
    Service for handling student promotions.
    """

    @staticmethod
    def evaluate_student_promotion(student, from_class, to_class, academic_term, promotion_rule=None):
        """
        Evaluate a single student's promotion eligibility.
        Returns a dict with promotion decision and details.
        """
        # Get grades for the specified term
        grades = Grade.objects.filter(
            student=student,
            assessment__academic_term=academic_term,
            assessment__school=student.school
        ).select_related('assessment')

        if not grades.exists():
            return {
                'eligible': False,
                'reason': 'No grades found for this term',
                'overall_average': None,
                'subjects_passed': 0,
                'subjects_failed': 0,
                'failed_subjects': [],
                'attendance_percentage': None,
                'status': 'PENDING'
            }

        # Calculate performance metrics
        total_score = 0
        total_subjects = 0
        subjects_passed = 0
        subjects_failed = 0
        failed_subjects = []

        for grade in grades:
            if grade.assessment.max_score > 0:
                percentage = (grade.score_achieved / grade.assessment.max_score) * 100
                total_score += percentage
                total_subjects += 1

                # Get minimum passing grade from rule or default to 50
                min_pass = promotion_rule.minimum_passing_grade if promotion_rule else Decimal('50.00')

                if percentage >= min_pass:
                    subjects_passed += 1
                else:
                    subjects_failed += 1
                    failed_subjects.append(grade.assessment.subject)

        overall_average = total_score / total_subjects if total_subjects > 0 else 0

        # Calculate attendance
        attendance_rate = PromotionService._calculate_attendance_rate(student, academic_term)

        # Check promotion criteria
        eligible, reason = PromotionService._check_eligibility(
            student, overall_average, subjects_passed, subjects_failed,
            failed_subjects, attendance_rate, promotion_rule
        )

        return {
            'eligible': eligible,
            'reason': reason,
            'overall_average': round(overall_average, 2),
            'subjects_passed': subjects_passed,
            'subjects_failed': subjects_failed,
            'failed_subjects': list(set(failed_subjects)),
            'attendance_percentage': attendance_rate,
            'status': 'PROMOTED' if eligible else 'REPEATED'
        }

    @staticmethod
    def _calculate_attendance_rate(student, academic_term):
        """Calculate student's attendance rate for the term."""
        attendances = Attendance.objects.filter(
            student=student,
            date__gte=academic_term.start_date,
            date__lte=academic_term.end_date
        )

        total = attendances.count()
        if total == 0:
            return None

        present = attendances.filter(status__in=['PRESENT', 'LATE']).count()
        return round((present / total) * 100, 2)

    @staticmethod
    def _check_eligibility(student, overall_average, subjects_passed, subjects_failed,
                           failed_subjects, attendance_rate, promotion_rule):
        """Check if a student meets promotion criteria."""
        if not promotion_rule:
            # Default rule: pass all subjects with 50% average
            if subjects_failed > 0:
                return False, f"Failed {subjects_failed} subject(s)"
            if overall_average < 50:
                return False, f"Overall average {overall_average:.2f}% is below 50%"
            return True, "Meets promotion criteria"

        # Check attendance
        if attendance_rate is not None:
            if attendance_rate < promotion_rule.minimum_attendance_percentage:
                return False, f"Attendance {attendance_rate:.2f}% is below {promotion_rule.minimum_attendance_percentage}%"

        # Check overall average
        if overall_average < promotion_rule.minimum_overall_average:
            return False, f"Overall average {overall_average:.2f}% is below {promotion_rule.minimum_overall_average}%"

        # Check subject failures
        min_pass = promotion_rule.minimum_subjects_to_pass
        if min_pass > 0 and subjects_passed < min_pass:
            return False, f"Passed only {subjects_passed} of {min_pass} required subjects"

        # Check for conditional promotion
        if subjects_failed > 0:
            if promotion_rule.allow_conditional_promotion:
                if subjects_failed <= promotion_rule.max_conditional_subjects:
                    return True, f"Conditional promotion allowed ({subjects_failed} failed subjects)"
            return False, f"Failed {subjects_failed} subject(s)"

        return True, "Meets all promotion criteria"

    @staticmethod
    @transaction.atomic
    def process_promotion_batch(school, from_grade_level_id, to_grade_level_id,
                               academic_term_id, promotion_rule_id=None, batch_name=None,
                               processed_by=None, mode='AUTO'):
        """
        Process a batch of student promotions.
        """
        from school.models import AcademicTerm
        from ..models import PromotionBatch

        try:
            from_grade = GradeLevel.objects.get(id=from_grade_level_id, school=school)
            to_grade = GradeLevel.objects.get(id=to_grade_level_id, school=school)
            academic_term = AcademicTerm.objects.get(id=academic_term_id, school=school)

            # Get or create promotion rule
            promotion_rule = None
            if promotion_rule_id:
                promotion_rule = PromotionRule.objects.get(id=promotion_rule_id, school=school)
            else:
                # Try to find an existing rule
                promotion_rule = PromotionRule.objects.filter(
                    school=school,
                    from_grade_level=from_grade,
                    to_grade_level=to_grade,
                    is_active=True
                ).first()

            # Get students to evaluate
            students = Student.objects.filter(
                school=school,
                grade_level=from_grade,
                is_active=True
            ).select_related('user')

            if not students.exists():
                raise ValueError(f"No students found in grade level {from_grade.name}")

            # Create promotion batch
            batch = PromotionBatch.objects.create(
                school=school,
                name=batch_name or f"{from_grade.name} → {to_grade.name} Promotion",
                academic_year=academic_term.academic_year,
                academic_term=academic_term,
                status='PROCESSING'
            )

            # Evaluate each student
            batch_stats = {
                'promoted': 0,
                'conditional': 0,
                'repeated': 0,
                'total': 0
            }

            promotions = []

            for student in students:
                # Get the student's current class
                current_class = student.school_class

                # Evaluate promotion
                result = PromotionService.evaluate_student_promotion(
                    student, from_grade, to_grade, academic_term, promotion_rule
                )

                # Determine final status
                status = 'PROMOTED' if result['eligible'] else 'REPEATED'

                # For conditional promotion
                if status == 'PROMOTED' and result.get('subjects_failed', 0) > 0:
                    status = 'CONDITIONAL'

                # Update batch stats
                if status == 'PROMOTED':
                    batch_stats['promoted'] += 1
                elif status == 'CONDITIONAL':
                    batch_stats['conditional'] += 1
                else:
                    batch_stats['repeated'] += 1
                batch_stats['total'] += 1

                # Find or create target class
                target_class = PromotionService._find_or_create_target_class(
                    student, to_grade, school
                )

                # Create promotion record
                promotion = StudentPromotion.objects.create(
                    school=school,
                    student=student,
                    from_grade_level=from_grade,
                    from_school_class=current_class,
                    to_grade_level=to_grade,
                    to_school_class=target_class,
                    overall_average=result['overall_average'],
                    subjects_passed=result['subjects_passed'],
                    subjects_failed=result['subjects_failed'],
                    failed_subjects=result['failed_subjects'],
                    attendance_percentage=result['attendance_percentage'],
                    status=status,
                    is_automatic=(mode == 'AUTO'),
                    notes=result.get('reason', ''),
                    promotion_batch=batch,
                )

                promotions.append(promotion)

            # Update batch stats
            batch.total_students = batch_stats['total']
            batch.promoted = batch_stats['promoted']
            batch.conditional = batch_stats['conditional']
            batch.repeated = batch_stats['repeated']
            batch.status = 'COMPLETED'
            batch.processed_by = processed_by
            batch.processed_at = timezone.now()
            batch.save()

            return {
                'success': True,
                'batch': batch,
                'promotions': promotions,
                'stats': batch_stats
            }

        except Exception as e:
            logger.error(f"Promotion batch processing failed: {str(e)}")
            if 'batch' in locals():
                batch.status = 'FAILED'
                batch.save()
            return {
                'success': False,
                'error': str(e)
            }

    @staticmethod
    def _find_or_create_target_class(student, to_grade_level, school):
        """Find or create a target class for the promoted student."""
        # Try to find an existing class
        classes = SchoolClass.objects.filter(
            school=school,
            grade_level=to_grade_level,
            is_active=True
        )

        if classes.exists():
            # Try to find a class with space
            for cls in classes:
                if cls.student_count < 40:  # Default capacity
                    return cls

            # If all full, create a new one
            new_class_name = f"{to_grade_level.name} {classes.count() + 1}"
            return SchoolClass.objects.create(
                school=school,
                name=new_class_name,
                grade_level=to_grade_level,
                uses_single_class_teacher=to_grade_level.stage in ['KG', 'PRIMARY']
            )

        # Create first class for this grade level
        return SchoolClass.objects.create(
            school=school,
            name=f"{to_grade_level.name} 1",
            grade_level=to_grade_level,
            uses_single_class_teacher=to_grade_level.stage in ['KG', 'PRIMARY']
        )

    @staticmethod
    @transaction.atomic
    def apply_promotion(promotion_id, approved_by):
        """
        Apply a promotion to a student (update their grade level and class).
        """
        try:
            promotion = StudentPromotion.objects.get(id=promotion_id)
            student = promotion.student

            # Only apply if status is PROMOTED or CONDITIONAL
            if promotion.status not in ['PROMOTED', 'CONDITIONAL']:
                return {
                    'success': False,
                    'error': f"Cannot apply promotion with status: {promotion.status}"
                }

            # Update student's grade level and class
            student.grade_level = promotion.to_grade_level
            if promotion.to_school_class:
                student.school_class = promotion.to_school_class

            student.save()

            promotion.status = 'TAKEN'  # or 'APPLIED'
            promotion.approved_by = approved_by
            promotion.approved_at = timezone.now()
            promotion.save()

            return {
                'success': True,
                'message': f"Student {student.user.get_full_name()} promoted to {promotion.to_grade_level.name}"
            }

        except StudentPromotion.DoesNotExist:
            return {
                'success': False,
                'error': "Promotion record not found"
            }
        except Exception as e:
            logger.error(f"Error applying promotion: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

    @staticmethod
    def get_promotion_statistics(school, academic_year=None):
        """
        Get promotion statistics for a school or academic year.
        """
        queryset = StudentPromotion.objects.filter(school=school)

        if academic_year:
            queryset = queryset.filter(
                promotion_batch__academic_year=academic_year
            )

        stats = {
            'total': queryset.count(),
            'promoted': queryset.filter(status='PROMOTED').count(),
            'conditional': queryset.filter(status='CONDITIONAL').count(),
            'repeated': queryset.filter(status='REPEATED').count(),
            'pending': queryset.filter(status='PENDING').count(),
            'by_grade': {},
        }

        # Breakdown by grade
        grades = queryset.values('from_grade_level__name', 'to_grade_level__name') \
            .annotate(
                total=Count('id'),
                promoted=Count('id', filter=Q(status='PROMOTED')),
                repeated=Count('id', filter=Q(status='REPEATED'))
            )

        for grade in grades:
            key = f"{grade['from_grade_level__name']} → {grade['to_grade_level__name']}"
            stats['by_grade'][key] = {
                'total': grade['total'],
                'promoted': grade['promoted'],
                'repeated': grade['repeated'],
            }

        return stats