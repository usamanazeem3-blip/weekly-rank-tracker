"""Create/overwrite the Modal secret from .env + token.json.

Run after editing .env or re-running google_auth.py:
    python tools/push_modal_secret.py
"""
import subprocess
import sys

from dotenv import dotenv_values

from rank_tracker import ROOT

REQUIRED = ["TARGET_DOMAIN", "OXYLABS_API_KEY", "GOOGLE_SHEET_ID", "REPORT_EMAIL_TO"]


def main():
    env = {k: v for k, v in dotenv_values(ROOT / ".env").items() if v}
    missing = [k for k in REQUIRED if k not in env]
    if missing:
        raise SystemExit(f"Fill these in .env first: {', '.join(missing)}")
    # Same fallback chain as modal_app.py, so the deployed app finds this secret
    secret_name = env.get("MODAL_SECRET_NAME") or env.get("MODAL_APP_NAME") or "weekly-rank-tracker"
    env["GOOGLE_TOKEN_JSON"] = (ROOT / "token.json").read_text().strip()

    # Argument list (no shell) so the JSON token needs no quoting
    cmd = [sys.executable, "-m", "modal", "secret", "create", "--force", secret_name] + [f"{k}={v}" for k, v in env.items()]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
    print(f"Modal secret '{secret_name}' updated with: {', '.join(env)}")


if __name__ == "__main__":
    main()
