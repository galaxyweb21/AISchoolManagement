# academics/services/__init__.py
"""
`academics.services` is a package containing service modules.

Re-export all service classes here so every existing import site keeps working:
    from .services import AITimetableService
    from academics.services.promotion_service import PromotionService
"""

from .timetable_service import AITimetableService, TimetableGenerationError

try:
    from .promotion_service import PromotionService
except ImportError:
    # promotion_service.py may not exist in every checkout of this app yet.
    PromotionService = None

try:
    from .class_teacher_sync import *
except ImportError:
    pass

try:
    from .ptc_scheduler import PTCSchedulerService
except ImportError:
    pass

__all__ = [
    "AITimetableService",
    "TimetableGenerationError",
    "PromotionService",
]