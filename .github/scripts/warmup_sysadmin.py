import os
import sys
import time

import requests

RSPACE_URL = os.environ["RSPACE_URL"]

# Public, non-secret bootstrap credentials seeded by rspace-web's own "dev-test"
# Liquibase context (initial-seed-run.sql / initial-seed-devtest.sql) for the
# built-in sysadmin1 account.
SYSADMIN_USERNAME = "sysadmin1"
SYSADMIN_PASSWORD = "sysWisc23!"

# A user account that is only ever authenticated via its API key (never a real
# login) has its home folder created lazily on first write - a code path that
# throws on that first attempt (though it leaves the account usable afterward).
# A real login runs the same initialization synchronously and correctly, so a
# single login here avoids ever hitting that first-write bug during the test run.
def warm_up(timeout_seconds=300, interval_seconds=5):
    deadline = time.monotonic() + timeout_seconds
    session = requests.Session()
    last_error = None
    while time.monotonic() < deadline:
        try:
            session.get(f"{RSPACE_URL}/login", timeout=10)
            resp = session.post(
                f"{RSPACE_URL}/login",
                data={"username": SYSADMIN_USERNAME, "password": SYSADMIN_PASSWORD},
                timeout=10,
                allow_redirects=True,
            )
            if resp.status_code == 200 and "loginForm" not in resp.text:
                return
            last_error = f"HTTP {resp.status_code}, login form still present"
        except requests.exceptions.RequestException as exc:
            last_error = str(exc)
        print(f"Login not successful yet ({last_error}); retrying...", file=sys.stderr)
        time.sleep(interval_seconds)
    raise RuntimeError(f"Could not log in as {SYSADMIN_USERNAME}: {last_error}")


if __name__ == "__main__":
    try:
        warm_up()
    except Exception as exc:
        print(f"Error warming up sysadmin1 account: {exc}", file=sys.stderr)
        sys.exit(1)
