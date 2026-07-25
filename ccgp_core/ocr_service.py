import os
import logging
import warnings
import numpy as np
from io import BytesIO
from PIL import Image, ImageEnhance
from typing import Optional, Tuple, List, Union, Dict


# Set env vars to suppress paddle logs early
os.environ["DISABLE_MODEL_SOURCE_CHECK"] = "True"
os.environ["FLAGS_allocator_strategy"] = 'auto_growth'

class OCRService:
    _instance = None
    _initialized = False

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = OCRService()
        return cls._instance

    def __init__(self):
        if OCRService._initialized:
            return
            
        self.ocr = None
        self._init_ocr()
        OCRService._initialized = True

    def _init_ocr(self):
        try:
            # Set env vars to suppress paddle logs
            os.environ["DISABLE_MODEL_SOURCE_CHECK"] = "True"
            logging.getLogger("ppocr").setLevel(logging.ERROR)
            logging.getLogger("paddle").setLevel(logging.ERROR)
            warnings.filterwarnings("ignore")
            
            # Use TextRecognition for specialized captcha recognition (Recognition Only)
            # This avoids the overhead and complexity of the detection stage.
            from paddleocr import TextRecognition
            
            # Initialize TextRecognition (defaults to server model which is accurate)
            # If standard English model is needed: model_name="en_PP-OCRv5_mobile_rec" (or similar)
            # For now, using default server model as it proved accurate in tests.
            self.ocr = TextRecognition()
            logging.info("OCRService: TextRecognition initialized successfully.")
            
        except Exception as e:
            logging.error(f"PaddleOCR Init Failed: {e}")
            self.ocr = None

    def preprocess_image(self, image: Image.Image) -> Image.Image:
        """
        Standard preprocessing for captchas: Greyscale -> Contrast -> Resize
        """
        # Convert to RGB (standard format for PaddleOCR inputs usually)
        if image.mode != 'RGB':
             image = image.convert('RGB')
        
        # 1. Enhance Contrast
        contrast = ImageEnhance.Contrast(image)
        image = contrast.enhance(2.0)
        
        # 2. Resize (Optional but often helpful for small captchas)
        # PaddleOCR usually handles resizing internally, but slightly larger text helps.
        w, h = image.size
        # Scaling up by 2x
        image = image.resize((w * 2, h * 2), Image.Resampling.BILINEAR)
        
        return image

    def recognize_captcha(self, image_bytes: bytes) -> Tuple[Optional[str], float]:
        """
        Recognize text from captcha image bytes using Recognition-only model.
        """
        if not self.ocr:
            logging.error("OCR engine not initialized.")
            return None, 0.0
        
        try:
            image = Image.open(BytesIO(image_bytes))
            # Preprocess
            processed_img = self.preprocess_image(image)
            img_array = np.array(processed_img)
            
            # Predict
            # TextRecognition.predict returns a list of dictionaries
            result = self.ocr.predict(img_array)

            if not result:
                return None, 0.0

            # Result parsing for TextRecognition (PaddleOCR v3+)
            # Structure: [{'rec_text': 'TEXT', 'rec_score': 0.99, ...}]
            
            full_text = ""
            score = 0.0
            
            # Usually result has 1 item for 1 image input
            if isinstance(result, list) and len(result) > 0:
                item = result[0]
                if isinstance(item, dict):
                    full_text = item.get('rec_text', '')
                    score = item.get('rec_score', 0.0)
                elif hasattr(item, 'json'): # Check if it's a structural object
                     data = item.json
                     full_text = data.get('rec_text', '')
                     score = data.get('rec_score', 0.0)

            if full_text:
                return full_text.replace(" ", "").upper(), score
            
            return None, 0.0

        except Exception as e:
            logging.error(f"OCR Service Error: {e}")
            import traceback
            logging.error(traceback.format_exc())
            return None, 0.0
