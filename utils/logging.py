import logging
import sys


def setup(level: int = logging.INFO) -> None:
    # Saat stdout diarahkan ke file, Windows memakai encoding locale (cp1252) dan
    # baris log berisi transkrip Indonesia/CJK meledak UnicodeEncodeError.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)-22s %(message)s",
        datefmt="%H:%M:%S",
        # Console Windows default cp1252; transkrip Indonesia/CJK yang di-log
        # akan meledak UnicodeEncodeError tanpa ini.
        stream=sys.stdout,
    )
    for noisy in ("httpx", "botocore", "boto3", "urllib3", "s3transfer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get(name: str) -> logging.Logger:
    return logging.getLogger(name)
