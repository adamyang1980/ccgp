import sys
import os
import pytest
from unittest.mock import MagicMock, patch
from io import BytesIO
from PIL import Image

# Ensure project root is in path
sys.path.append(os.getcwd())

from ccgp_core.ocr_service import OCRService

@pytest.fixture
def mock_text_rec():
    # We patch paddleocr.TextRecognition. 
    # Since the import happens inside a method, this patch is effective if applied before that method runs.
    with patch('paddleocr.TextRecognition') as MockClass:
        yield MockClass

@pytest.fixture
def ocr_service(mock_text_rec):
    # Reset singleton
    OCRService._instance = None
    OCRService._initialized = False
    return OCRService.get_instance()

def test_init(ocr_service, mock_text_rec):
    # Verify initialized
    assert ocr_service.ocr is not None
    # Verify TextRecognition was called
    mock_text_rec.assert_called_once()

def test_recognize_captcha_success(ocr_service, mock_text_rec):
    # Setup mock instance
    mock_instance = mock_text_rec.return_value
    # predict returns list of dicts
    mock_instance.predict.return_value = [{'rec_text': 'ABCD', 'rec_score': 0.99}]
    
    # Create fake image
    buf = BytesIO()
    Image.new('RGB', (50, 20), color='white').save(buf, format='JPEG')
    img_bytes = buf.getvalue()
    
    code, score = ocr_service.recognize_captcha(img_bytes)
    assert code == 'ABCD'
    assert score == 0.99

def test_recognize_captcha_fail(ocr_service, mock_text_rec):
    mock_instance = mock_text_rec.return_value
    mock_instance.predict.return_value = []
    
    code, score = ocr_service.recognize_captcha(b'invalid') # PIL might fail here so code returns None
    # We should mock Image.open if we want to test OCR logic independently of PIL failure
    assert code is None
