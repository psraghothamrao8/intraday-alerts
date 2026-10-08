"""
Helper script to push to git using token in .env securely.
"""
import os
import subprocess
import sys
sys.path.insert(0, os.path.abspath("."))
from engine.config import get_settings


def main():
    settings = get_settings()
    token = settings.GITHUB_TOKEN
    if not token:
        print("GITHUB_TOKEN not found in .env")
        sys.exit(1)

    remote_url = f"https://{token}@github.com/psraghothamrao8/intraday-alerts.git"
    branch = sys.argv[1] if len(sys.argv) > 1 else "main"
    cmd = ["git", "push", remote_url, branch]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        print("Successfully pushed to GitHub!")
    else:
        # Avoid printing full stderr if it contains token
        err = res.stderr.replace(token, "[REDACTED]")
        print(f"Push failed: {err}")
        sys.exit(res.returncode)


if __name__ == "__main__":
    main()
