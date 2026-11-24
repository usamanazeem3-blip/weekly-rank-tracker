"""Scan the repo for secrets, IDs, emails and local paths before sharing or committing.

    python tools/scan_secrets.py                  # scan the whole repo, exit 1 on findings
    python tools/scan_secrets.py --deny "Acme"    # also flag these words (case-insensitive)

Extra words to flag (old project names, client names, people) can also live one per line in
.scan-denylist at the repo root; that file is gitignored so the words themselves stay private.

Allowed on purpose: emails and URLs on reserved example domains (*.example, example.com/org/net),
obvious placeholder values ("example", "not-a-real", "your-"), and any line containing the
marker `scan:allow`.
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".tmp", "node_modules"}
# Files that are private by design and gitignored; flagged only if they exist at all
PRIVATE_FILES = {".env", "credentials.json", "token.json"}

PATTERNS = {
    "email address": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "Google OAuth client ID": re.compile(r"\d{6,}-[a-z0-9]{20,}\.apps\.googleusercontent\.com"),
    "Google OAuth client secret": re.compile(r"GOCSPX-[A-Za-z0-9_-]{10,}"),
    "Google API key": re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    "Google refresh token": re.compile(r"\b1//[0-9A-Za-z_-]{20,}"),
    "Google access token": re.compile(r"ya29\.[0-9A-Za-z_-]{20,}"),
    "Google Drive/Sheet/Doc ID": re.compile(r"(?:/d/|\bid=)([A-Za-z0-9_-]{25,})|\b(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{44}\b"),
    "Google Cloud project ID": re.compile(r"\b[a-z]+-[a-z]+-\d{6}(?:-[a-z0-9]+)?\b"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "bearer token": re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{20,}"),
    "hard-coded secret": re.compile(r"""(?i)(?:api[_-]?key|secret|token|password|passwd)\w*['"]?\s*[=:]\s*['"]?[A-Za-z0-9_\-./+=]{16,}"""),
    "webhook URL": re.compile(r"https?://[^\s'\"]*(?:hooks\.slack\.com|discord(?:app)?\.com/api/webhooks|/webhook/)[^\s'\"]+"),
    "UUID (account/instance ID?)": re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"),
    "local file path": re.compile(r"\b[A-Za-z]:\\(?:Users|Documents and Settings)\\|/(?:home|Users)/[A-Za-z0-9_.-]+/"),
    "phone number": re.compile(r"(?<![\w.])\+\d{1,3}[\s-]?\(?\d{2,4}\)?[\s-]?\d{3,4}[\s-]?\d{3,4}\b"),
}
EXAMPLE_DOMAIN = re.compile(r"(?:\.example|@example\.(?:com|org|net)|\bexample\.(?:com|org|net))\b", re.I)
ZERO_UUID = "00000000-0000-0000-0000-000000000000"
PLACEHOLDER = re.compile(r"example|not-a-real|your[_-]|placeholder|xxxx", re.I)


def load_denylist(extra):
    words = [w for w in extra if w.strip()]
    path = ROOT / ".scan-denylist"
    if path.exists():
        words += [w.strip() for w in path.read_text(encoding="utf-8").splitlines()
                  if w.strip() and not w.startswith("#")]
    return [re.compile(re.escape(w), re.I) for w in words]


def iter_files():
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT)
        if path.is_file() and not SKIP_DIRS.intersection(rel.parts) and rel.name != ".scan-denylist":
            yield path, rel


def scan(deny):
    findings = []
    for path, rel in iter_files():
        if rel.as_posix() in PRIVATE_FILES:
            findings.append((rel, 0, "private file present in repo folder", rel.name))
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary file
        for n, line in enumerate(text.splitlines(), 1):
            if "scan:allow" in line:
                continue
            for label, pattern in PATTERNS.items():
                for m in pattern.finditer(line):
                    hit = m.group(0)
                    if EXAMPLE_DOMAIN.search(hit) or hit == ZERO_UUID or (
                            label in {"hard-coded secret", "bearer token"} and PLACEHOLDER.search(hit)):
                        continue
                    findings.append((rel, n, label, hit))
            for word in deny:
                for m in word.finditer(line):
                    findings.append((rel, n, "denylisted word", m.group(0)))
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--deny", nargs="*", default=[], help="extra words to flag (case-insensitive)")
    args = parser.parse_args()
    findings = scan(load_denylist(args.deny))
    for rel, n, label, hit in findings:
        print(f"{rel.as_posix()}:{n}: {label}: {hit[:80]}")
    print(f"{len(findings)} finding(s)" if findings else "Clean: no secrets, IDs, emails or paths found.")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
