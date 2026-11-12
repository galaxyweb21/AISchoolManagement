# attendance/consumers.py
import json
import base64
import numpy as np
from channels.generic.websocket import AsyncWebsocketConsumer
from .face_service import FaceRecognitionService
from students.models import Student
from .models import Attendance


class AttendanceConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.school_id = self.scope['user'].school_id
        await self.accept()

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            image_data = data.get('image')

            if image_data:
                # Process image and mark attendance
                results = FaceRecognitionService.capture_attendance_from_frame(
                    image_data,
                    self.school_id
                )

                await self.send(text_data=json.dumps({
                    'type': 'attendance_update',
                    'data': results
                }))
        except Exception as e:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': str(e)
            }))