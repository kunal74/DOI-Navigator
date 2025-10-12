# downloadable.py — DOI Navigator (with top-right About + Theme toggle)
# Run: streamlit run downloadable.py

from __future__ import annotations
import io, re, difflib, time
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Dict, Optional

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import streamlit as st

st.set_page_config(page_title="DOI Navigator", layout="wide", page_icon="🔍", initial_sidebar_state="expanded")

# ------------------ Top-right About + Theme (no global design changes) ------------------
if "show_about" not in st.session_state:
    st.session_state.show_about = False
if "theme_mode" not in st.session_state:
    st.session_state.theme_mode = "auto"   # auto -> dark -> light -> auto

params = st.query_params
if "about" in params:
    st.session_state.show_about = not st.session_state.show_about
    st.query_params.clear()
if "theme" in params:
    _cycle = {"auto":"dark","dark":"light","light":"auto"}
    st.session_state.theme_mode = _cycle.get(st.session_state.theme_mode,"auto")
    st.query_params.clear()

_icon = "🌞" if st.session_state.theme_mode == "dark" else "🌙"
st.markdown(
    f"""
    <div style="position:fixed;top:10px;right:14px;z-index:9999;display:flex;gap:8px;align-items:center">
      <a href="?about=1" style="padding:8px 12px;border-radius:999px;text-decoration:none;font-weight:700;border:1px solid rgba(127,127,127,.25)">About</a>
      <a href="?theme=1" title="Theme: {st.session_state.theme_mode}" style="padding:8px 12px;border-radius:999px;text-decoration:none;font-weight:700;border:1px solid rgba(127,127,127,.25)">{_icon}</a>
    </div>
    """, unsafe_allow_html=True
)

# ------------------ Hero ------------------
st.markdown("## 🔍 DOI Navigator")
st.caption("Advanced Research Paper Metadata Extraction & Analysis")

# ------------------ Sidebar ------------------
with st.sidebar:
    st.header("⚙️ Configuration")
    min_score = st.slider("🎯 Fuzzy Match Threshold", 60, 95, 80)
    wos_if_jcr = st.checkbox("📊 Auto-mark WoS if in JCR", True)
    scopus_exact_first = st.checkbox("🔍 Scopus exact match first", True)
    workers = st.slider("⚡ Parallel requests", 2, 16, 12)

# ------------------ Helpers ------------------
def _get_session() -> requests.Session:
    s = requests.Session()
    retries = Retry(total=4, backoff_factor=0.5, status_forcelist=[429,500,502,503,504], allowed_methods=frozenset(["GET"]))
    adapter = HTTPAdapter(max_retries=retries, pool_connections=64, pool_maxsize=64)
    s.mount("https://", adapter); s.mount("http://", adapter)
    s.headers.update({"User-Agent": "DOI-Navigator/1.1 (mailto:kunal.bhattacharya221@gmail.com)"})
    return s

def normalize_doi(s: str) -> str:
    s = s.strip()
    low = s.lower()
    for p in ("https://doi.org/","http://doi.org/","doi:","doi "):
        if low.startswith(p): s = s[len(p):]
    return s.strip()

def normalize_journal(name: str) -> str:
    if not name: return ""
    s = name.lower().replace("&","and")
    s = re.sub(r"[.,:;()\[\]]"," ",s)
    s = re.sub(r"\s+"," ",s).strip()
    return s

def _first(x): return x[0] if isinstance(x,list) and x else (x or "")

def _authors_from(msg: dict) -> str:
    parts = []
    for a in msg.get("author", []) or []:
        if not isinstance(a, dict): continue
        given = (a.get("given") or "").strip()
        family = (a.get("family") or "").strip()
        initials = " ".join(w[0].upper()+"." for w in re.split(r"[\s-]+", given) if w)
        s = f"{family}, {initials}".strip().rstrip(",")
        if s: parts.append(s)
    if len(parts)==1: return parts[0]
    if len(parts)==2: return " & ".join(parts)
    return ", ".join(parts[:-1]) + ", & " + parts[-1] if parts else ""

def extract_crossref_fields(obj: dict) -> Dict:
    title = _first(obj.get("title"))
    journal = _first(obj.get("container-title"))
    publisher = obj.get("publisher") or obj.get("publisher-name") or ""
    year = None
    for k in ("published-print","issued","published-online"):
        dp = obj.get(k,{}).get("date-parts")
        if isinstance(dp,list) and dp and isinstance(dp[0],list) and dp[0]:
            year = dp[0][0]; break
    if not year:
        try: year = int(str(obj.get("created",{}).get("date-time",""))[:4])
        except: year = None
    cites = obj.get("is-referenced-by-count")
    return {"Title":title or "","Authors":_authors_from(obj),"Journal":journal or "","Publisher":publisher,"Year":year,"Citations (Crossref)":cites or ""}

def fetch_crossref(doi: str) -> dict:
    r = _get_session().get(f"https://api.crossref.org/works/{requests.utils.quote(doi)}", timeout=20)
    r.raise_for_status(); return r.json().get("message",{})

def fetch_csl(doi: str) -> dict:
    r = _get_session().get(f"https://doi.org/{requests.utils.quote(doi)}", headers={"Accept":"application/vnd.citationstyles.csl+json"}, timeout=20)
    r.raise_for_status(); return r.json()

# ------------------ Input ------------------
st.subheader("🔍 Input DOIs")
dois_text = st.text_area("Enter one DOI per line", height=160, label_visibility="collapsed",
                         placeholder="10.1016/j.arr.2025.102847\n10.1016/j.arr.2025.102834\nhttps://doi.org/10.1038/nature12373")
st.markdown("---")

# Action row (keeps your UI compact by default)
c1,c2,c3 = st.columns([1,1,1])
go = c1.button("🚀 Fetch Metadata", type="primary", use_container_width=True)
if c2.button("🗑️ Clear All", use_container_width=True):
    st.rerun()
with c3:
    _lines = [ln.strip() for ln in (dois_text or "").splitlines() if ln.strip()]
    DOIS = sorted(set(normalize_doi(ln) for ln in _lines))
    st.metric("DOIs", len(DOIS))

# ------------------ About block (toggles on/off; no style changes) ------------------
if st.session_state.show_about:
    st.markdown(
        """
        <div style="max-width:900px;margin:24px auto;padding:16px;border-radius:16px;border:1px solid rgba(127,127,127,.25)">
          <div style="font-weight:800;margin-bottom:8px">About</div>
          <p><strong>DOI Navigator</strong> fetches metadata from DOIs (Crossref first; DOI CSL fallback). Optional JCR/Scopus enrichment (if you add it) and Excel export.</p>
        </div>
        """, unsafe_allow_html=True
    )

# ------------------ Fetch ------------------
results_df: Optional[pd.DataFrame] = None
if go:
    if not DOIS:
        st.warning("Please paste at least one DOI.")
    else:
        rows = []
        with st.spinner("🔎 Fetching metadata..."):
            for i, doi in enumerate(DOIS, 1):
                try:
                    msg = fetch_crossref(doi)
                    data = extract_crossref_fields(msg)
                except Exception:
                    try:
                        csl = fetch_csl(doi)
                        data = {
                            "Title": csl.get("title",""),
                            "Authors": "; ".join(a.get("family","") for a in csl.get("author",[]) if a.get("family")),
                            "Journal": csl.get("container-title",""),
                            "Publisher": csl.get("publisher",""),
                            "Year": csl.get("issued",{}).get("date-parts",[[None]])[0][0] if csl.get("issued") else None,
                            "Citations (Crossref)": ""
                        }
                    except Exception as e:
                        data = {"Title": f"[ERROR] {e}","Authors":"","Journal":"","Publisher":"","Year":None,"Citations (Crossref)":""}
                rows.append({"DOI": doi, **data})
                if i % 8 == 0: time.sleep(0.05)
        results_df = pd.DataFrame(rows)

# ------------------ Results ------------------
if results_df is not None:
    st.subheader("📊 Results")
    st.dataframe(results_df, use_container_width=True, hide_index=True)
    from io import BytesIO
    with BytesIO() as buf:
        with pd.ExcelWriter(buf, engine="xlsxwriter") as wr:
            results_df.to_excel(wr, index=False, sheet_name="DOI Metadata")
        xlsx = buf.getvalue()
    st.download_button("📥 Download Excel", data=xlsx, file_name="doi_metadata.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ------------------ Footer (email only) ------------------
year = datetime.now().year
st.markdown(
    f"""
    <div style="margin-top:24px;text-align:center;color:rgba(127,127,127,.9)">
      <strong>DOI Navigator</strong> • © {year} •
      <a href="mailto:kunal.bhattacharya221@gmail.com" style="text-decoration:none;color:inherit">kunal.bhattacharya221@gmail.com</a>
    </div>
    """, unsafe_allow_html=True
)
