import os
from typing import Optional


class FileCache:
    def __init__(self, pages_dir: str, attachments_dir: Optional[str] = None) -> None:
        self.pages_dir = pages_dir
        self.attachments_dir = attachments_dir

    def ensure_dirs(self) -> None:
        os.makedirs(self.pages_dir, exist_ok=True)
        if self.attachments_dir:
            os.makedirs(self.attachments_dir, exist_ok=True)

    def page_path(self, page_id: str, filename: str) -> str:
        return os.path.join(self.pages_dir, str(page_id), filename)

    def is_page_cached(self, page_id: str, filename: str) -> bool:
        return os.path.exists(self.page_path(page_id, filename))

    def get_page_text(self, page_id: str, filename: str) -> Optional[str]:
        path = self.page_path(page_id, filename)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None

    def save_page_text(self, page_id: str, filename: str, content: str) -> str:
        path = self.page_path(page_id, filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def attachment_path(self, page_id: str, filename: str) -> str:
        if not self.attachments_dir:
            raise RuntimeError("attachments_dir is not configured")
        return os.path.join(self.attachments_dir, str(page_id), filename)

    def is_attachment_cached(self, page_id: str, filename: str) -> bool:
        if not self.attachments_dir:
            return False
        return os.path.exists(self.attachment_path(page_id, filename))

    def get_attachment_bytes(self, page_id: str, filename: str) -> Optional[bytes]:
        if not self.attachments_dir:
            return None
        path = self.attachment_path(page_id, filename)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as f:
                return f.read()
        except Exception:
            return None

    def get_attachment_path_if_exists(self, page_id: str, filename: str) -> Optional[str]:
        if not self.attachments_dir:
            return None
        path = self.attachment_path(page_id, filename)
        return path if os.path.exists(path) else None

    def save_attachment_bytes(self, page_id: str, filename: str, content: bytes) -> str:
        if not self.attachments_dir:
            raise RuntimeError("attachments_dir is not configured")
        path = self.attachment_path(page_id, filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        return path

