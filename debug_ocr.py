import sys
import os
import requests

# Add project root to path
sys.path.append(os.getcwd())

from ccgp_core.ocr_service import OCRService

def run_debug(filename_or_url):
    print(f"Testing OCR Service on: {filename_or_url}")
    
    if filename_or_url.startswith("http"):
        print("Downloading image...")
        try:
            r = requests.get(filename_or_url, timeout=10)
            img_bytes = r.content
        except Exception as e:
            print(f"Download failed: {e}")
            return
    else:
        if not os.path.exists(filename_or_url):
            print("File not found.")
            return
        with open(filename_or_url, "rb") as f:
            img_bytes = f.read()

    service = OCRService.get_instance()
    
    import time
    start = time.time()
    text, confidence = service.recognize_captcha(img_bytes)
    end = time.time()
    
    print(f"--- Result ---")
    print(f"Text: {text}")
    print(f"Confidence: {confidence:.4f}")
    print(f"Time: {(end - start)*1000:.2f} ms")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_debug(sys.argv[1])
    else:
        # Look for local samples
        files = [f for f in os.listdir('.') if f.startswith('failed_captcha') and f.endswith('.jpg')]
        if files:
            run_debug(files[0])
        else:
            print("No 'failed_captcha_*.jpg' found. Provide a filename or URL.")
            # Fallback to test URL if needed, or just exit
