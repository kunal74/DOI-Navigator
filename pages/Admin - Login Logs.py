# pages/Admin - Login Logs.py
# Read-only viewer of users & login_history stored in doi_navigator_users.db

import os
import sqlite3
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Admin · Login Logs", page_icon="🔒", layout="wide")

# --- Simple protection: require an admin password set in Streamlit secrets ---
# In Streamlit Cloud → App → Settings → Secrets, add:  ADMIN_PASS="your-strong-password"
ADMIN_PASS = st.secrets.get("ADMIN_PASS", "")
if not ADMIN_PASS:
    st.warning("Admin password not set. Go to App → Settings → Secrets and add ADMIN_PASS.")
    st.stop()

if "admin_ok" not in st.session_state:
    st.session_state.admin_ok = False

with st.sidebar:
    st.subheader("🔐 Admin Access")
    pw = st.text_input("Admin password", type="password")
    if st.button("Unlock"):
        st.session_state.admin_ok = (pw == ADMIN_PASS)
    st.caption("Tip: Use a long, unique password.")

if not st.session_state.admin_ok:
    st.info("Enter the admin password in the sidebar and click **Unlock**.")
    st.stop()

# --- DB path (same file your app uses) ---
DB_PATH = os.path.abspath(st.secrets.get("DB_PATH", "doi_navigator_users.db"))
st.caption(f"DB: {DB_PATH}")

@st.cache_data(ttl=15)
def load_tables(path: str):
    con = sqlite3.connect(path)
    users = pd.read_sql_query(
        """
        SELECT id, username, email, full_name, organization,
               created_at, last_login, is_active
        FROM users
        ORDER BY created_at DESC
        """,
        con,
    )
    logins = pd.read_sql_query(
        """
        SELECT lh.id AS log_id,
               u.username,
               u.email,
               lh.login_time,
               lh.ip_address,
               lh.user_agent
        FROM login_history lh
        LEFT JOIN users u ON u.id = lh.user_id
        ORDER BY lh.login_time DESC
        """,
        con,
    )
    con.close()
    return users, logins

try:
    users_df, logins_df = load_tables(DB_PATH)
except Exception as e:
    st.error(f"Could not open database. {e}")
    st.stop()

# --- Quick metrics ---
c1, c2 = st.columns(2)
c1.metric("Total users", len(users_df))
c2.metric("Total logins", len(logins_df))
st.divider()

# --- Users table ---
st.subheader("👥 Users")
st.dataframe(users_df, use_container_width=True, hide_index=True)
st.download_button(
    "Download users.csv",
    users_df.to_csv(index=False).encode("utf-8-sig"),
    "users.csv",
    "text/csv",
    use_container_width=True,
)

st.divider()

# --- Login history table ---
st.subheader("🕘 Login history")
st.dataframe(logins_df, use_container_width=True, hide_index=True)
st.download_button(
    "Download login_history.csv",
    logins_df.to_csv(index=False).encode("utf-8-sig"),
    "login_history.csv",
    "text/csv",
    use_container_width=True,
)

st.caption("Note: Disk storage on Streamlit Cloud is ephemeral and may reset on redeploy/sleep.")
