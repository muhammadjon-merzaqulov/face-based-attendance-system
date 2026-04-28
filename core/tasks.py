import time
import base64
import logging
from celery import shared_task
from django.utils import timezone
from accounts.models import User, UserRole
from core import face_utils
from core.models import ActivityLog, AttendanceRecord, AttendanceSession

logger = logging.getLogger(__name__)

@shared_task
def process_student_enrollment_task(first_name, last_name, username, email, password, images_b64, admin_user_id, client_ip=None):
    """
    Background task to enroll a new student with face recognition.
    """
    start_time = time.time()  # Taymerni boshlash
    
    try:
        admin_user = User.objects.get(pk=admin_user_id) if admin_user_id else None
        
        face_image_bytes = []
        for b64_str in images_b64:
            try:
                if ',' in b64_str:
                    b64_str = b64_str.split(',', 1)[1]
                face_image_bytes.append(base64.b64decode(b64_str))
            except Exception:
                continue

        if not face_image_bytes:
            execution_time = time.time() - start_time
            logger.warning(f"[COMPUTATION METRIC] Enrollment aborted after {execution_time:.4f}s: Could not decode images.")
            return {'success': False, 'error': 'Could not decode the uploaded images.'}

        # Extract face embeddings
        try:
            embeddings = face_utils.extract_face_embeddings(face_image_bytes)
        except Exception as exc:
            execution_time = time.time() - start_time
            logger.error(f"[COMPUTATION METRIC] Enrollment failed after {execution_time:.4f}s: extract_face_embeddings error: {exc}", exc_info=True)
            return {'success': False, 'error': 'Face processing error. Please try again.'}

        if not embeddings:
            execution_time = time.time() - start_time
            logger.warning(f"[COMPUTATION METRIC] Enrollment aborted after {execution_time:.4f}s: No valid face detected.")
            return {
                'success': False,
                'error': 'No valid face detected in the captured photos. Please ensure good lighting and look directly at the camera.'
            }

        avg_embedding = face_utils.average_embeddings(embeddings)

        person_id = None
        try:
            person_id = face_utils.enroll_student(f"{first_name} {last_name}", face_image_bytes)
        except Exception as exc:
            logger.warning("Disk enrollment partially failed (non-critical): %s", exc)

        # Create user
        student = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            role=UserRole.STUDENT,
        )
        student.face_encodings = avg_embedding
        student.azure_person_id = person_id
        student.save(update_fields=['face_encodings', 'azure_person_id'])

        if admin_user:
            ActivityLog.objects.create(
                actor=admin_user,
                action=f"Enrolled student: {student.get_full_name()} (@{student.username}) with {len(embeddings)} face image(s).",
                ip_address=client_ip
            )

        execution_time = time.time() - start_time  # Taymerni to'xtatish
        logger.info(f"[COMPUTATION METRIC] process_student_enrollment_task completed successfully in {execution_time:.4f} seconds.")

        return {'success': True, 'message': f'Student {student.get_full_name()} enrolled successfully!', 'student_id': student.pk}

    except Exception as exc:
        execution_time = time.time() - start_time
        logger.error(f"[COMPUTATION METRIC] process_student_enrollment_task failed after {execution_time:.4f}s: {exc}", exc_info=True)
        return {'success': False, 'error': str(exc)}


@shared_task
def verify_student_face_task(session_id, student_id, image_b64, client_ip=None):
    """
    Background task to verify student face and update attendance.
    """
    start_time = time.time()  # Taymerni boshlash
    
    try:
        session = AttendanceSession.objects.get(pk=session_id)
        student = User.objects.get(pk=student_id)
        
        try:
            if ',' in image_b64:
                image_b64 = image_b64.split(',', 1)[1]
            image_bytes = base64.b64decode(image_b64)
        except Exception:
            return {'success': False, 'error': 'Corrupted image data.'}

        # Sun'iy intellekt orqali solishtirish qismi
        result = face_utils.verify_by_encoding(image_bytes, student.face_encodings)
        
        execution_time = time.time() - start_time  # Asosiy AI hisoblash uchun ketgan vaqt
        
        if result and result.get('verified'):
            record = AttendanceRecord.objects.get(session=session, student=student)
            record.status = AttendanceRecord.Status.PRESENT
            record.timestamp = timezone.now()
            record.save(update_fields=['status', 'timestamp'])
            
            ActivityLog.objects.create(
                actor=student,
                action=f"Marked attendance (Face ID) for {session.subject.name}.",
                ip_address=client_ip
            )
            
            logger.info(f"[COMPUTATION METRIC] verify_student_face_task took {execution_time:.4f} seconds (Match SUCCESS).")
            return {'success': True, 'message': 'Face verified successfully! You are marked present.'}
        else:
            logger.info(f"[COMPUTATION METRIC] verify_student_face_task took {execution_time:.4f} seconds (Match FAILED).")
            return {'success': False, 'error': 'Face did not match. Ensure good lighting and look directly at the camera.'}

    except Exception as exc:
        execution_time = time.time() - start_time
        logger.error(f"[COMPUTATION METRIC] verify_student_face_task crashed after {execution_time:.4f}s: {exc}", exc_info=True)
        return {'success': False, 'error': 'Face recognition engine error. Try again.'}
