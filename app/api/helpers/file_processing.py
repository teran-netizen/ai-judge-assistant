"""File validation and judge auto-detection helpers."""
import logging

logger = logging.getLogger(__name__)

# Judge detection keywords
JUDGE_KEYWORDS = [
    "вынеси решение", "вынеси отказ", "откажи в", "удовлетвори требовани",
    "назначить арест", "приостановлени", "определение о ",
    "мотивированное решение", "решение суда", "откажи истцу",
    "отказ в удовлетворении", "удовлетвори иск",
]


def detect_judge(instructions: str, file_count: int) -> bool:
    """Detect if user is likely a judge based on instructions and file count.

    Returns True if instructions match judicial patterns or file count >= 10.
    """
    instr = (instructions or "").lower()
    has_keywords = any(p in instr for p in JUDGE_KEYWORDS)
    has_sides = "истец" in instr and "ответчик" in instr
    return has_keywords or has_sides or file_count >= 10


def classify_file(ext: str) -> str:
    """Classify file extension into type category."""
    ext = ext.lower()
    if ext in ('.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif', '.bmp', '.tiff', '.tif'):
        return "image"
    elif ext == '.pdf':
        return "pdf"
    else:
        return "document"
