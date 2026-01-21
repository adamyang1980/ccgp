# Verification Report

## Verification Summary
- DummyResponse.raise_for_status in tests/test_jiangsu_spider.py raises a RuntimeError when status_code >= 400.
- test_extract_attachment_urls in tests/test_zhejiang_spider.py validates that only document-type attachments are kept, image/txt are excluded, and duplicates are filtered.
- All tests pass.

## Checks Performed
1) tests/test_jiangsu_spider.py
   - Confirmed DummyResponse.raise_for_status guards HTTP errors by raising on status_code >= 400.
2) tests/test_zhejiang_spider.py
   - Confirmed test_extract_attachment_urls expects document extensions (pdf, doc, docx, xls, xlsx, zip, rar), excludes images/txt, and de-duplicates.

## Test Results
- Command: pytest
- Result: 27 passed in 0.41s
