# doi_metadata_gui_final.py
# DOI Navigator - No Login Version (Adaptive Theme + Full Features)

import io
import difflib
import hashlib
import re
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import typing as t
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import streamlit as st

# ----- Optional but fast fuzzy -----
try:
    from rapidfuzz import fuzz, process  # type: ignore
    _USE_RAPIDFUZZ = True
except Exception:
    _USE_RAPIDFUZZ = False


# --------------------------------------------------------------------
# Built-in data sources
# --------------------------------------------------------------------
JCR_FALLBACK_URL = (
    "https://www.dropbox.com/scl/fi/z1xdk4pbpko4p2x0brgq7/AllJournalsJCR2025.xlsx"
    "?rlkey=3kxhjziorfbo2xwf4p177ukin&st=0bu01tph&dl=1"
)
SCOPUS_FALLBACK_URL = (
    "https://www.dropbox.com/scl/fi/1uv8s3207pojp4tzzt8f4/ext_list_Aug_2025.xlsx"
    "?rlkey=kyieyvc0b08vgo0asxhe0j061&st=ooszzvmx&dl=1"
)


# --------------------------------------------------------------------
# Main App
# --------------------------------------------------------------------
def run_original_app():
    """Main app with adaptive theme support"""

    # --------------------------------------------------------------------
    # Page & Styles - ADAPTIVE THEME
    # --------------------------------------------------------------------
    st.set_page_config(page_title="DOI Navigator", layout="wide", page_icon="🔍", initial_sidebar_state="expanded")

    # === Adaptive CSS and Animations ===
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700;800;900&display=swap');
    :root {
        --primary-bg: #ffffff;
        --secondary-bg: #f8f9fa;
        --card-bg: rgba(255, 255, 255, 0.95);
        --text-primary: #212529;
        --text-secondary: #6c757d;
    }
    @media (prefers-color-scheme: dark) {
        :root {
            --primary-bg: #1a1a2e;
            --secondary-bg: #16213e;
            --card-bg: rgba(15, 23, 42, 0.95);
            --text-primary: #e2e8f0;
            --text-secondary: #94a3b8;
        }
    }
    .stApp {
        background: linear-gradient(135deg, var(--primary-bg) 0%, var(--secondary-bg) 100%);
        font-family: 'Poppins', sans-serif;
        color: var(--text-primary);
    }
    .main-title {
        font-size: 56px;
        font-weight: 800;
        background: linear-gradient(135deg, #e94560 0%, #34d399 25%, #5e72e4 50%, #f59e0b 75%, #8b5cf6 100%);
        background-size: 400% 400%;
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        animation: gradientFlow 10s ease infinite;
        text-align: center;
    }
    @keyframes gradientFlow {
        0%, 100% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
    }
    </style>
    """, unsafe_allow_html=True)

    # Header
    st.markdown("""
    <div style="text-align:center;">
        <h1 class="main-title">🔍 DOI Navigator</h1>
        <p style="color: var(--text-secondary); font-size: 18px;">
        Advanced Research Paper Metadata Extraction & Journal Index Analysis
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Sidebar Config
    with st.sidebar:
        st.markdown("## ⚙️ Configuration")
        min_score = st.slider("🎯 Fuzzy Match Threshold", 60, 95, 80)
        wos_if_jcr = st.checkbox("📊 Auto-mark WoS if in JCR", value=True)
        scopus_exact = st.checkbox("🔍 Scopus exact match first", value=True)
        fast_workers = st.slider("⚡ Parallel requests", 2, 16, 12)
        st.markdown("---")
        st.markdown("### 📈 Database Stats")
        st.markdown(f"**29,270** JCR Journals Scanned")
        st.markdown(f"**47,838** Scopus Journals Scanned")

    # Helper dataclass
    @dataclass
    class MatchCfg:
        min_score: int = 80
        wos_if_missing: bool = True
        scopus_exact_first: bool = True

    cfg = MatchCfg(min_score=min_score, wos_if_missing=wos_if_jcr, scopus_exact_first=scopus_exact)

    # DOI input
    st.markdown("### 📋 Input DOIs")
    dois_text = st.text_area(
        "Enter one DOI per line",
        height=200,
        placeholder="10.1016/j.arr.2025.102847\n10.1016/j.arr.2025.102834\n10.17179/excli2014-541"
    )

    raw_lines = [d for d in dois_text.splitlines() if d.strip()]
    normalize = lambda s: re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)\s*", "", s.strip(), flags=re.I)
    dois = list(dict.fromkeys(normalize(d) for d in raw_lines))

    st.markdown(f"✅ **{len(dois)} DOIs entered**")

    fetch = st.button("🚀 Fetch Metadata", type="primary")

    # --- Utility functions ---
    def _get_session():
        s = requests.Session()
        retries = Retry(total=4, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
        s.mount("https://", HTTPAdapter(max_retries=retries))
        s.headers.update({"User-Agent": "DOI-Navigator/1.1"})
        return s

    def _download_excel(url: str) -> io.BytesIO:
        r = _get_session().get(url, timeout=60)
        r.raise_for_status()
        return io.BytesIO(r.content)

    def normalize_journal(s: str) -> str:
        return re.sub(r"[^\w\s]", "", s.lower()).replace("&", "and").strip() if isinstance(s, str) else ""

    def read_jcr(io_obj):
        xls = pd.ExcelFile(io_obj, engine="openpyxl")
        df = pd.read_excel(xls, xls.sheet_names[0])
        out = df.iloc[:, [1, 12, 16]].copy()
        out.columns = ["Journal", "Impact Factor", "Quartile"]
        out["__norm"] = out["Journal"].map(normalize_journal)
        return out

    def read_scopus_titles(io_obj):
        xls = pd.ExcelFile(io_obj, engine="openpyxl")
        df = pd.read_excel(xls, xls.sheet_names[0])
        col = [c for c in df.columns if "title" in c.lower()][0]
        out = df[[col]].copy()
        out.columns = ["Scopus Title"]
        out["__norm"] = out["Scopus Title"].map(normalize_journal)
        return out

    @st.cache_data(ttl=60*60*12)
    def load_jcr_cached(url): return read_jcr(_download_excel(url))

    @st.cache_data(ttl=60*60*12)
    def load_scopus_cached(url): return read_scopus_titles(_download_excel(url))

    def _crossref_fetch_raw(doi):
        url = f"https://api.crossref.org/works/{doi}"
        return _get_session().get(url, timeout=15).json().get("message", {})

    def _doi_content_negotiation(doi):
        url = f"https://doi.org/{doi}"
        headers = {"Accept": "application/vnd.citationstyles.csl+json"}
        return _get_session().get(url, headers=headers, timeout=15).json()

    def _extract_fields(msg):
        def first(x): return x[0] if isinstance(x, list) and x else x
        title = first(msg.get("title"))
        journal = first(msg.get("container-title"))
        authors = "; ".join([f"{a.get('given','')} {a.get('family','')}".strip()
                             for a in msg.get("author", []) if isinstance(a, dict)])
        publisher = msg.get("publisher", "")
        year = None
        for k in ["published-print", "issued", "published-online"]:
            if k in msg and isinstance(msg[k], dict):
                parts = msg[k].get("date-parts", [])
                if parts and isinstance(parts[0], list) and parts[0]:
                    year = parts[0][0]
                    break
        cites = msg.get("is-referenced-by-count")
        return {"Title": title, "Authors": authors, "Journal": journal,
                "Publisher": publisher, "Year": year, "Citations (Crossref)": cites}

    def fetch_metadata_unified(doi):
        try:
            msg = _crossref_fetch_raw(doi)
            data = _extract_fields(msg)
            if data.get("Title"): return data
        except Exception: pass
        try:
            csl = _doi_content_negotiation(doi)
            return _extract_fields(csl)
        except Exception:
            return {"error": "Metadata not available."}

    def fetch_parallel(dois, max_workers=12):
        results = []
        progress = st.progress(0.0, text="Starting...")
        with ThreadPoolExecutor(max_workers=min(max_workers, len(dois))) as ex:
            futs = {ex.submit(fetch_metadata_unified, d): d for d in dois}
            for i, fut in enumerate(as_completed(futs)):
                data = fut.result()
                doi = futs[fut]
                results.append({"DOI": doi, **data})
                progress.progress((i + 1) / len(futs), text=f"Processed {i+1}/{len(futs)}")
        progress.empty()
        return results

    def merge_enrich_fast(df, jcr, scopus, cfg):
        q = df["Journal"].fillna("").map(normalize_journal).tolist()
        imp, qrt, scp, wos = [None]*len(q), [None]*len(q), [False]*len(q), [False]*len(q)
        if not jcr.empty:
            j_choices = jcr["__norm"].tolist()
            for i, n in enumerate(q):
                match = difflib.get_close_matches(n, j_choices, n=1)
                if match:
                    row = jcr.iloc[j_choices.index(match[0])]
                    imp[i] = row["Impact Factor"]
                    qrt[i] = row["Quartile"]
                    wos[i] = True
        if not scopus.empty:
            s_choices = scopus["__norm"].tolist()
            for i, n in enumerate(q):
                match = difflib.get_close_matches(n, s_choices, n=1)
                if match:
                    scp[i] = True
        df["Impact Factor (JCR)"] = imp
        df["Quartile (JCR)"] = qrt
        df["Indexed in Scopus"] = scp
        df["Indexed in Web of Science"] = wos
        return df

    # --- Main logic ---
    if fetch:
        if not dois:
            st.error("⚠️ Please enter at least one DOI.")
        else:
            st.info("📥 Loading databases...")
            jcr_df, sc_df = load_jcr_cached(JCR_FALLBACK_URL), load_scopus_cached(SCOPUS_FALLBACK_URL)
            st.success("✅ Databases loaded!")

            st.info("📡 Fetching metadata...")
            rows = fetch_parallel(dois, fast_workers)
            df = pd.DataFrame(rows)
            df = merge_enrich_fast(df, jcr_df, sc_df, cfg)

            st.success(f"✅ Processed {len(df)} papers!")

            df.index = pd.RangeIndex(1, len(df) + 1, name="S.No.")
            st.dataframe(df, use_container_width=True)

            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as w:
                df.to_excel(w, sheet_name="DOI Metadata")
            st.download_button("📊 Download Excel", buf.getvalue(), "doi_metadata.xlsx")

    st.markdown("<hr>", unsafe_allow_html=True)
    year = datetime.now().year
    st.markdown(
        f"<p style='text-align:center;color:var(--text-secondary);'>© {year} · DOI Navigator · Developed by Dr. Kunal Bhattacharya</p>",
        unsafe_allow_html=True
    )


# --------------------------------------------------------------------
# MAIN ENTRY (no authentication)
# --------------------------------------------------------------------
if __name__ == "__main__":
    run_original_app()
