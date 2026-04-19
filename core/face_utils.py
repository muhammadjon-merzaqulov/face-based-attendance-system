import io
import logging
import shutil
from pathlib import Path
from typing import Optional
import numpy as np
# NOTE: DeepFace is imported lazily (inside functions) to avoid
# deepface initialization errors at Django startup time.
from PIL import Image
from django.conf import settings
from deepface import DeepFace
import uuid
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FACE_DB_ROOT      = Path(settings.MEDIA_ROOT) / 'face_db'
RECOGNITION_MODEL = 'ArcFace'      # 512-dim embeddings, ~99.4% LFW accuracy
DETECTOR_BACKEND  = 'retinaface'   # Best accuracy for varied angles/lighting
DISTANCE_METRIC   = 'cosine'

# Cosine distance threshold  (ArcFace + cosine):
#   < 0.40  → same person  (we use 0.40 for higher security)
#   DeepFace default = 0.68
MATCH_THRESHOLD = 0.40


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _person_dir(person_id: str) -> Path:
    """Return (and create) the face-image folder for a given person_id."""
    d = FACE_DB_ROOT / person_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _bytes_to_ndarray(image_bytes: bytes) -> np.ndarray:
    """Convert raw image bytes → RGB numpy array for DeepFace."""
    pil_img = Image.open(io.BytesIO(image_bytes)).convert('RGB')
    return np.array(pil_img)


def _save_face_image(person_id: str, image_bytes: bytes, index: int) -> Path:
    """Save one face image to media/face_db/<person_id>/face_<n>.jpg."""
    dest = _person_dir(person_id) / f'face_{index}.jpg'
    img  = Image.open(io.BytesIO(image_bytes)).convert('RGB')
    img.save(str(dest), 'JPEG', quality=95)
    logger.debug("Saved face image %d for person %s → %s", index, person_id, dest)
    return dest


# ---------------------------------------------------------------------------
# 1. Embedding extraction  (Phase 2 — new)
# ---------------------------------------------------------------------------

def extract_embedding(image_bytes: bytes) -> Optional[list]:
    """
    Extract a single ArcFace embedding vector from one image.

    Args:
        image_bytes: Raw JPEG/PNG bytes (from webcam capture).

    Returns:
        List of 512 floats, or None if no face detected.
    """
    try:
        img_array = _bytes_to_ndarray(image_bytes)
        embedding_objs = DeepFace.represent(
            img_path          = img_array,
            model_name        = RECOGNITION_MODEL,
            detector_backend  = DETECTOR_BACKEND,
            enforce_detection = False,   # Return empty list instead of raising
            align             = True,
        )
        if embedding_objs:
            embedding = embedding_objs[0]['embedding']   # 512-dim list
            logger.debug("Extracted embedding of length %d.", len(embedding))
            return embedding
        logger.warning("DeepFace.represent() returned empty result — no face in image.")
        return None

    except Exception as exc:
        logger.warning("Embedding extraction error: %s", exc)
        return None


def extract_face_embeddings(face_images: list) -> list:
    """
    Extract ArcFace embeddings from a list of raw image byte objects.

    Called by the Admin enrollment view with 3 captured webcam images.

    Args:
        face_images: List of bytes objects (each is a JPEG/PNG).

    Returns:
        List of valid embedding vectors (may be shorter than input if a
        particular image had no detectable face).
    """
    embeddings = []
    total = len(face_images)

    for i, img_bytes in enumerate(face_images, start=1):
        emb = extract_embedding(img_bytes)
        if emb is not None:
            embeddings.append(emb)
            logger.info("Extracted embedding %d/%d (len=%d).", i, total, len(emb))
        else:
            logger.warning("Could not extract embedding from image %d/%d.", i, total)

    logger.info(
        "extract_face_embeddings: %d/%d valid embeddings.", len(embeddings), total
    )
    return embeddings


def average_embeddings(embeddings: list) -> Optional[list]:
    """
    Average multiple ArcFace embedding vectors into one canonical representation.

    The result is L2-normalised so cosine distances remain consistent.

    Args:
        embeddings: List of embedding lists (each 512 floats).  None values ignored.

    Returns:
        Normalised average embedding as a plain Python list of floats, or None.
    """
    valid = [e for e in embeddings if e is not None]
    if not valid:
        return None

    arr = np.array(valid, dtype=np.float64)  # shape (N, 512)
    avg = np.mean(arr, axis=0)               # shape (512,)

    # L2 normalise for cosine distance consistency
    norm = np.linalg.norm(avg)
    if norm > 0:
        avg = avg / norm

    return avg.tolist()


def verify_by_encoding(
    image_bytes: bytes,
    stored_encoding: list,
    threshold: float = MATCH_THRESHOLD,
) -> Optional[dict]:
    """
    Verify a live webcam face against a stored embedding vector.

    This is the PRIMARY verification method used at attendance time.
    It is faster than verify_face() because it doesn't need to scan disk images —
    it compares a single embedding against the stored JSON vector.

    Args:
        image_bytes:     Raw JPEG/PNG from the student's webcam.
        stored_encoding: The averaged embedding stored in User.face_encodings.
        threshold:       Max cosine distance to accept (lower = stricter).

    Returns:
        {'verified': True, 'distance': float, 'confidence': float} on match,
        or None if no face / distance exceeds threshold.
    """
    current_embedding = extract_embedding(image_bytes)
    if current_embedding is None:
        logger.warning("verify_by_encoding: no face found in live image.")
        return None

    a = np.array(current_embedding,  dtype=np.float64)
    b = np.array(stored_encoding,    dtype=np.float64)

    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        logger.warning("Zero-norm embedding — skipping verification.")
        return None

    # Cosine distance  ∈ [0, 2]  (0 = identical, 1 = orthogonal, 2 = opposite)
    cosine_dist = float(1.0 - np.dot(a, b) / (norm_a * norm_b))

    logger.info(
        "verify_by_encoding: cosine_dist=%.4f (threshold=%.2f) → %s",
        cosine_dist, threshold,
        'MATCH ✅' if cosine_dist <= threshold else 'NO MATCH ❌',
    )

    if cosine_dist <= threshold:
        # Confidence: 100% at distance=0, 0% at distance=threshold
        confidence = round(max(0.0, 1.0 - (cosine_dist / threshold)), 4)
        return {
            'verified':   True,
            'distance':   round(cosine_dist, 4),
            'confidence': confidence,
        }
    return None


# ---------------------------------------------------------------------------
# 2. Enrollment helpers  (Phase 1 — unchanged, reproduced for completeness)
# ---------------------------------------------------------------------------

def create_person(display_name: str) -> str:
    """Create a local person ID and its face_db directory."""
    person_id = str(uuid.uuid4())
    _person_dir(person_id)
    logger.info("Local person created: '%s' → id=%s", display_name, person_id)
    return person_id


def add_face_to_person(person_id: str, image_bytes: bytes) -> bool:
    """Validate face presence, then save image to disk for backup."""
    faces = detect_faces(image_bytes)
    if not faces:
        raise ValueError("No face detected in provided image.")

    person_dir   = _person_dir(person_id)
    next_index   = len(list(person_dir.glob('face_*.jpg'))) + 1
    _save_face_image(person_id, image_bytes, next_index)
    logger.info("Face %d saved for person %s.", next_index, person_id)
    return True


def train_person_group(wait: bool = True, max_wait_seconds: int = 60) -> None:
    """No-op in local mode — kept for API compatibility with azure_utils."""
    logger.info("train_person_group(): local mode, no training required.")


def enroll_student(display_name: str, face_images: list) -> str:
    """
    Full enrollment pipeline (create person + save all images to disk).
    Returns person_id (stored as User.azure_person_id for disk lookups).
    """
    if not face_images:
        raise ValueError("At least one face image is required.")

    person_id = create_person(display_name)

    for idx, img_bytes in enumerate(face_images, start=1):
        try:
            add_face_to_person(person_id, img_bytes)
        except ValueError as exc:
            logger.warning("Face %d for '%s' skipped: %s", idx, display_name, exc)

    return person_id


# ---------------------------------------------------------------------------
# 3. Detection helper
# ---------------------------------------------------------------------------

def detect_faces(image_bytes: bytes) -> list:
    """
    Detect faces in an image.

    Returns:
        List of face dicts with 'facial_area' and 'confidence', or [].
    """
    try:
        img_array = _bytes_to_ndarray(image_bytes)
        faces = DeepFace.extract_faces(
            img_path          = img_array,
            detector_backend  = DETECTOR_BACKEND,
            enforce_detection = False,
        )
        valid = [f for f in faces if f.get('confidence', 0) > 0.85]
        logger.info("detect_faces: found %d face(s).", len(valid))
        return valid
    except Exception as exc:
        logger.warning("Face detection error: %s", exc)
        return []


# ---------------------------------------------------------------------------
# 4. Disk-based verification  (alternative / fallback)
# ---------------------------------------------------------------------------

def verify_face(image_bytes: bytes, person_id: str) -> Optional[dict]:
    """
    Verify a face against all stored images for a person (disk-based).
    Slower than verify_by_encoding but does not require stored embeddings.
    """
    person_dir     = _person_dir(person_id)
    stored_images  = list(person_dir.glob('face_*.jpg'))

    if not stored_images:
        logger.warning("No enrolled images for person %s.", person_id)
        return None

    img_array    = _bytes_to_ndarray(image_bytes)
    best_distance = float('inf')

    for stored_path in stored_images:
        try:
            result   = DeepFace.verify(
                img1_path        = img_array,
                img2_path        = str(stored_path),
                model_name       = RECOGNITION_MODEL,
                detector_backend = DETECTOR_BACKEND,
                distance_metric  = DISTANCE_METRIC,
                enforce_detection = False,
            )
            dist = result.get('distance', float('inf'))
            if dist < best_distance:
                best_distance = dist
        except Exception as exc:
            logger.warning("Verify error vs %s: %s", stored_path.name, exc)

    if best_distance <= MATCH_THRESHOLD:
        conf = round(1.0 - (best_distance / MATCH_THRESHOLD), 4)
        return {'person_id': person_id, 'confidence': conf, 'distance': round(best_distance, 4)}

    return None


# ---------------------------------------------------------------------------
# 5. Delete person
# ---------------------------------------------------------------------------

def delete_person(person_id: str) -> None:
    """Remove all face images for a person from the local face DB."""
    d = _person_dir(person_id)
    if d.exists():
        shutil.rmtree(str(d))
        logger.info("Deleted face DB for person %s.", person_id)
