import functools
import logging
import time

log = logging.getLogger(__name__)


def retry(attempts: int = 3, backoff: float = 0.0, exc: type[Exception] = Exception):
    """Retry generik. `attempts` = total percobaan, bukan jumlah pengulangan.

    PRD menyebut "retry 2x" yang artinya attempts=3.
    """

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            for i in range(attempts):
                try:
                    return fn(*args, **kwargs)
                except exc as e:
                    if i == attempts - 1:
                        raise
                    log.warning(
                        "%s gagal (percobaan %d/%d): %s — ulang dalam %.0fs",
                        fn.__name__, i + 1, attempts, e, backoff,
                    )
                    if backoff:
                        time.sleep(backoff)

        return wrapper

    return deco
