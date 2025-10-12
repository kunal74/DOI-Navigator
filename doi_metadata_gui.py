# doi_metadata_gui.py
# Streamlit DOI Navigator – clean build with About toggle, theme toggle, and footer email
# ---------------------------------------------------------------
# Dependencies:
#   pip install streamlit requests pandas openpyxl xlsxwriter
#
# Run:
#   streamlit run doi_metadata_gui.py
# ---------------------------------------------------------------

from __future__ import annotations

import io
import json
import math
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests
import streamlit as st

# ===============================
# ---------- STYLES -------------
# ===============================

# Base CSS (dark/light via CSS vars). We keep the same look across the app.
st.set_page_config(page_title="DOI Navigator", page_icon="🔍", layout="wide")

BASE_CSS = """
<style>
:root {
  --primary-bg:#1a1a2e;
  --secondary-bg:#16213e;
  --tertiary-bg:#0f3460;
  --card-bg:rgba(15,23,42,0.95);
  --card-bg-alt:rgba(22,33,62,0.95);
  --text-primary:#e2e8f0;
  --text-secondary:#94a3b8;
  --text-muted:#64748b;
  --border-color:rgba(255,255,255,0.1);
  --border-light:rgba(255,255,255,0.05);
  --shadow-light:rgba(0,0,0,0.2);
  --shadow-medium:rgba(0,0,0,0.3);
  --shadow-heavy:rgba(0,0,0,0.4);
  --input-bg:rgba(15,23,42,0.8);
  --input-border:rgba(94,114,228,0.4);
  --sidebar-bg:rgba(15,23,42,0.95);
}
@media (prefers-color-scheme: light){
  :root {
    --primary-bg:#ffffff;
    --secondary-bg:#f8f9fa;
    --tertiary-bg:#e9ecef;
    --card-bg:rgba(255,255,255,0.95);
    --card-bg-alt:rgba(248,249,250,0.95);
    --text-primary:#212529;
    --text-secondary:#6c757d;
    --text-muted:#868e96;
    --border-color:rgba(0,0,0,0.125);
    --border-light:rgba(0,0,0,0.06);
    --shadow-light:rgba(0,0,0,0.08);
    --shadow-medium:rgba(0,0,0,0.12);
    --shadow-heavy:rgba(0,0,0,0.18);
    --input-bg:rgba(255,255,255,0.9);
    --input-border:rgba(94,114,228,0.25);
    --sidebar-bg:rgba(248,249,250,0.95);
  }
}

html,body { background: var(--primary-bg); }
.block-container { padding-top: 1.2rem; }

.hero {
  position: relative;
  background: var(--card-bg);
  border: 1px solid var(--border-light);
  border-radius: 24px;
  padding: 40px 24px;
  margin-bottom: 20px;
  backdrop-filter: blur(18px);
  box-shadow: 0 10px 40px var(--shadow-light), inset 0 1px 0 var(--border-light);
  overflow: hidden;
}

.hero h1 {
  margin: 0;
  font-weight: 900;
  font-size: 56px;
  background: linear-gradient(135deg,#e94560 0%,#34d399 25%,#5e72e4 50%,#f59e0b 75%,#8b5cf6 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  letter-spacing: -1px;
}
.hero .sub {
  color: var(--text-secondary);
  margin-top: 6px;
}

.card {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: 0 10px 40px var(--shadow-medium);
  padding: 0;
  margin-bottom: 18px;
}
.card h3 {
  margin: 0;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border-color);
}
.card .body { padding: 16px 18px; }

.sidebar {
  background: var(--sidebar-bg);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  padding: 16px 18px;
}

input[type="text"], textarea {
  width: 100%;
  background: var(--input-bg);
  border: 2px solid var(--input-border);
  border-radius: 12px;
  color: var(--text-primary);
  font-size: 15px;
  padding: 10px 12px;
}
textarea::placeholder, input::placeholder { color: var(--text-secondary); opacity: .8; }

button, .btn {
  background: linear-gradient(135deg,#5e72e4 0%,#667eea 100%);
  color: #fff;
  border: none;
  border-radius: 12px;
  padding: 6px 12px;     /* very thin buttons as requested */
  font-weight: 700;
  font-size: 13px;
  line-height: 1.1;
  box-shadow: 0 4px 15px rgba(94,114,228,.3);
}
.btn.primary {
  background: linear-gradient(135deg,#e94560 0%,#ff6b6b 100%);
}
.btn.download {
  background: linear-gradient(135deg,#34d399 0%,#10b981 100%);
}

.kpi {
  text-align:center;
  background: var(--card-bg-alt);
  border: 1px solid var(--border-light);
  border-radius: 16px;
  padding: 16px;
  margin: 0;
}
.kpi .v {
  font-size: 28px;
  font-weight: 800;
  background: linear-gradient(135deg,#5e72e4,#e94560);
  -webkit-background-clip:text;
  -webkit-text-fill-color:transparent;
}
.kpi .l { font-size: 13px; color: var(--text-secondary); margin-top: 6px; }

.table-note {
  font-size: 12px; color: var(--text-secondary);
  padding-top: 6px;
}

.progress { height: 8px; width: 100%; border-radius: 10px; background: var(--card-bg);
  border:1px solid var(--border-color); overflow: hidden; }
.progress > div { height: 100%; width: 0%; background: linear-gradient(90deg,#5e72e4,#e94560,#34d399);
  background-size: 200% 100%; animation: pg 2s ease infinite; }
@keyframes pg { 0%{background-position:0% 50%} 100%{background-position:200% 50%} }

.top-right {
  position: fixed; top: 10px; right: 14px; z-index: 9999;
  display: flex; gap: 8px; align-items: center;
}
.top-right a {
  border: 1px solid var(--border-color); padding: 8px 12px; border-radius: 999px;
  background: var(--card-bg); text-decoration: none; color: var(--text-primary); font-weight: 800;
}

.footer {
  margin-top: 14px;
  padding: 18px;
  text-align: center;
  color: var(--text-secondary);
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 16px;
}
.footer a { color: inherit; text-decoration: none; }
.footer a:hover { color: #e2e8f0; text-decoration: underline; }
</style>
"""
st.markdown(BASE_CSS, unsafe_allow_html=True)

# =====================================================
# --------- ABOUT / THEME TOGGLE (TOP RIGHT) ----------
# =====================================================
if "show_about" not in st.session_state:
    st.session_state.show_about = False
if "theme_mode" not in st.session_state:
    st.session_state.theme_mode = "auto"  # auto / dark / light

params = st.query_params
if "about" in params:
    st.session_state.show_about = not st.session_state.show_about
    st.query_params.clear()
if "theme" in params:
    cycle = {"auto": "dark", "dark": "light", "light": "auto"}
    st.session_state.theme_mode = cycle.get(st.session_state.theme_mode, "auto")
    st.query_params.clear()

# If user explicitly picked light/dark, override CSS vars
if st.session_state.theme_mode in ("light", "dark"):
    if st.session_state.theme_mode == "light":
        st.markdown(
            """
            <style>
            :root {
              --primary-bg:#ffffff; --secondary-bg:#f8f9fa; --tertiary-bg:#e9ecef;
              --card-bg:rgba(255,255,255,0.95); --card-bg-alt:rgba(248,249,250,0.95);
              --text-primary:#212529; --text-secondary:#6c757d; --text-muted:#868e96;
              --border-color:rgba(0,0,0,0.125); --border-light:rgba(0,0,0,0.06);
              --shadow-light:rgba(0,0,0,0.08); --shadow-medium:rgba(0,0,0,0.12);
              --input-bg:rgba(255,255,255,0.9); --input-border:rgba(94,114,228,0.25);
              --sidebar-bg:rgba(248,249,250,0.95);
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
            <style>
            :root {
              --primary-bg:#1a1a2e; --secondary-bg:#16213e; --tertiary-bg:#0f3460;
              --card-bg:rgba(15,23,42,0.95); --card-bg-alt:rgba(22,33,62,0.95);
              --text-primary:#e2e8f0; --text-secondary:#94a3b8; --text-muted:#64748b;
              --border-color:rgba(255,255,255,0.1); --border-light:rgba(255,255,255,0.05);
              --shadow-light:rgba(0,0,0,0.2); --shadow-medium:rgba(0,0,0,0.3);
              --input-bg:rgba(15,23,42,0.8); --input-border:rgba(94,114,228,0.4);
              --sidebar-bg:rgba(15,23,42,0.95);
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

icon = "🌞" if st.session_state.theme_mode == "dark" else "🌙"
st.markdown(
    f"""
    <div class="top-right">
      <a href="?about=1">About</a>
      <a href="?theme=1" title="Theme: {st.session_state.theme_mode}">{icon}</a>
    </div>
    """,
    unsafe_allow_html=True,
)

# ===============================
# ----------- HERO --------------
# ===============================
st.markdown(
    """
    <section class="hero">
      <h1>🔍 DOI Navigator</h1>
      <div class="sub">Advanced Research Paper Metadata Extraction & Analysis</div>
    </section>
    """,
    unsafe_allow_html=True,
)

# ===============================
# --------- SIDEBAR -------------
# ===============================
with st.sidebar:
    st.markdown('<div class="sidebar">', unsafe_allow_html=True)
    st.header("⚙️ Configuration")

    st.subheader("Matching")
    min_score = st.slider("🎯 Fuzzy Match Threshold", 60, 95, 80, help="80 = balanced accuracy")
    wos_if_jcr = st.checkbox("📊 Auto-mark WoS if found in JCR", value=True)
    scopus_exact_first = st.checkbox("🔍 Scopus exact match first", value=True)

    st.markdown("---")
    st.subheader("Performance")
    workers = st.slider("⚡ Parallel requests (hint)", 2, 16, 12)

    st.markdown("---")
    st.subheader("📥 Load Databases (optional)")
    jcr_file = st.file_uploader("Load JCR Excel (local)", type=["xlsx", "xls"])
    scopus_file = st.file_uploader("Load Scopus Excel (local)", type=["xlsx", "xls"])

    st.markdown("</div>", unsafe_allow_html=True)

# ===============================
# --------- HELPERS -------------
# ===============================

def normalize_journal(name: str) -> str:
    if not name:
        return ""
    s = str(name)
    s = s.lower()
    s = s.replace("&", "and")
    s = re.sub(r"[.,:;()\\[\\]]", " ", s)
    s = re.sub(r"\\s+", " ", s).strip()
    return s

def format_authors_crossref(auth: Optional[List[Dict]]) -> str:
    if not auth:
        return ""
    parts = []
    for a in auth:
        given = (a.get("given") or "").strip()
        family = (a.get("family") or "").strip()
        initials = " ".join(w[0].upper() + "." for w in re.split(r"[\\s-]+", given) if w)
        s = f"{family}, {initials}".strip().rstrip(",")
        if s:
            parts.append(s)
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return " & ".join(parts)
    return ", ".join(parts[:-1]) + ", & " + parts[-1]

def extract_fields_from_crossref(obj: Dict) -> Dict:
    title = (obj.get("title") or [""])[0] if isinstance(obj.get("title"), list) else obj.get("title") or ""
    journal = (obj.get("container-title") or [""])[0] if isinstance(obj.get("container-title"), list) else obj.get("container-title") or ""
    publisher = obj.get("publisher") or obj.get("publisher-name") or ""
    # year
    year = None
    for key in ("published-print", "issued", "published-online"):
        dp = obj.get(key, {}).get("date-parts")
        if isinstance(dp, list) and dp and isinstance(dp[0], list) and dp[0]:
            year = dp[0][0]
            break
    if not year:
        dt = obj.get("created", {}).get("date-time") or ""
        m = re.match(r"^(\\d{4})", str(dt))
        if m:
            year = int(m.group(1))
    cites = obj.get("is-referenced-by-count")
    return {
        "Title": title or "",
        "Authors": format_authors_crossref(obj.get("author")),
        "Journal": journal or "",
        "Publisher": publisher,
        "Year": year,
        "Citations (Crossref)": cites if cites is not None else "",
    }

def fetch_crossref(doi: str) -> Dict:
    url = f"https://api.crossref.org/works/{requests.utils.quote(doi)}"
    r = requests.get(url, headers={"Accept": "application/json"}, timeout=20)
    r.raise_for_status()
    j = r.json()
    return j.get("message", {})

def fetch_csl(doi: str) -> Dict:
    url = f"https://doi.org/{requests.utils.quote(doi)}"
    r = requests.get(url, headers={"Accept": "application/vnd.citationstyles.csl+json"}, timeout=20)
    r.raise_for_status()
    return r.json()

def parse_uploaded_jcr(file) -> pd.DataFrame:
    """Expect columns like: [.., Journal, .., IF, .., Quartile ..] (we use positions 1,12,16 as a robust default)."""
    xls = pd.ExcelFile(file, engine="openpyxl")
    df = pd.read_excel(xls, xls.sheet_names[0])
    if df.shape[1] < 3:
        return pd.DataFrame(columns=["Journal", "Impact Factor", "Quartile", "__norm"])
    journal_col = df.columns[1]
    impact_col = df.columns[12] if len(df.columns) > 12 else df.columns[-1]
    quartile_col = df.columns[16] if len(df.columns) > 16 else df.columns[-1]
    out = df[[journal_col, impact_col, quartile_col]].copy()
    out.columns = ["Journal", "Impact Factor", "Quartile"]
    out["__norm"] = out["Journal"].map(normalize_journal)
    return out

def _pick_scopus_title_col(df: pd.DataFrame) -> str:
    candidates = {c.lower().strip(): c for c in df.columns}
    likely = {
        "source title", "title", "journal", "publication title", "full title",
        "journal title", "journal name", "scopus title", "scopus source title",
    }
    for k in likely:
        if k in candidates:
            return candidates[k]
    # fallback: first object dtype
    for c in df.columns:
        if pd.api.types.is_object_dtype(df[c]):
            return c
    return df.columns[0]

def parse_uploaded_scopus(file) -> pd.DataFrame:
    xls = pd.ExcelFile(file, engine="openpyxl")
    df = pd.read_excel(xls, xls.sheet_names[0])
    title_col = _pick_scopus_title_col(df)
    out = df[[title_col]].copy()
    out.columns = ["Scopus Title"]
    out["__norm"] = out["Scopus Title"].map(normalize_journal)
    return out

def quick_score(a: str, b: str) -> int:
    """Jaccard over tokens (fast, stable)."""
    A, B = set(a.split()), set(b.split())
    if not A or not B:
        return 0
    inter = len(A & B)
    union = len(A | B)
    return int(round(100 * inter / union))

# ===============================
# ----------- LAYOUT ------------
# ===============================

left, right = st.columns([1.0, 2.2])

with right:
    st.markdown('<div class="card"><h3>🔍 Input DOIs</h3><div class="body">', unsafe_allow_html=True)
    dois_text = st.text_area(
        label="Paste one DOI per line",
        label_visibility="collapsed",
        height=180,
        placeholder="10.1016/j.arr.2025.102847\n10.1016/j.arr.2025.102834\nhttps://doi.org/10.1038/nature12373",
    )
    st.markdown("</div></div>", unsafe_allow_html=True)

with left:
    st.markdown('<div class="card"><h3>Action Buttons</h3><div class="body">', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([0.7, 0.7, 0.6])
    go = c1.button("🚀 Fetch Metadata", type="primary", use_container_width=True)
    clear = c2.button("🗑️ Clear All", use_container_width=True)
    with c3:
        lines = [ln.strip() for ln in (dois_text or "").splitlines() if ln.strip()]
        uniq = sorted(set(re.sub(r"^https?://(dx\\.)?doi\\.org/", "", ln, flags=re.I).replace("doi:", "").strip() for ln in lines))
        st.markdown(
            f'<div class="kpi"><div class="v">{len(uniq)}</div><div class="l">DOIs</div></div>',
            unsafe_allow_html=True,
        )
    st.markdown('<div class="table-note">The buttons are intentionally thin (compact height) per your spec.</div>', unsafe_allow_html=True)
    st.markdown("</div></div>", unsafe_allow_html=True)

# ABOUT card (below action area)
st.markdown("<hr>", unsafe_allow_html=True)
if st.session_state.show_about:
    st.markdown(
        """
        <section style="margin:24px auto;max-width:900px;background:var(--card-bg);
            border:1px solid var(--border-color);border-radius:16px;box-shadow:0 10px 40px var(--shadow-medium);
            padding:20px;text-align:center">
            <div style="margin-bottom:8px;font-weight:800;background:linear-gradient(135deg,#5e72e4,#e94560);
                -webkit-background-clip:text;-webkit-text-fill-color:transparent;">About</div>
            <p style="white-space:nowrap"><strong>DOI Navigator</strong> fetches paper metadata from DOIs and (optionally) enriches with JCR/Scopus you provide locally.</p>
            <ul style="display:inline-block;text-align:left;margin:12px auto">
              <li>Crossref first; DOI CSL fallback</li>
              <li>Optional: JCR impact factor &amp; quartile; Scopus index</li>
              <li>Export results to Excel</li>
            </ul>
        </section>
        """,
        unsafe_allow_html=True,
    )

# ===============================
# -------- FETCH & BUILD --------
# ===============================

def update_progress(p: float, note: str = ""):
    p = max(0.0, min(1.0, float(p)))
    prog.empty()
    with prog:
        st.markdown('<div class="progress"><div style="width:{}%"></div></div>'.format(int(p * 100)), unsafe_allow_html=True)
        if note:
            st.caption(note)

results_df: Optional[pd.DataFrame] = None
prog = st.empty()
status = st.empty()

if clear:
    st.experimental_rerun()

if go:
    if not uniq:
        st.warning("Please paste at least one DOI.")
    else:
        rows: List[Dict] = []
        # Optional databases
        JCR = pd.DataFrame()
        SCOPUS = pd.DataFrame()
        if jcr_file is not None:
            try:
                JCR = parse_uploaded_jcr(jcr_file)
                st.success(f"Loaded JCR rows: {len(JCR):,}")
            except Exception as e:
                st.warning(f"Could not parse JCR: {e}")
        if scopus_file is not None:
            try:
                SCOPUS = parse_uploaded_scopus(scopus_file)
                st.success(f"Loaded Scopus rows: {len(SCOPUS):,}")
            except Exception as e:
                st.warning(f"Could not parse Scopus: {e}")

        total = len(uniq)
        for i, doi in enumerate(uniq, 1):
            update_progress(i / (total + 2), f"Resolving {i}/{total}…")
            time.sleep(0.01)
            meta = {}
            try:
                msg = fetch_crossref(doi)
                meta = extract_fields_from_crossref(msg)
            except Exception:
                try:
                    msg = fetch_csl(doi)
                    # Map a few basic fields from CSL
                    meta = {
                        "Title": msg.get("title", ""),
                        "Authors": ", ".join(a.get("family", "") for a in msg.get("author", []) if a.get("family")),
                        "Journal": msg.get("container-title", ""),
                        "Publisher": msg.get("publisher", ""),
                        "Year": msg.get("issued", {}).get("date-parts", [[None]])[0][0] if msg.get("issued") else "",
                        "Citations (Crossref)": "",
                    }
                except Exception as e:
                    meta = {"Title": f"[ERROR] {e}", "Authors": "", "Journal": "", "Publisher": "", "Year": "", "Citations (Crossref)": ""}

            rows.append({"DOI": doi, **meta})

        df = pd.DataFrame(rows)
        # Enrichment (best-effort, local)
        update_progress(0.75, "Matching with JCR / Scopus…")

        impact = [""] * len(df)
        quart = [""] * len(df)
        wos = ["" if not wos_if_jcr else False] * len(df)
        sc_index = [False] * len(df)

        if not df.empty:
            norm = df["Journal"].map(normalize_journal)

            if not JCR.empty:
                jcr_map = JCR.to_dict("records")
                for i, target in enumerate(norm):
                    best = None
                    best_score = 0
                    for cand in jcr_map:
                        s = cand["__norm"]
                        score = quick_score(target, s)
                        if score > best_score:
                            best_score = score
                            best = cand
                    if best and best_score >= min_score:
                        impact[i] = best.get("Impact Factor", "")
                        quart[i] = best.get("Quartile", "")
                        if wos_if_jcr:
                            wos[i] = True

            if not SCOPUS.empty:
                sc_map = SCOPUS["__norm"].tolist()
                for i, target in enumerate(norm):
                    ok = False
                    if scopus_exact_first:
                        ok = target in sc_map
                    if not ok:
                        best_score = 0
                        for s in sc_map:
                            score = quick_score(target, s)
                            if score > best_score:
                                best_score = score
                            if score >= min_score:
                                ok = True
                                break
                    sc_index[i] = ok

        df["Impact Factor (JCR)"] = impact
        df["Quartile (JCR)"] = quart
        df["Indexed in Scopus"] = ["✅ Yes" if v else ("➖ N/A" if SCOPUS.empty else "❌ No") for v in sc_index]
        df["Indexed in Web of Science"] = ["✅ Yes" if v is True else ("➖ N/A" if v == "" else "❌ No") for v in wos]

        results_df = df
        update_progress(1.0, "Done")

# ===============================
# --------- RESULTS UI ----------
# ===============================

if results_df is not None:
    # Summary KPI
    st.markdown('<div class="card"><h3>📊 Analysis Summary</h3><div class="body">', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    total = len(results_df)
    q1_count = (results_df["Quartile (JCR)"] == "Q1").sum()
    wos_count = (results_df["Indexed in Web of Science"] == "✅ Yes").sum()
    sc_count = (results_df["Indexed in Scopus"] == "✅ Yes").sum()
    c1.markdown(f'<div class="kpi"><div class="v">{total}</div><div class="l">Total Papers</div></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="kpi"><div class="v">{wos_count}</div><div class="l">WoS Indexed ({(wos_count/max(1,total))*100:.1f}%)</div></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="kpi"><div class="v">{sc_count}</div><div class="l">Scopus Indexed ({(sc_count/max(1,total))*100:.1f}%)</div></div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="kpi"><div class="v">{q1_count}</div><div class="l">Q1 Papers ({(q1_count/max(1,total))*100:.1f}%)</div></div>', unsafe_allow_html=True)
    st.markdown("</div></div>", unsafe_allow_html=True)

    # Table + Download
    st.markdown('<div class="card"><h3>🔓 Results Table</h3><div class="body">', unsafe_allow_html=True)
    st.dataframe(results_df, use_container_width=True, hide_index=True)
    st.markdown('<div class="table-note">Powered by Crossref + DOI content negotiation; JCR/Scopus enrichment is local & optional.</div>', unsafe_allow_html=True)

    def to_excel_bytes(df: pd.DataFrame) -> bytes:
        with io.BytesIO() as buffer:
            with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
                df.to_excel(writer, sheet_name="DOI Metadata", index=False)
            return buffer.getvalue()

    dl = st.download_button(
        label="📊 Download as Excel",
        data=to_excel_bytes(results_df),
        file_name="doi_metadata.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=False,
    )
    st.markdown("</div></div>", unsafe_allow_html=True)

# ===============================
# ----------- FOOTER ------------
# ===============================

st.markdown(
    """
    <div class="footer">
      <strong>DOI Navigator</strong><br>
      © 2025 · Developed by Dr. Kunal Bhattacharya ·
      <a href="mailto:kunal.bhattacharya221@gmail.com">kunal.bhattacharya221@gmail.com</a>
    </div>
    """,
    unsafe_allow_html=True,
)
