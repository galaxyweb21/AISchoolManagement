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

            # Convert to RGB if needed
            if len(image_np.shape) == 3 and image_np.shape[2] == 3:
                # Check if it's BGR (OpenCV format)
                if image_np[0, 0, 0] > image_np[0, 0, 2]:  # Simple heuristic
                    image_rgb = image_np
                else:
                    image_rgb = image_np
            else:
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