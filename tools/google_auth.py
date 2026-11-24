"""One-time Google OAuth: reads credentials.json, opens a browser, writes token.json.

Grants Sheets (read/write) and Gmail (send only). Re-run whenever token.json is
revoked or the scopes in rank_tracker.SCOPES change.

    python tools/google_auth.py
"""
from google_auth_oauthlib.flow import InstalledAppFlow

from rank_tracker import ROOT, SCOPES


def main():
    flow = InstalledAppFlow.from_client_secrets_file(str(ROOT / "credentials.json"), SCOPES)
    # offline + consent guarantees a refresh token, which the Modal job relies on
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    (ROOT / "token.json").write_text(creds.to_json())
    print("Saved token.json")


if __name__ == "__main__":
    main()
