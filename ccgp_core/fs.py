import os


def sanitize_filename(filename: str, max_length: int = 100) -> str:
    unsafe_chars = ["<", ">", ':', '"', "/", "\\", "|", "?", "*"]
    safe_name = filename
    for char in unsafe_chars:
        safe_name = safe_name.replace(char, "_")
    if len(safe_name) > max_length:
        safe_name = safe_name[:max_length]
    return safe_name


def build_timestamped_dir(prefix: str, timestamp: str) -> str:
    return f"{prefix}_{timestamp}"

