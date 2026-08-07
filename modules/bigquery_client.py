"""
BigQuery Client — Real Data Only. No Demo Mode.
Auth priority: ADC → Cached Google OAuth → Service Account JSON → Manual Google Login.
Exact SQL from the Jupyter notebook.
"""
import os
import json
import pandas as pd
import streamlit as st
from datetime import datetime

try:
    from google.cloud import bigquery
    from google.api_core.exceptions import GoogleAPIError
    HAS_BQ = True
except ImportError:
    HAS_BQ = False

try:
    from google_auth_oauthlib.flow import InstalledAppFlow, Flow
    from google.oauth2.credentials import Credentials as OAuthCredentials
    from google.auth.transport.requests import Request as AuthRequest
    HAS_OAUTH = True
except ImportError:
    HAS_OAUTH = False


PROJECT_ID = "bi-team-400508"

# Cache dir helper (used by AWB fetch + OAuth)
import tempfile as _tempfile
def _get_cache_dir():
    if os.path.exists("/mount/src") or os.environ.get("STREAMLIT_SHARING_MODE") == "true":
        return _tempfile.gettempdir()
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "outputs")

# Google OAuth scopes for BigQuery
OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/bigquery",
    "https://www.googleapis.com/auth/cloud-platform",
]

# Google Cloud SDK's built-in OAuth client (public, used by gcloud CLI)
OAUTH_CLIENT_CONFIG = {
    "installed": {
        "client_id": "764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur.apps.googleusercontent.com",
        "client_secret": "d-FL95Q19q7MQmFpd7hHD0Ty",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
}

# Cache file for OAuth credentials (persists across sessions)
def _get_creds_cache_path():
    if os.path.exists("/mount/src") or os.environ.get("STREAMLIT_SHARING_MODE") == "true":
        return os.path.join(_tempfile.gettempdir(), ".clustering_app_oauth_credentials.json")
    return os.path.join(os.path.expanduser("~"), ".clustering_app_oauth_credentials.json")

CREDENTIALS_CACHE = _get_creds_cache_path()


# ════════════════════════════════════════════════════
# OAUTH HELPERS — credential persistence
# ════════════════════════════════════════════════════

def _save_oauth_credentials(creds):
    """Save OAuth credentials to disk for reuse across sessions."""
    data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else OAUTH_SCOPES,
    }
    try:
        with open(CREDENTIALS_CACHE, "w") as f:
            json.dump(data, f)
    except OSError:
        pass  # Read-only filesystem on Cloud


def _load_cached_oauth_credentials():
    """Load cached OAuth credentials if available and still valid."""
    if not HAS_OAUTH or not os.path.exists(CREDENTIALS_CACHE):
        return None
    try:
        with open(CREDENTIALS_CACHE, "r") as f:
            data = json.load(f)
        creds = OAuthCredentials(
            token=data.get("token"),
            refresh_token=data.get("refresh_token"),
            token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=data.get("client_id"),
            client_secret=data.get("client_secret"),
            scopes=data.get("scopes", OAUTH_SCOPES),
        )
        # Refresh if expired
        if creds.expired and creds.refresh_token:
            creds.refresh(AuthRequest())
            _save_oauth_credentials(creds)
        if creds.valid:
            return creds
        return None
    except Exception:
        return None


def clear_oauth_credentials():
    """Remove cached OAuth credentials (logout)."""
    if os.path.exists(CREDENTIALS_CACHE):
        os.remove(CREDENTIALS_CACHE)


# ════════════════════════════════════════════════════
# AUTH — Streamlit Secrets → ADC → Cached OAuth → Manual
# ════════════════════════════════════════════════════

def _connect_from_remote_token_store():
    """
    Fetch the newest Gmail refresh token from the encrypted token store
    (bq_token.enc on the 'token-store' branch of the cluster-payout-optimization
    repo) and connect. The laptop-side REFRESH_BQ_TOKEN script rotates that
    token, so the store always holds the latest one — no Streamlit secrets
    edits needed when company policy expires the token (~2 days).
    Requires GH_TOKEN and TOKEN_DECRYPT_KEY in Streamlit secrets (one-time).
    Returns (client, auth_mode) or (None, None).
    """
    try:
        gh_token = st.secrets.get("GH_TOKEN")
        fkey = st.secrets.get("TOKEN_DECRYPT_KEY")
    except Exception:
        return None, None
    if not (gh_token and fkey):
        return None, None
    try:
        import base64 as _b64
        import urllib.request as _rq
        req = _rq.Request(
            "https://api.github.com/repos/rk7326181-lab/cluster-payout-optimization"
            "/contents/bq_token.enc?ref=token-store",
            headers={"Authorization": f"Bearer {gh_token}",
                     "Accept": "application/vnd.github+json"},
        )
        with _rq.urlopen(req, timeout=15) as r:
            blob = _b64.b64decode(json.load(r)["content"])
        from cryptography.fernet import Fernet
        tok = json.loads(Fernet(fkey.encode()).decrypt(blob))
        creds = OAuthCredentials(
            token=None,
            refresh_token=tok["refresh_token"],
            token_uri=tok.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=tok["client_id"],
            client_secret=tok["client_secret"],
        )
        creds.refresh(AuthRequest())
        client = bigquery.Client(project=PROJECT_ID, credentials=creds)
        client.query("SELECT 1", timeout=10).result(timeout=15)
        return client, "google_oauth"
    except Exception:
        return None, None


def _connect_from_streamlit_secrets():
    """
    Try to connect using credentials stored in Streamlit secrets.
    Tries the remote token store first (always the freshest token), then
    [gcp_credentials] with service_account / authorized_user types.
    Returns (client, auth_mode) or (None, None).
    """
    client, mode = _connect_from_remote_token_store()
    if client:
        return client, mode

    try:
        raw = st.secrets.get("gcp_credentials", {})
        # Deep-convert Streamlit's AttrDict to plain dict
        creds_dict = json.loads(json.dumps(dict(raw)))
        if not creds_dict or "type" not in creds_dict:
            return None, None
    except Exception:
        return None, None

    cred_type = creds_dict.get("type")

    try:
        if cred_type == "service_account":
            from google.oauth2 import service_account as sa_module
            creds = sa_module.Credentials.from_service_account_info(
                creds_dict, scopes=OAUTH_SCOPES
            )
            client = bigquery.Client(project=PROJECT_ID, credentials=creds)
            client.query("SELECT 1").result()
            return client, "service_account"

        elif cred_type == "authorized_user":
            creds = OAuthCredentials(
                token=None,
                refresh_token=creds_dict.get("refresh_token"),
                token_uri=creds_dict.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=creds_dict.get("client_id"),
                client_secret=creds_dict.get("client_secret"),
            )
            creds.refresh(AuthRequest())
            client = bigquery.Client(project=PROJECT_ID, credentials=creds)
            client.query("SELECT 1").result()
            return client, "google_oauth"

    except Exception:
        pass

    return None, None


def auto_connect():
    """
    Try Streamlit secrets first, then ADC, then cached OAuth.
    Returns (client, auth_mode, error_msg).
    auth_mode: "adc" | "google_oauth" | "service_account" | "needs_key" | None
    """
    if not HAS_BQ:
        return None, None, "google-cloud-bigquery not installed. Run: pip install google-cloud-bigquery"

    # Option 0 — Streamlit secrets (primary method for Streamlit Cloud)
    client, mode = _connect_from_streamlit_secrets()
    if client:
        return client, mode, None

    # Option A — Application Default Credentials (gcloud auth — local dev)
    try:
        client = bigquery.Client(project=PROJECT_ID)
        client.query("SELECT 1").result()
        return client, "adc", None
    except Exception:
        pass

    # Option B — Cached Google OAuth credentials
    try:
        creds = _load_cached_oauth_credentials()
        if creds:
            client = bigquery.Client(project=PROJECT_ID, credentials=creds)
            client.query("SELECT 1").result()
            return client, "google_oauth", None
    except Exception:
        pass

    return None, "needs_key", None


def connect_with_service_account(creds_dict):
    """
    Option C — Service account JSON upload.
    Returns (client, error_msg).
    """
    if not HAS_BQ:
        return None, "google-cloud-bigquery not installed."
    try:
        client = bigquery.Client.from_service_account_info(creds_dict, project=PROJECT_ID)
        return client, None
    except Exception as e:
        return None, str(e)


def connect_with_google_oauth():
    """
    Option D — Google OAuth login. Opens browser for Google sign-in.
    Returns (client, error_msg).
    """
    if not HAS_BQ:
        return None, "google-cloud-bigquery not installed."
    if not HAS_OAUTH:
        return None, "google-auth-oauthlib not installed. Run: pip install google-auth-oauthlib"

    try:
        flow = InstalledAppFlow.from_client_config(OAUTH_CLIENT_CONFIG, OAUTH_SCOPES)
        creds = flow.run_local_server(
            port=0,
            prompt="consent",
            success_message=(
                "Authentication successful! You can close this tab and return to the Streamlit app."
            ),
        )
        _save_oauth_credentials(creds)
        client = bigquery.Client(project=PROJECT_ID, credentials=creds)
        return client, None
    except Exception as e:
        return None, str(e)


def init_bq_on_startup():
    """
    Called once on app startup. Tries ADC then cached OAuth silently.
    Sets st.session_state.bq_client and st.session_state.bq_auth_mode.
    """
    if st.session_state.get("bq_client") is not None:
        return  # Already connected

    client, mode, err = auto_connect()
    if client:
        st.session_state["bq_client"] = client
        st.session_state["bq_auth_mode"] = mode
    else:
        st.session_state["bq_auth_mode"] = "needs_key"


def handle_service_account_upload(uploaded_file):
    """Process uploaded JSON key file. Returns (success, error_msg)."""
    try:
        creds_dict = json.load(uploaded_file)
        client, err = connect_with_service_account(creds_dict)
        if err:
            return False, err
        st.session_state["bq_client"] = client
        st.session_state["bq_auth_mode"] = "service_account"
        st.session_state["bq_credentials"] = creds_dict
        return True, None
    except Exception as e:
        return False, str(e)


def handle_google_oauth_login():
    """Run Google OAuth login flow. Returns (success, error_msg)."""
    client, err = connect_with_google_oauth()
    if err:
        return False, err
    st.session_state["bq_client"] = client
    st.session_state["bq_auth_mode"] = "google_oauth"
    return True, None


# ════════════════════════════════════════════════════
# AWB QUERY — Exact copy from Jupyter notebook
# ════════════════════════════════════════════════════

def build_awb_query(cluster_df):
    """
    Build the exact AWB SQL query from the notebook.
    Pincodes auto-injected from cluster_df.
    """
    pincodes = (
        cluster_df["Pincode"]
        .astype(str)
        .str.strip()
        .str.replace(".0", "", regex=False)
        .tolist()
    )
    pincode_list = ",".join(pincodes)

    Awb = f"""
    WITH awb_data AS (

        SELECT
            sg.order_date,
            sg.rider_id,
            sg.pincode,
            sg.order_id AS fwd_del_awb_number,
            edp.delivery_latitude AS lat,
            edp.delivery_longitude AS long,
            ROW_NUMBER() OVER (
                PARTITION BY sg.rider_id
                ORDER BY edp.update_timestamp
            ) AS row_num

        FROM `data-warehousing-391512.smaug_dataengine.data_engine_orderleveldata` sg

        LEFT JOIN `data-warehousing-391512.ecommerce.ecommerce_deliveryrequest` edr
            ON edr.awb_number = sg.order_id
            AND edr.last_updated > CURRENT_DATE() - INTERVAL 60 DAY

        LEFT JOIN `data-warehousing-391512.ecommerce.ecommerce_deliveryrequestproof` edp
            ON edr.id = edp.delivery_request_id
            AND edp.update_timestamp > CURRENT_DATE() - INTERVAL 60 DAY

        WHERE sg.order_date > CURRENT_DATE() - INTERVAL 60 DAY
            AND sg.order_category = 1
            AND ecom_request_type IN (1)
            AND sg.order_status IN (1)
            AND sg.order_tag IN (0, 1, 14)
            AND edr.client_id NOT IN (
                5,18,60,61,67,68,102,354,552,557,
                715,818,862,875,11,996,1579,1575,
                1819,2063,2253
            )
            AND sg.pincode IN ({pincode_list})

        UNION ALL

        SELECT
            sg.order_date,
            sg.rider_id,
            sg.pincode,
            sg.order_id AS fwd_del_awb_number,
            epp.pickup_latitude AS lat,
            epp.pickup_longitude AS long,
            ROW_NUMBER() OVER (
                PARTITION BY sg.rider_id
                ORDER BY epp.update_timestamp
            ) AS row_num

        FROM `data-warehousing-391512.smaug_dataengine.data_engine_orderleveldata` sg

        LEFT JOIN `data-warehousing-391512.ecommerce.pickup_pickuprequestproof` epp
            ON sg.order_id = epp.pickup_request_id
            AND epp.update_timestamp > CURRENT_DATE() - INTERVAL 60 DAY

        WHERE sg.order_date > CURRENT_DATE() - INTERVAL 60 DAY
            AND sg.order_category = 1
            AND ecom_request_type IN (5)
            AND sg.order_status IN (2,3)
            AND sg.order_tag IN (0,1,14)
            AND sg.pincode IN ({pincode_list})

    ),

    Pin AS (

        WITH ranked_data AS (
            SELECT
                report_date,
                pincode,
                hub,
                payment_category,
                ROW_NUMBER() OVER (
                    PARTITION BY pincode
                    ORDER BY report_date DESC
                ) AS row_num
            FROM `data-warehousing-391512.analytics_tables.client_pincode_active_data`
            WHERE service = "regular"
        )

        SELECT
            report_date,
            pincode,
            hub,
            payment_category
        FROM ranked_data
        WHERE row_num = 1

    )

    SELECT
        order_date,
        rider_id,
        Pin.hub,
        awb_data.pincode AS pincode,
        CONCAT("P", CAST(pin.payment_category AS STRING)) AS payment_category,
        fwd_del_awb_number,

        COALESCE(
            lat,
            FIRST_VALUE(lat) OVER (
                PARTITION BY rider_id
                ORDER BY row_num
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            )
        ) AS lat,

        COALESCE(
            long,
            FIRST_VALUE(long) OVER (
                PARTITION BY rider_id
                ORDER BY row_num
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            )
        ) AS long

    FROM awb_data
    LEFT JOIN Pin
        ON awb_data.pincode = Pin.pincode
    """
    return Awb


# ════════════════════════════════════════════════════
# FETCH — Exact Jupyter notebook execution
# ════════════════════════════════════════════════════

def fetch_awb_data(client, cluster_df):
    """
    Execute AWB query exactly like Jupyter notebook cells 4 & 5.
    Returns (dataframe, error_msg). No demo fallback. Real data only.
    """
    query = build_awb_query(cluster_df)

    try:
        query_job = client.query(query)
        # Wait up to 5 minutes — do NOT cancel early
        Awn_number_with_latlong = query_job.to_dataframe(timeout=300)

        # Save CSV exactly like notebook
        output_dir = _get_cache_dir()
        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError:
            pass
        output_file = os.path.join(output_dir, "Awb_with_polygon_mapping.csv")
        try:
            Awn_number_with_latlong.to_csv(output_file, index=False)
        except OSError:
            pass  # Read-only FS on Cloud — data is still in memory
        return Awn_number_with_latlong, None

    except GoogleAPIError as e:
        return None, f"BigQuery API Error: {e}"
    except Exception as e:
        return None, f"Unexpected Error: {e}"


# ════════════════════════════════════════════════════
# WEB OAUTH — Redirect-based flow for Streamlit Cloud
# ════════════════════════════════════════════════════

def _get_web_oauth_config():
    """Get web OAuth client config from Streamlit secrets or environment.

    Looks in this order:
      1. Top-level secrets: GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET
      2. [gcp_credentials] section: client_id / client_secret
      3. [google_oauth] section: client_id / client_secret
      4. Env vars: GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET
    """
    client_id, client_secret = None, None
    try:
        client_id = st.secrets.get("GOOGLE_CLIENT_ID")
        client_secret = st.secrets.get("GOOGLE_CLIENT_SECRET")
    except Exception:
        pass
    if not (client_id and client_secret):
        for section_name in ("gcp_credentials", "google_oauth"):
            try:
                section = st.secrets.get(section_name, {})
                if section:
                    cid = section.get("client_id")
                    csec = section.get("client_secret")
                    if cid and csec:
                        client_id, client_secret = cid, csec
                        break
            except Exception:
                pass
    if not client_id:
        client_id = os.environ.get("GOOGLE_CLIENT_ID")
    if not client_secret:
        client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if client_id and client_secret:
        return {"client_id": client_id, "client_secret": client_secret}
    return None


def _get_redirect_uri():
    """Get OAuth redirect URI: secrets/env override, else the app's own external URL.

    On Streamlit Cloud the app sits behind a proxy, so the Host header is the
    INTERNAL localhost:8501 — use st.context.url (browser-visible URL,
    Streamlit >= 1.44) first, then X-Forwarded-Host, then Host."""
    uri = None
    try:
        uri = st.secrets.get("REDIRECT_URI")
    except Exception:
        pass
    if not uri:
        uri = os.environ.get("REDIRECT_URI")
    if not uri:
        try:
            from urllib.parse import urlsplit
            page_url = getattr(st.context, "url", None)
            if page_url:
                parts = urlsplit(page_url)
                if parts.scheme and parts.netloc:
                    uri = f"{parts.scheme}://{parts.netloc}"
        except Exception:
            pass
    if not uri:
        try:
            headers = st.context.headers
            host = headers.get("X-Forwarded-Host") or headers.get("x-forwarded-host")
            proto = headers.get("X-Forwarded-Proto") or headers.get("x-forwarded-proto") or "https"
            if not host:
                host = headers.get("host")
                proto = "http" if host and host.split(":")[0] in ("localhost", "127.0.0.1") else "https"
            if host and host.split(":")[0] not in ("localhost", "127.0.0.1"):
                uri = f"{proto}://{host}"
        except Exception:
            pass
    if not uri:
        uri = "http://localhost:8501"
    return uri.rstrip("/")


def _build_web_client_config(config):
    """Build Google OAuth web client config dict."""
    return {
        "web": {
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def get_google_auth_url():
    """
    Generate Google OAuth authorization URL for web-based sign-in.
    Returns (auth_url, state) or (None, error_msg).
    """
    if not HAS_OAUTH:
        return None, "google-auth-oauthlib not installed"

    config = _get_web_oauth_config()
    if not config:
        return None, "not_configured"

    # The built-in gcloud/desktop client only allows localhost redirects —
    # a web redirect back to *.streamlit.app can never work with it, so don't
    # offer the button on Cloud (use generate_bq_token.py secrets instead).
    _is_cloud = os.path.exists("/mount/src") or os.environ.get("STREAMLIT_SHARING_MODE") == "true"
    if _is_cloud and config["client_id"] == OAUTH_CLIENT_CONFIG["installed"]["client_id"]:
        return None, "not_configured"

    redirect_uri = _get_redirect_uri()
    client_config = _build_web_client_config(config)

    flow = Flow.from_client_config(
        client_config,
        scopes=OAUTH_SCOPES,
        redirect_uri=redirect_uri,
    )
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return auth_url, state


def handle_oauth_callback(code):
    """
    Exchange OAuth authorization code for credentials and create BQ client.
    Returns (client, error_msg).
    """
    if not HAS_BQ:
        return None, "google-cloud-bigquery not installed"
    if not HAS_OAUTH:
        return None, "google-auth-oauthlib not installed"

    config = _get_web_oauth_config()
    if not config:
        return None, "OAuth client not configured in secrets"

    redirect_uri = _get_redirect_uri()
    client_config = _build_web_client_config(config)

    try:
        flow = Flow.from_client_config(
            client_config,
            scopes=OAUTH_SCOPES,
            redirect_uri=redirect_uri,
        )
        flow.fetch_token(code=code)
        creds = flow.credentials

        client = bigquery.Client(project=PROJECT_ID, credentials=creds)
        # Verify the connection works
        client.query("SELECT 1").result()
        return client, None
    except Exception as e:
        return None, str(e)
