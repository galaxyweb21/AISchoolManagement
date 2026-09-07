# attendance/face_service.py

import base64
from io import BytesIO

import numpy as np

# Face recognition is an optional feature. It is intentionally disabled in
# lightweight/cloud demo builds unless face_recognition + dlib are installed.
try:
    import face_recognition
    FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    face_recognition = None
    FACE_RECOGNITION_AVAILABLE = False
from PIL import Image

from django.core.files.base import ContentFile
from django.utils import timezone


class FaceRecognitionService:
    """
    Central service for student face registration and attendance recognition.

    Teacher access is restricted to the teacher's assigned classes.
    Administrators can recognize students across the school.
    """

    # ==========================================================
    # IMAGE DECODING
    # ==========================================================

    @staticmethod
    def decode_base64_image(image_data):
        """
        Decode a base64/data-URL image into an RGB numpy array.

        Returns:
            numpy.ndarray | None
        """

        try:
            if not image_data:
                return None

            if isinstance(image_data, bytes):
                image_bytes = image_data

            elif isinstance(image_data, str):
                # Handle:
                # data:image/jpeg;base64,/9j/...
                if image_data.startswith("data:image"):
                    try:
                        image_data = image_data.split(",", 1)[1]
                    except (IndexError, ValueError):
                        return None

                # Remove accidental whitespace
                image_data = image_data.strip()

                image_bytes = base64.b64decode(
                    image_data,
                    validate=False
                )

            else:
                return None

            image = Image.open(BytesIO(image_bytes))

            # Ensure image is completely loaded before the BytesIO
            # object disappears.
            image.load()

            # Face recognition expects RGB.
            if image.mode != "RGB":
                image = image.convert("RGB")

            return np.asarray(image, dtype=np.uint8)

        except Exception as exc:
            print(f"[FaceRecognitionService] Image decode error: {exc}")
            return None

    # ==========================================================
    # FACE ENCODING
    # ==========================================================

    @staticmethod
    def encode_face(image_data):
        """
        Extract exactly one face encoding from an image.

        Returns:
            (encoding_list, message)

        Example:
            ([0.12, ...], "Face encoding extracted successfully.")
        """

        if not FACE_RECOGNITION_AVAILABLE:
            return None, (
                "Face recognition is not enabled in this deployment. "
                "Use manual attendance or install the optional face-recognition dependencies."
            )

        try:
            image_np = FaceRecognitionService.decode_base64_image(
                image_data
            )

            if image_np is None:
                return None, "Failed to decode image."

            # --------------------------------------------------
            # HOG detection
            # --------------------------------------------------

            face_locations = face_recognition.face_locations(
                image_np,
                model="hog"
            )

            # --------------------------------------------------
            # CNN fallback
            # --------------------------------------------------

            if not face_locations:
                try:
                    face_locations = face_recognition.face_locations(
                        image_np,
                        model="cnn"
                    )
                except Exception:
                    # CNN may not be available on some installations.
                    face_locations = []

            if not face_locations:
                return (
                    None,
                    "No face detected. Please face the camera directly "
                    "and ensure there is enough lighting."
                )

            if len(face_locations) > 1:
                return (
                    None,
                    "Multiple faces detected. Please ensure only one "
                    "student is visible."
                )

            # --------------------------------------------------
            # Encoding
            # --------------------------------------------------

            face_encodings = face_recognition.face_encodings(
                image_np,
                face_locations,
                num_jitters=1,
                model="small"
            )

            if not face_encodings:
                return (
                    None,
                    "Could not encode the face. Please try again "
                    "with better lighting."
                )

            encoding = face_encodings[0]

            return (
                encoding.tolist(),
                "Face encoding extracted successfully."
            )

        except Exception as exc:
            return (
                None,
                f"Error processing image: {str(exc)}"
            )

    # ==========================================================
    # FACE COMPARISON
    # ==========================================================

    @staticmethod
    def compare_faces(
        known_face_encodings,
        face_encoding_to_check,
        tolerance=0.50
    ):
        """
        Compare one face against known student encodings.

        Returns:
            student ID string or None
        """

        if not FACE_RECOGNITION_AVAILABLE:
            return None

        if not known_face_encodings:
            return None

        if not face_encoding_to_check:
            return None

        known_encodings = []
        student_ids = []

        for student_id, encoding in known_face_encodings.items():

            if not encoding:
                continue

            try:
                encoded_array = np.asarray(
                    encoding,
                    dtype=np.float64
                )

                # Standard face_recognition encoding length.
                if encoded_array.shape != (128,):
                    continue

                known_encodings.append(encoded_array)
                student_ids.append(str(student_id))

            except Exception:
                continue

        if not known_encodings:
            return None

        try:
            face_to_check = np.asarray(
                face_encoding_to_check,
                dtype=np.float64
            )

            if face_to_check.shape != (128,):
                return None

            distances = face_recognition.face_distance(
                known_encodings,
                face_to_check
            )

            if len(distances) == 0:
                return None

            best_match_index = int(
                np.argmin(distances)
            )

            best_distance = float(
                distances[best_match_index]
            )

            if best_distance <= tolerance:
                return student_ids[best_match_index]

        except Exception as exc:
            print(
                f"[FaceRecognitionService] Comparison error: {exc}"
            )

        return None

    # ==========================================================
    # REGISTER STUDENT FACE
    # ==========================================================

    @staticmethod
    def register_student_face(
        student,
        image_data,
        registered_by=None
    ):
        """
        Register or replace a student's face.

        Returns:
            (success, message, encoding)
        """

        try:
            encoding, message = (
                FaceRecognitionService.encode_face(
                    image_data
                )
            )

            if encoding is None:
                return False, message, None

            # --------------------------------------------------
            # Save profile photo
            # --------------------------------------------------

            if image_data:

                try:
                    if isinstance(image_data, str):

                        if image_data.startswith("data:image"):

                            header, imgstr = image_data.split(
                                ";base64,",
                                1
                            )

                            extension = (
                                header.split("/", 1)[-1]
                                .lower()
                            )

                            if extension == "jpg":
                                extension = "jpeg"

                            allowed_extensions = {
                                "jpeg",
                                "png",
                                "webp"
                            }

                            if extension not in allowed_extensions:
                                extension = "jpeg"

                            file_content = ContentFile(
                                base64.b64decode(imgstr)
                            )

                            file_name = (
                                f"{student.admission_number}_"
                                f"{timezone.now().strftime('%Y%m%d_%H%M%S')}"
                                f".{extension}"
                            )

                            # Delete previous photo only after a valid
                            # new face has been successfully encoded.
                            old_photo = student.profile_photo

                            student.profile_photo.save(
                                file_name,
                                file_content,
                                save=False
                            )

                            if old_photo:
                                try:
                                    old_photo.delete(
                                        save=False
                                    )
                                except Exception:
                                    pass

                except Exception as photo_exc:
                    print(
                        "[FaceRecognitionService] "
                        f"Photo save warning: {photo_exc}"
                    )

            # --------------------------------------------------
            # Update student
            # --------------------------------------------------

            student.face_encoding = encoding
            student.face_registered = True
            student.face_registered_at = timezone.now()
            student.face_registered_by = registered_by

            student.save(
                update_fields=[
                    "face_encoding",
                    "face_registered",
                    "face_registered_at",
                    "face_registered_by",
                    "profile_photo",
                ]
            )

            return (
                True,
                "Face registered successfully!",
                encoding
            )

        except Exception as exc:
            return (
                False,
                f"Error registering face: {str(exc)}",
                None
            )

    # ==========================================================
    # TEACHER CLASS ACCESS
    # ==========================================================

    @staticmethod
    def get_teacher_class_ids(user, school_id):
        """
        Return active class IDs assigned to a teacher.

        Returns:
            set[str]
        """

        if not user or not user.is_authenticated:
            return set()

        try:
            from academics.models import TeacherClassAssignment

            assignments = (
                TeacherClassAssignment.objects
                .filter(
                    school_id=school_id,
                    teacher__user=user,
                    is_active=True,
                )
                .values_list(
                    "school_class_id",
                    flat=True
                )
            )

            return {
                str(class_id)
                for class_id in assignments
                if class_id
            }

        except Exception as exc:
            print(
                "[FaceRecognitionService] "
                f"Teacher assignment error: {exc}"
            )
            return set()

    # ==========================================================
    # STUDENT ACCESS CHECK
    # ==========================================================

    @staticmethod
    def teacher_can_access_student(
        user,
        student,
        school_id=None
    ):
        """
        Verify that a teacher can access a particular student.

        Administrators are allowed.

        Teachers are allowed only when the student's class is
        actively assigned to them.
        """

        if not user or not user.is_authenticated:
            return False

        if school_id and str(student.school_id) != str(school_id):
            return False

        # Superusers
        if user.is_superuser:
            return True

        # Administrative roles
        role = getattr(user, "role", None)

        admin_roles = {
            "SUPER_ADMIN",
            "SCHOOL_ADMIN",
            "ADMIN",
        }

        if role in admin_roles:
            return True

        # Teacher
        if role == "TEACHER":

            class_ids = (
                FaceRecognitionService
                .get_teacher_class_ids(
                    user,
                    student.school_id
                )
            )

            return (
                student.school_class_id is not None
                and str(student.school_class_id) in class_ids
            )

        return False

    # ==========================================================
    # ATTENDANCE FROM CAMERA FRAME
    # ==========================================================

    @staticmethod
    def capture_attendance_from_frame(
        image_data,
        school_id,
        date=None,
        user=None
    ):
        """
        Recognize students from a camera frame and mark attendance.

        Teachers are restricted to their assigned classes.

        Returns:
            {
                "success": True,
                "students": {
                    "student-id": {
                        "name": "...",
                        "grade": "...",
                        "admission": "...",
                        "status": "PRESENT"
                    }
                }
            }
        """

        from attendance.models import Attendance
        from students.models import Student

        if date is None:
            date = timezone.localdate()

        try:

            if not user or not user.is_authenticated:
                return {
                    "success": False,
                    "students": {},
                    "error": "Authentication required."
                }

            image_np = (
                FaceRecognitionService
                .decode_base64_image(image_data)
            )

            if image_np is None:
                return {
                    "success": False,
                    "students": {},
                    "error": "Invalid camera image."
                }

            # --------------------------------------------------
            # Determine role
            # --------------------------------------------------

            role = getattr(user, "role", None)

            admin_roles = {
                "SUPER_ADMIN",
                "SCHOOL_ADMIN",
                "ADMIN",
            }

            teacher_class_ids = set()

            if (
                not user.is_superuser
                and role not in admin_roles
            ):

                if role != "TEACHER":
                    return {
                        "success": False,
                        "students": {},
                        "error": (
                            "You do not have permission to "
                            "use facial attendance."
                        )
                    }

                teacher_class_ids = (
                    FaceRecognitionService
                    .get_teacher_class_ids(
                        user,
                        school_id
                    )
                )

                if not teacher_class_ids:
                    return {
                        "success": False,
                        "students": {},
                        "error": (
                            "You are not assigned to any class."
                        )
                    }

            # --------------------------------------------------
            # Student pool
            # --------------------------------------------------

            students_queryset = Student.objects.filter(
                school_id=school_id,
                face_registered=True,
                is_active=True,
            ).select_related(
                "user",
                "grade_level",
                "school_class",
            )

            # Critical teacher restriction.
            if (
                not user.is_superuser
                and role not in admin_roles
            ):
                students_queryset = students_queryset.filter(
                    school_class_id__in=teacher_class_ids
                )

            # --------------------------------------------------
            # Build known encodings
            # --------------------------------------------------

            known_encodings = {}

            student_map = {}

            for student in students_queryset:

                if not student.face_encoding:
                    continue

                try:

                    encoding = np.asarray(
                        student.face_encoding,
                        dtype=np.float64
                    )

                    if encoding.shape != (128,):
                        continue

                    student_id = str(student.id)

                    known_encodings[
                        student_id
                    ] = student.face_encoding

                    student_map[
                        student_id
                    ] = student

                except Exception:
                    continue

            if not known_encodings:
                return {
                    "success": True,
                    "students": {},
                    "recognized_students": 0,
                    "message": (
                        "No registered faces were found "
                        "for your accessible students."
                    )
                }

            # --------------------------------------------------
            # Detect faces
            # --------------------------------------------------

            face_locations = face_recognition.face_locations(
                image_np,
                model="hog"
            )

            if not face_locations:

                try:
                    face_locations = (
                        face_recognition.face_locations(
                            image_np,
                            model="cnn"
                        )
                    )
                except Exception:
                    face_locations = []

            if not face_locations:
                return {
                    "success": True,
                    "students": {},
                    "recognized_students": 0,
                    "message": "No faces detected."
                }

            # --------------------------------------------------
            # Encode detected faces
            # --------------------------------------------------

            face_encodings = face_recognition.face_encodings(
                image_np,
                face_locations
            )

            recognized_students = {}

            # --------------------------------------------------
            # Match faces
            # --------------------------------------------------

            for face_encoding in face_encodings:

                matched_student_id = (
                    FaceRecognitionService.compare_faces(
                        known_encodings,
                        face_encoding.tolist()
                    )
                )

                if not matched_student_id:
                    continue

                student = student_map.get(
                    str(matched_student_id)
                )

                if not student:
                    continue

                # Final security check.
                if not FaceRecognitionService.teacher_can_access_student(
                    user,
                    student,
                    school_id
                ):
                    continue

                # ------------------------------------------------
                # Mark attendance
                # ------------------------------------------------

                attendance, created = (
                    Attendance.objects.update_or_create(
                        school_id=school_id,
                        student=student,
                        date=date,
                        defaults={
                            "status": "PRESENT",
                            "marked_by": user,
                            "remarks": (
                                "Auto-detected by facial "
                                "recognition"
                            ),
                        },
                    )
                )

                full_name = (
                    student.user.get_full_name()
                    or student.user.username
                )

                recognized_students[
                    str(student.id)
                ] = {
                    "id": str(student.id),
                    "name": full_name,
                    "grade": str(
                        student.grade_level
                    ) if student.grade_level else "N/A",
                    "admission": (
                        student.admission_number
                        or "N/A"
                    ),
                    "class": (
                        student.school_class.name
                        if student.school_class
                        else "No Class"
                    ),
                    "status": attendance.status,
                }

            return {
                "success": True,
                "students": recognized_students,
                "recognized_students": len(
                    recognized_students
                ),
            }

        except Exception as exc:

            print(
                "[FaceRecognitionService] "
                f"Attendance capture error: {exc}"
            )

            return {
                "success": False,
                "students": {},
                "recognized_students": 0,
                "error": (
                    "An error occurred while processing "
                    "the camera image."
                ),
            }

    # ==========================================================
    # DELETE FACE
    # ==========================================================

    @staticmethod
    def delete_student_face(student):
        """
        Remove all face-registration information.
        """

        try:

            if student.profile_photo:
                try:
                    student.profile_photo.delete(
                        save=False
                    )
                except Exception:
                    pass

            student.face_encoding = None
            student.face_registered = False
            student.face_registered_at = None
            student.face_registered_by = None

            student.save(
                update_fields=[
                    "face_encoding",
                    "face_registered",
                    "face_registered_at",
                    "face_registered_by",
                ]
            )

            return (
                True,
                "Face registration removed successfully."
            )

        except Exception as exc:

            return (
                False,
                f"Error removing face: {str(exc)}"
            )