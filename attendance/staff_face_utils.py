"""Shared staff face-enrollment helpers.

A staff face is checked against all active registrations in the same school before
it is saved. Current StaffProfile fields and legacy StaffFaceProfile rows are both
read during the transition so older enrollments remain protected.
"""
import base64
import binascii
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from staff.models import StaffProfile
from school.models import School
from .models import StaffFaceProfile
from .face_service import FaceRecognitionService


class DuplicateStaffFaceError(ValueError):
    def __init__(self, duplicate_staff):
        self.duplicate_staff = duplicate_staff
        super().__init__("This face is already registered to {} ({}). Each staff member must have a unique face registration.".format(duplicate_staff.user.get_full_name() or duplicate_staff.staff_id, duplicate_staff.staff_id))


def find_duplicate_staff_face(school, encoding, exclude_staff_id=None, tolerance=0.45):
    """Return another active StaffProfile whose face matches this encoding."""
    if not school or not encoding:
        return None
    staff_qs = StaffProfile.objects.filter(school=school, is_active=True).select_related("user")
    known = {}
    staff_by_id = {}
    for staff in staff_qs:
        key = str(staff.pk)
        staff_by_id[key] = staff
        if str(staff.pk) != str(exclude_staff_id) and staff.face_registered and staff.face_encoding:
            known[key] = staff.face_encoding

    legacy = StaffFaceProfile.objects.filter(
        school=school, is_active=True, staff__is_active=True
    ).select_related("staff__user")
    for profile in legacy:
        key = str(profile.staff_id)
        staff_by_id.setdefault(key, profile.staff)
        if key != str(exclude_staff_id) and profile.encoding and key not in known:
            known[key] = profile.encoding

    matches = FaceRecognitionService.compare_faces_all(known, encoding, tolerance=tolerance)
    for identity_id, _distance in matches:
        if identity_id != str(exclude_staff_id):
            return staff_by_id.get(identity_id)
    return None


def _image_bytes(image_data):
    if not isinstance(image_data, str) or not image_data.startswith("data:image/") or "," not in image_data:
        raise ValueError("The captured image is invalid. Please capture the face again.")
    header, payload = image_data.split(",", 1)
    try:
        content = base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("The captured image could not be decoded. Please capture it again.")
    if not content or len(content) > 5 * 1024 * 1024:
        raise ValueError("The captured image is empty or too large. Please capture it again.")
    extension = "png" if "image/png" in header.lower() else "webp" if "image/webp" in header.lower() else "jpg"
    return content, extension


def save_staff_face(staff, encoding, image_data, registered_by, use_as_profile_picture=False):
    """Save one face to current and legacy-compatible stores and optional profile photo."""
    content, extension = _image_bytes(image_data)
    timestamp = timezone.now()
    filename = "{}_{}.{}".format(staff.staff_id, timestamp.strftime("%Y%m%d_%H%M%S_%f"), extension)

    with transaction.atomic():
        # Serialize enrollments for a school on databases that support row locks,
        # then repeat the duplicate check inside the write transaction to close
        # the gap between the view's pre-check and the actual save.
        School.objects.select_for_update().get(pk=staff.school_id)
        duplicate = find_duplicate_staff_face(staff.school, encoding, exclude_staff_id=staff.pk, tolerance=0.45)
        if duplicate:
            raise DuplicateStaffFaceError(duplicate)
        staff.face_encoding = encoding
        staff.face_registered = True
        staff.face_registered_at = timestamp
        staff.face_registered_by = registered_by
        staff.face_photo.save(filename, ContentFile(content), save=False)
        if use_as_profile_picture:
            staff.profile_picture.save("{}_profile_{}.{}".format(staff.staff_id, timestamp.strftime("%Y%m%d_%H%M%S_%f"), extension), ContentFile(content), save=False)
        staff.save(update_fields=["face_encoding", "face_registered", "face_registered_at", "face_registered_by", "face_photo", "profile_picture"] if use_as_profile_picture else ["face_encoding", "face_registered", "face_registered_at", "face_registered_by", "face_photo"])

        profile, _created = StaffFaceProfile.objects.get_or_create(
            staff=staff,
            defaults={"school": staff.school},
        )
        profile.school = staff.school
        profile.encoding = encoding
        profile.registered_at = timestamp
        profile.registered_by = registered_by
        profile.is_active = True
        profile.photo.save(filename, ContentFile(content), save=False)
        profile.save()
    return staff
