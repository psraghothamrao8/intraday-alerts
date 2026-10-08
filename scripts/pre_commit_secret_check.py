#!/usr/bin/env python3
"""
Pre-commit hook to prevent accidental commit of secrets.
Refuses commits containing ghp_, github_pat_, sk-ant-, or -----BEGIN (private keys).
"""
import re
import subprocess
import sys

SECRET_PATTERNS = [
    re.compile(r"ghp_[a-zA-Z0-9]{20,}"),
    re.compile(r"github_pat_[a-zA-Z0-9]{20,}"),
    re.compile(r"sk-ant-[a-zA-Z0-9]{20,}"),
    re.compile(r"-----BEGIN[ A-Z0-9_-]*PRIVATE KEY-----"),
]

def check_staged_content():
    # Get list of staged files
    try:
        res = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            capture_output=True,
            text=True,
            check=True
        )
    except subprocess.CalledProcessError:
        return 0

    staged_files = [f.strip() for f in res.stdout.splitlines() if f.strip()]
    violations = []

    for filepath in staged_files:
        try:
            content_res = subprocess.run(
                ["git", "show", f":{filepath}"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True
            )
            content = content_res.stdout
        except subprocess.CalledProcessError:
            continue

        for pattern in SECRET_PATTERNS:
            if pattern.search(content):
                violations.append((filepath, pattern.pattern))

    if violations:
        print("\n[ERROR] Pre-commit secret check failed! Potential secrets detected in staged files:")
        for path, pat in violations:
            print(f"  - {path}: matches pattern {pat}")
        print("\nPlease remove secrets before committing. Secrets belong only in .env or secrets/ (git-ignored).\n")
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(check_staged_content())
