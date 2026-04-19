import base64
from unittest.mock import patch

from django.test import TestCase

from core import face_utils

class CoreFaceUtilsTests(TestCase):
    def setUp(self):
        # A dummy 1x1 image in base64 to mimic image bytes
        self.dummy_image_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
        self.dummy_image_bytes = base64.b64decode(self.dummy_image_b64)

    @patch('core.face_utils.DeepFace.represent')
    def test_extract_embedding_success(self, mock_represent):
        # Mock what DeepFace returns: a list of dicts with 'embedding'
        mock_represent.return_value = [{'embedding': [0.1, 0.2, 0.3, 0.4]}]

        result = face_utils.extract_embedding(self.dummy_image_bytes)
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 4)

    @patch('core.face_utils.DeepFace.represent')
    def test_extract_embedding_failure(self, mock_represent):
        # Mock empty return (no face found)
        mock_represent.return_value = []

        result = face_utils.extract_embedding(self.dummy_image_bytes)
        self.assertIsNone(result)

    def test_average_embeddings(self):
        # Vector 1 and Vector 2
        embeds = [
            [1.0, 0.0],
            [0.0, 1.0]
        ]
        # Average is [0.5, 0.5] => L2 norm is sqrt(0.5^2 + 0.5^2) = sqrt(0.5) ~ 0.7071
        # Normalised: [0.5/0.7071, 0.5/0.7071] ~ [0.7071, 0.7071]
        avg = face_utils.average_embeddings(embeds)
        self.assertIsNotNone(avg)
        self.assertAlmostEqual(avg[0], 0.70710678, places=5)
        self.assertAlmostEqual(avg[1], 0.70710678, places=5)

    @patch('core.face_utils.extract_embedding')
    def test_verify_by_encoding_match(self, mock_extract):
        # Ensure cosine distance is small
        # Stored vector:
        stored = [1.0, 0.0]
        # Live vector (same vector, perfectly matching):
        mock_extract.return_value = [1.0, 0.0]

        res = face_utils.verify_by_encoding(self.dummy_image_bytes, stored, threshold=0.40)
        self.assertIsNotNone(res)
        self.assertTrue(res['verified'])
        self.assertAlmostEqual(res['distance'], 0.0)

    @patch('core.face_utils.extract_embedding')
    def test_verify_by_encoding_no_match(self, mock_extract):
        # Orthogonal vector (distance = 1.0)
        stored = [1.0, 0.0]
        mock_extract.return_value = [0.0, 1.0]

        res = face_utils.verify_by_encoding(self.dummy_image_bytes, stored, threshold=0.40)
        self.assertIsNone(res)  # Exceeds threshold 0.40

    @patch('core.face_utils.extract_embedding')
    def test_verify_by_encoding_no_face_detected(self, mock_extract):
        # Missing face from extraction returns None
        mock_extract.return_value = None
        
        stored = [1.0, 0.0]
        res = face_utils.verify_by_encoding(self.dummy_image_bytes, stored)
        self.assertIsNone(res)
