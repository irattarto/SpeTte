"""Small helpers shared by the tests."""

import time


def wait_until(app, condition, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end and not condition():
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    return condition()
