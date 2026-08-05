r"""
generate_bq_token.py
─────────────────────
Run this once locally to refresh your BigQuery access when the app says
"BigQuery: Connect Below" and Google sign-in on the deployed app fails.

Usage:
    python generate_bq_token.py

A browser window opens — pick the Google account that has BigQuery access
and click Allow. The script then:
  1. verifies BigQuery access,
  2. saves the token locally so `streamlit run app.py` connects on this machine,
  3. writes a ready-to-paste Streamlit-secrets block to
     ..\PASTE_INTO_STREAMLIT_SECRETS.toml (one folder above the repo, never
     committed) — paste its contents into share.streamlit.io → your app →
     Settings → Secrets so the deployed app auto-connects too.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from google_auth_oauthlib.flow import InstalledAppFlow
from google.cloud import bigquery

from modules.bigquery_client import (
    OAUTH_CLIENT_CONFIG, OAUTH_SCOPES, PROJECT_ID, _save_oauth_credentials,
)

SECRETS_OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "PASTE_INTO_STREAMLIT_SECRETS.toml")

print("Opening browser — sign in with the Google account that has BigQuery access...")
flow = InstalledAppFlow.from_client_config(OAUTH_CLIENT_CONFIG, OAUTH_SCOPES)
creds = flow.run_local_server(port=0, prompt="consent",
                              success_message="Auth OK — you can close this tab and return to the terminal.")

print("\nToken obtained. Verifying BigQuery access...")
connected = None
for proj in [PROJECT_ID, "data-warehousing-391512"]:
    try:
        client = bigquery.Client(project=proj, credentials=creds)
        client.query("SELECT 1").result(timeout=30)
        connected = proj
        print(f"BigQuery access confirmed (billing project: {proj})")
        break
    except Exception as e:
        print(f"  {proj}: {str(e)[:120]}")

if not connected:
    print("\nThis account has no BigQuery access on either project.")
    print("Ask your GCP admin for the 'BigQuery Job User' role, then re-run.")
    sys.exit(1)

# Local cache — `streamlit run app.py` on this machine now auto-connects.
_save_oauth_credentials(creds)
print("Saved local token cache (local runs will auto-connect).")

with open(SECRETS_OUT, "w", encoding="utf-8") as f:
    f.write(
        "# Paste everything below into share.streamlit.io -> your app -> Settings -> Secrets\n"
        "# (replace any existing [gcp_credentials] section), then save. Delete this file after.\n\n"
        "[gcp_credentials]\n"
        'type = "authorized_user"\n'
        f'refresh_token = "{creds.refresh_token}"\n'
        f'client_id = "{creds.client_id}"\n'
        f'client_secret = "{creds.client_secret}"\n'
        'token_uri = "https://oauth2.googleapis.com/token"\n'
    )
print(f"\nSecrets block written to:\n  {SECRETS_OUT}")
print("Paste its contents into the deployed app's Settings -> Secrets, save, and reboot the app.")
