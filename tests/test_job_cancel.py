import sys
import threading
import time

import pytest

from utils.ffmpeg_helpers import Deadline, JobCancelled, run


def test_cancel_terminates_active_subprocess():
    cancelled = threading.Event()
    threading.Timer(0.2, cancelled.set).start()
    start = time.monotonic()

    with pytest.raises(JobCancelled):
        run(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            Deadline(60, check_cancel=cancelled.is_set),
        )

    assert time.monotonic() - start < 5
