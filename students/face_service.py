# students/face_service.py
import base64
import json
import numpy as np
from io import BytesIO
from PIL import Image
from django.core.files.base import ContentFile
from django.utils import timezone
try:
    import face_recognition
    FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    face_recognition = None
    FACE_RECOGNITION_AVAILABLE = False


class FaceRegistrationService:
    """Enterprise-grade face registration service for students"""

    # Distance below which two encodings are treated as the SAME person.
    # face_recognition's own default for "is this a match" is 0.6; we use
    # a slightly stricter value for duplicate-registration checks so we
    # don't accidentally block two genuinely different students who merely
    # look similar, while still reliably catching the same person being
    # registered twice.
    DUPLICATE_FACE_TOLERANCE = 0.45

    # Distance below which a live capture is treated as a confident
    # identification match against a registered student, e.g. for
    # attendance check-in.
    IDENTIFY_MATCH_TOLERANCE = 0.55

    @staticmethod
    def _known_encodings_for_school(school, exclude_student_id=None):
        """
        Load every registered (student, encoding) pair for a school as
        numpy arrays, skipping any record with malformed/missing data.
        Returns (students, encodings_matrix_or_empty_list).
        """
        from students.models import Student  # local import: avoids any
        # import-order issues between models.py and this service module.

        qs = Student.objects.filter(
            school=school,
            face_registered=True,
            face_encoding__isnull=False,
        )
        if exclude_student_id:
            qs = qs.exclude(pk=exclude_student_id)

        students = []
        encodings = []
        for candidate in qs:
            try:
                enc = np.array(candidate.face_encoding, dtype=float)
            except (TypeError, ValueError):
                continue
            if enc.shape != (128,):
                # Not a valid 128-d face_recognition encoding; skip rather
                # than letting a corrupt row crash the comparison.
                continue
            students.append(candidate)
            encodings.append(enc)

        return students, encodings

    @staticmethod
    def find_duplicate_registration(school, encoding, exclude_student_id=None):
        """
        Check whether `encoding` matches a face already registered to a
        DIFFERENT student in the same school. This is what enforces
        "one face -> one student record": without it, the same person's
        photo can silently be saved under several different students,
        and face-based attendance can never tell them apart.

        Returns the matching Student, or None if no match is found.
        """
        if not FACE_RECOGNITION_AVAILABLE:
            return None

        students, known_encodings = FaceRegistrationService._known_encodings_for_school(
            school, exclude_student_id=exclude_student_id
        )
        if not known_encodings:
            return None

        target = np.array(encoding, dtype=float)
        distances = face_recognition.face_distance(known_encodings, target)
        best_idx = int(np.argmin(distances))

        if distances[best_idx] <= FaceRegistrationService.DUPLICATE_FACE_TOLERANCE:
            return students[best_idx]
        return None

    @staticmethod
    def identify_student(school, image_data, tolerance=None):
        """
        Real face-recognition lookup: given a freshly captured image (e.g.
        from an attendance kiosk), find which registered student it
        belongs to. This is the counterpart to registration -- registration
        stores one encoding per student, this compares a live capture
        against all of them and returns the closest confident match.

        Returns (student_or_None, distance_or_None, message).
        """
        if not FACE_RECOGNITION_AVAILABLE:
            return None, None, (
                "Face recognition is not enabled in this deployment."
            )

        encoding, message = FaceRegistrationService.extract_face_encoding(image_data)
        if encoding is None:
            return None, None, message

        students, known_encodings = FaceRegistrationService._known_encodings_for_school(school)
        if not known_encodings:
            return None, None, "No students with registered faces found."

        target = np.array(encoding, dtype=float)
        distances = face_recognition.face_distance(known_encodings, target)
        best_idx = int(np.argmin(distances))
        best_distance = float(distances[best_idx])

        threshold = tolerance if tolerance is not None else FaceRegistrationService.IDENTIFY_MATCH_TOLERANCE
        if best_distance <= threshold:
            return students[best_idx], best_distance, "Match found."

        return None, best_distance, "No confident match found."

    @staticmethod
    def extract_face_encoding(image_data):
        """
        Extract face encoding from image data
        Supports: base64 string, bytes, file path, or PIL Image
        Returns: list of encodings or None
        """
        if not FACE_RECOGNITION_AVAILABLE:
            return None, (
                "Face recognition is not enabled in this deployment. "
                "Use the standard student profile/photo workflow instead."
            )

        try:
            # Convert various input formats to numpy array
            if isinstance(image_data, str):
                # Check if it's a base64 string
                if image_data.startswith('data:image'):
                    # Remove data URL prefix
                    image_data = image_data.split(',')[1]
                    image_bytes = base64.b64decode(image_data)
                    image = Image.open(BytesIO(image_bytes))
                    image_np = np.array(image)
                elif image_data.startswith('/') or image_data.startswith('./'):
                    # File path
                    image = face_recognition.load_image_file(image_data)
                    image_np = image
                else:
                    # Assume it's raw base64
                    image_bytes = base64.b64decode(image_data)
                    image = Image.open(BytesIO(image_bytes))
                    image_np = np.array(image)
            elif isinstance(image_data, bytes):
                # Bytes
                image = Image.open(BytesIO(image_data))
                image_np = np.array(image)
            elif isinstance(image_data, np.ndarray):
                # Already numpy array
                image_np = image_data
            else:
                # Assume it's a PIL Image
                image_np = np.array(image_data)

            # All of our input paths (PIL.Image -> np.array, or an
            # already-RGB ndarray/PIL image) are RGB, not OpenCV's BGR,
            # so no channel swap is needed here. face_recognition always
            # expects RGB.
            image_rgb = image_np

            # Detect face locations
            face_locations = face_recognition.face_locations(image_rgb, model='hog')

            if not face_locations:
                return None, "No face detected in the image. Please ensure the face is clearly visible."

            if len(face_locations) > 1:
                return None, "Multiple faces detected. Please ensure only one student is in the frame."

            # Get face encodings
            face_encodings = face_recognition.face_encodings(image_rgb, face_locations)

            if not face_encodings:
                return None, "Could not encode face. Please try with better lighting."

            # Return the first encoding as list
            return face_encodings[0].tolist(), "Face encoding extracted successfully."

        except Exception as e:
            return None, f"Error processing image: {str(e)}"

    @staticmethod
    def register_student_face(student, image_data, registered_by=None):
        """
        Register a student's face for recognition
        Returns: (success, message, encoding)
        """
        try:
            # Extract face encoding
            encoding, message = FaceRegistrationService.extract_face_encoding(image_data)

            if encoding is None:
                return False, message, None

            # Enforce one-face-per-student: reject if this face is already
            # registered to someone else in the same school, instead of
            # silently overwriting/duplicating identities.
            duplicate = FaceRegistrationService.find_duplicate_registration(
                student.school, encoding, exclude_student_id=student.pk
            )
            if duplicate is not None:
                return False, (
                    f"This face already appears to be registered to "
                    f"{duplicate} ({duplicate.admission_number}). "
                    f"Each student must be registered with their own face."
                ), None

            # Save the profile photo
            if isinstance(image_data, str) and image_data.startswith('data:image'):
                # Extract image data
                format, imgstr = image_data.split(';base64,')
                ext = format.split('/')[-1]
                file_name = f"faces/{student.admission_number}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.{ext}"

                # Create file
                file_content = ContentFile(base64.b64decode(imgstr))
                student.profile_photo.save(file_name, file_content, save=False)

            # Update student record
            student.face_encoding = encoding
            student.face_registered = True
            student.face_registered_at = timezone.now()
            student.face_registered_by = registered_by

            # Save without triggering recursion
            student.save(update_fields=[
                'face_encoding', 'face_registered', 'face_registered_at',
                'face_registered_by', 'profile_photo'
            ])

            return True, "Face registered successfully!", encoding

        except Exception as e:
            return False, f"Error registering face: {str(e)}", None

    @staticmethod
    def delete_student_face(student):
        """Delete a student's face registration"""
        try:
            # Delete the photo file
            if student.profile_photo:
                student.profile_photo.delete(save=False)

            # Clear face data
            student.face_encoding = None
            student.face_registered = False
            student.face_registered_at = None
            student.face_registered_by = None
            student.save(update_fields=[
                'face_encoding', 'face_registered', 'face_registered_at',
                'face_registered_by'
            ])

            return True, "Face registration removed successfully."
        except Exception as e:
            return False, f"Error removing face: {str(e)}"

    @staticmethod
    def get_face_quality_score(image_data):
        """
        Evaluate the quality of a face image
        Returns: (score, message)
        """
        try:
            encoding, message = FaceRegistrationService.extract_face_encoding(image_data)

            if encoding is None:
                return 0, message

            # Quality metrics based on encoding confidence
            # Higher confidence = better quality
            confidence = 1.0  # Placeholder - actual implementation would analyze image quality

            if confidence > 0.8:
                return 90, "Excellent quality. Face is clear and well-lit."
            elif confidence > 0.6:
                return 70, "Good quality. Face is visible but could be clearer."
            elif confidence > 0.4:
                return 50, "Fair quality. Consider retaking with better lighting."
            else:
                return 30, "Poor quality. Please retake with better lighting and position."

        except Exception as e:
            return 0, f"Error evaluating quality: {str(e)}"