"""
DuckDB Local Storage - Fast persistence for app DataFrames.
Replaces slow CSV reads with sub-second DuckDB queries.
"""
import os
import tempfile
import duckdb
import pandas as pd
import streamlit as st


def _is_streamlit_cloud():
    """Detect if running on Streamlit Cloud (read-only filesystem)."""
    return os.path.exists("/mount/src") or os.environ.get("STREAMLIT_SHARING_MODE") == "true"


def _get_db_path():
    if _is_streamlit_cloud():
        return os.path.join(tempfile.gettempdir(), "app_store.duckdb")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "outputs", "app_store.duckdb")


DB_PATH = _get_db_path()

# Tables that map to session state keys
TABLE_MAP = {
    "cluster_df":          "cluster_df",
    "final_output_df":     "final_output_df",
    "polygon_records_df":  "polygon_records_df",
    "awb_raw_df":          "awb_raw_df",
    "awb_cluster_df":      "awb_cluster_df",
    "final_result_df":     "final_result_df",
    "live_cluster_df":     "live_cluster_df",
}


def _ensure_dir():
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    except OSError:
        pass  # Read-only filesystem on Cloud - /tmp/ already exists


@st.cache_resource
def get_connection():
    """Persistent DuckDB connection (cached across reruns)."""
    _ensure_dir()
    return duckdb.connect(DB_PATH)


def save_df(name: str, df: pd.DataFrame):
    """Save DataFrame to DuckDB, replacing any existing table."""
    if df is None or df.empty:
        return
    con = get_connection()
    safe = name.replace("-", "_").replace(" ", "_")
    try:
        con.execute(f"DROP TABLE IF EXISTS {safe}")
        con.execute(f"CREATE TABLE {safe} AS SELECT * FROM df")
    except Exception as e:
        print(f"[DuckDB] save_df({safe}) error: {e}")


def load_df(name: str) -> pd.DataFrame:
    """Load DataFrame from DuckDB. Returns None if table doesn't exist."""
    con = get_connection()
    safe = name.replace("-", "_").replace(" ", "_")
    try:
        return con.execute(f"SELECT * FROM {safe}").fetchdf()
    except Exception:
        return None


def has_table(name: str) -> bool:
    con = get_connection()
    safe = name.replace("-", "_").replace(" ", "_")
    try:
        tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
        return safe in tables
    except Exception:
        return False


def drop_table(name: str):
    con = get_connection()
    safe = name.replace("-", "_").replace(" ", "_")
    try:
        con.execute(f"DROP TABLE IF EXISTS {safe}")
    except Exception:
        pass


def drop_all():
    """Drop all app tables (used by Clear Cache)."""
    con = get_connection()
    for name in TABLE_MAP:
        safe = name.replace("-", "_").replace(" ", "_")
        try:
            con.execute(f"DROP TABLE IF EXISTS {safe}")
        except Exception:
            pass


def save_session_df(key: str, df: pd.DataFrame):
    """Save to both session_state and DuckDB."""
    st.session_state[key] = df
    if key in TABLE_MAP:
        save_df(TABLE_MAP[key], df)


def load_all_to_session():
    """
    On startup, load all persisted DataFrames from DuckDB into session_state.
    Returns list of loaded table names.
    """
    loaded = []
    for ss_key, table_name in TABLE_MAP.items():
        if st.session_state.get(ss_key) is not None:
            continue  # Already in memory
        df = load_df(table_name)
        if df is not None and not df.empty:
            st.session_state[ss_key] = df
            loaded.append(ss_key)
    return loaded
