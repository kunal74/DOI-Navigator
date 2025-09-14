# doi_metadata_gui.py
# DOI Navigator – fast, RA-agnostic (Crossref + DOI content negotiation fallback)
#
# - Paste DOIs (full https://doi.org/... also fine)
# - JCR & Scopus auto-load (your Dropbox links; Streamlit Secrets can override)
# - Speed: parallel requests + retries; 12h cache (JCR/Scopus), 7d cache (per-DOI)
# - Matching: RapidFuzz vectorized cdist (fallback to difflib)
# - Fallback for non-Crossref DOIs via DOI content negotiation (CSL-JSON)
# - UI: dark theme; bright ticks on screen; Excel exports with UTF-8 BOM
# - Authors formatted "Given Family" (e.g., "Pravin D. Patil")
#
# References:
# - DOI content negotiation works across RAs via doi.org: https://www.crossref.org/documentation/retrieve-metadata/content-negotiation/  # noqa
# - DataCite note on CN for any DOI: https://support.datacitate.org/docs/what-is-the-best-way-to-make-a-content-negotiation-request-for-any-doi  # noqa

import io
import difflib
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
# Built-in data sources (your Dropbox links). Secrets override these.
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
# Page & Styles - ELEGANT UI WITH BOUNCING BALLS
# --------------------------------------------------------------------
st.set_page_config(page_title="DOI Navigator", layout="wide", page_icon="🔍", initial_sidebar_state="expanded")

# Enhanced CSS with elegant colors and bouncing balls animation
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700;800;900&display=swap');

/* Global Styles - Elegant Color Scheme */
.stApp {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    font-family: 'Poppins', sans-serif;
}

/* Animated Background - Subtle and Elegant */
.stApp::before {
    content: '';
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background-image: 
        radial-gradient(circle at 20% 80%, rgba(233, 69, 96, 0.08) 0%, transparent 50%),
        radial-gradient(circle at 80% 20%, rgba(52, 211, 153, 0.08) 0%, transparent 50%),
        radial-gradient(circle at 40% 40%, rgba(94, 114, 228, 0.08) 0%, transparent 50%);
    animation: gradientShift 25s ease infinite;
    pointer-events: none;
    z-index: -1;
}

@keyframes gradientShift {
    0%, 100% { transform: translate(0, 0) rotate(0deg); }
    33% { transform: translate(-15px, -15px) rotate(120deg); }
    66% { transform: translate(15px, -10px) rotate(240deg); }
}

/* Bouncing Balls Animation */
.bouncing-balls {
    position: absolute;
    width: 100%;
    height: 100px;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    pointer-events: none;
    z-index: 1;
}

.ball {
    position: absolute;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    animation: bounce 2s infinite ease-in-out;
}

.ball:nth-child(1) {
    left: 20%;
    background: linear-gradient(135deg, #e94560, #ff6b6b);
    animation-delay: 0s;
    box-shadow: 0 0 20px rgba(233, 69, 96, 0.6);
}

.ball:nth-child(2) {
    left: 35%;
    background: linear-gradient(135deg, #34d399, #10b981);
    animation-delay: 0.2s;
    box-shadow: 0 0 20px rgba(52, 211, 153, 0.6);
}

.ball:nth-child(3) {
    left: 50%;
    background: linear-gradient(135deg, #5e72e4, #667eea);
    animation-delay: 0.4s;
    box-shadow: 0 0 20px rgba(94, 114, 228, 0.6);
}

.ball:nth-child(4) {
    left: 65%;
    background: linear-gradient(135deg, #f59e0b, #fbbf24);
    animation-delay: 0.6s;
    box-shadow: 0 0 20px rgba(245, 158, 11, 0.6);
}

.ball:nth-child(5) {
    left: 80%;
    background: linear-gradient(135deg, #8b5cf6, #a78bfa);
    animation-delay: 0.8s;
    box-shadow: 0 0 20px rgba(139, 92, 246, 0.6);
}

@keyframes bounce {
    0%, 100% {
        transform: translateY(0) scale(1);
    }
    50% {
        transform: translateY(-30px) scale(1.1);
    }
}

/* Header Styles - Elegant and Refined */
.hero-section {
    background: linear-gradient(135deg, rgba(94, 114, 228, 0.05), rgba(233, 69, 96, 0.05));
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 24px;
    padding: 40px;
    margin: -20px -50px 30px -50px;
    backdrop-filter: blur(20px);
    box-shadow: 
        0 10px 40px rgba(0, 0, 0, 0.2),
        inset 0 1px 0 rgba(255, 255, 255, 0.05);
    animation: slideDown 0.6s ease-out;
    position: relative;
    overflow: visible;
}

@keyframes slideDown {
    from { opacity: 0; transform: translateY(-30px); }
    to { opacity: 1; transform: translateY(0); }
}

.main-title {
    font-size: 56px;
    font-weight: 800;
    background: linear-gradient(135deg, #e94560 0%, #34d399 25%, #5e72e4 50%, #f59e0b 75%, #8b5cf6 100%);
    background-size: 400% 400%;
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    letter-spacing: -1px;
    margin: 0;
    animation: gradientFlow 10s ease infinite;
    text-align: center;
    position: relative;
    z-index: 2;
}

@keyframes gradientFlow {
    0%, 100% { background-position: 0% 50%; }
    50% { background-position: 100% 50%; }
}

.subtitle {
    color: #94a3b8;
    font-size: 18px;
    font-weight: 400;
    text-align: center;
    margin-top: 10px;
    opacity: 0;
    animation: fadeInUp 0.8s ease-out 0.3s forwards;
}

@keyframes fadeInUp {
    to { opacity: 1; transform: translateY(0); }
    from { opacity: 0; transform: translateY(10px); }
}

/* Input Styles - Elegant Dark Theme */
.stTextArea textarea, .stTextInput input {
    background: rgba(15, 23, 42, 0.6) !important;
    border: 2px solid rgba(94, 114, 228, 0.2) !important;
    border-radius: 12px !important;
    color: #e2e8f0 !important;
    font-size: 15px !important;
    padding: 12px 16px !important;
    transition: all 0.3s ease !important;
    backdrop-filter: blur(10px) !important;
}

.stTextArea textarea:focus, .stTextInput input:focus {
    border-color: rgba(94, 114, 228, 0.5) !important;
    box-shadow: 0 0 0 3px rgba(94, 114, 228, 0.1) !important;
    background: rgba(15, 23, 42, 0.8) !important;
}

/* Button Styles - Elegant Gradients */
.stButton > button {
    background: linear-gradient(135deg, #5e72e4 0%, #667eea 100%);
    color: white;
    border: none;
    border-radius: 12px;
    padding: 12px 32px;
    font-weight: 600;
    font-size: 16px;
    transition: all 0.3s ease;
    box-shadow: 0 4px 15px rgba(94, 114, 228, 0.3);
    position: relative;
    overflow: hidden;
}

.stButton > button::before {
    content: '';
    position: absolute;
    top: 0;
    left: -100%;
    width: 100%;
    height: 100%;
    background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.15), transparent);
    transition: left 0.5s ease;
}

.stButton > button:hover::before {
    left: 100%;
}

.stButton > button:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(94, 114, 228, 0.4);
}

/* Primary Button Special Style */
[data-testid="stButton"] button[kind="primary"] {
    background: linear-gradient(135deg, #e94560 0%, #ff6b6b 100%);
    box-shadow: 0 4px 15px rgba(233, 69, 96, 0.3);
}

/* Download Button */
.stDownloadButton > button {
    background: linear-gradient(135deg, #34d399 0%, #10b981 100%);
    color: white;
    border: none;
    border-radius: 12px;
    padding: 12px 32px;
    font-weight: 600;
    transition: all 0.3s ease;
    box-shadow: 0 4px 15px rgba(52, 211, 153, 0.3);
}

.stDownloadButton > button:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(52, 211, 153, 0.4);
}

/* Slider Styles */
.stSlider > div > div > div > div {
    background: linear-gradient(90deg, #5e72e4, #e94560) !important;
}

.stSlider > div > div > div[role="slider"] {
    background: white !important;
    box-shadow: 0 2px 10px rgba(94, 114, 228, 0.4) !important;
}

/* Checkbox Styles */
.stCheckbox label {
    color: #e2e8f0 !important;
    font-weight: 500;
}

/* DataFrame Styles */
.dataframe-container {
    background: rgba(15, 23, 42, 0.5);
    border: 1px solid rgba(94, 114, 228, 0.15);
    border-radius: 16px;
    padding: 20px;
    backdrop-filter: blur(10px);
    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
    margin: 20px 0;
    animation: slideUp 0.6s ease-out;
}

@keyframes slideUp {
    from { opacity: 0; transform: translateY(20px); }
    to { opacity: 1; transform: translateY(0); }
}

[data-testid="stDataFrame"] {
    background: transparent !important;
}

[data-testid="stTable"] {
    background: transparent !important;
}

/* Progress Bar - Elegant Animation */
.stProgress > div > div > div {
    background: linear-gradient(90deg, #5e72e4, #e94560, #34d399) !important;
    background-size: 200% 100%;
    animation: progressGradient 2s ease infinite;
    border-radius: 10px;
    height: 8px !important;
}

@keyframes progressGradient {
    0% { background-position: 0% 50%; }
    100% { background-position: 200% 50%; }
}

/* Sidebar Styles - Elegant Dark */
.css-1d391kg, [data-testid="stSidebar"] {
    background: rgba(15, 23, 42, 0.95);
    backdrop-filter: blur(20px);
    border-right: 1px solid rgba(94, 114, 228, 0.15);
}

/* Info/Success/Warning Messages */
.stAlert {
    background: rgba(94, 114, 228, 0.08) !important;
    border: 1px solid rgba(94, 114, 228, 0.2) !important;
    border-radius: 12px !important;
    color: #e2e8f0 !important;
    backdrop-filter: blur(10px);
}

/* Metrics Cards - Elegant Style */
.metric-card {
    background: linear-gradient(135deg, rgba(94, 114, 228, 0.08), rgba(233, 69, 96, 0.08));
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 16px;
    padding: 20px;
    text-align: center;
    transition: all 0.3s ease;
}

.metric-card:hover {
    transform: translateY(-5px);
    box-shadow: 0 10px 30px rgba(94, 114, 228, 0.2);
}

.metric-value {
    font-size: 32px;
    font-weight: 700;
    background: linear-gradient(135deg, #5e72e4, #e94560);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}

.metric-label {
    color: #94a3b8;
    font-size: 14px;
    font-weight: 500;
    margin-top: 8px;
}

/* Footer */
.footer-section {
    margin-top: 60px;
    padding: 30px;
    background: rgba(15, 23, 42, 0.5);
    border-radius: 20px;
    border: 1px solid rgba(94, 114, 228, 0.15);
    text-align: center;
}

.footer-credit {
    color: #94a3b8;
    font-size: 14px;
    font-weight: 400;
}

.footer-credit a {
    color: #5e72e4;
    text-decoration: none;
    transition: color 0.3s ease;
}

.footer-credit a:hover {
    color: #e94560;
}

/* Spinner Enhancement */
.stSpinner > div {
    border-color: #5e72e4 !important;
}

/* Caption Styles */
.caption-text {
    color: #94a3b8;
    font-size: 14px;
    font-style: italic;
    margin-top: 8px;
}

/* Stats Display */
.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 20px;
    margin: 30px 0;
}

/* Fade in animation for elements */
.fade-in {
    animation: fadeInElement 0.8s ease-out;
}

@keyframes fadeInElement {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
}

/* Custom scrollbar - Elegant */
::-webkit-scrollbar {
    width: 10px;
    height: 10px;
}

::-webkit-scrollbar-track {
    background: rgba(15, 23, 42, 0.5);
}

::-webkit-scrollbar-thumb {
    background: linear-gradient(135deg, #5e72e4, #e94560);
    border-radius: 5px;
}

::-webkit-scrollbar-thumb:hover {
    background: linear-gradient(135deg, #e94560, #5e72e4);
}

/* Single Line Separator */
hr {
    border: 0;
    height: 0.1px;
    background: #94a3b8;
    margin: 20px 0;
}
</style>
""", unsafe_allow_html=True)

# Hero Section with Bouncing Balls
st.markdown("""
<div class="hero-section">
    <div class="bouncing-balls">
        <div class="ball"></div>
        <div class="ball"></div>
        <div class="ball"></div>
        <div class="ball"></div>
        <div class="ball"></div>
    </div>
    <h1 class="main-title">🔍 DOI Navigator</h1>
    <p class="subtitle">Advanced Research Paper Metadata Extraction & Analysis</p>
</div>
""", unsafe_allow_html=True)

# Session / networking
def _get_session() -> requests.Session:
    s = requests.Session()
    retries = Retry(
        total=4,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET"]),
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=64, pool_maxsize=64)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    # Polite pool: include a real email here
    s.headers.update({"User-Agent": "DOI-Navigator/1.1 (mailto:your.email@domain)"})
    return s

def _download_excel(url: str) -> io.BytesIO:
    r = _get_session().get(url, timeout=60)
    r.raise_for_status()
    return io.BytesIO(r.content)

# DOI normalization (accept full https://doi.org/ links)
def normalize_doi_input(s: str) -> str:
    s = s.strip()
    low = s.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:", "doi "):
        if low.startswith(prefix):
            s = s[len(prefix):]
            break
    return s.strip()

# Matching config & helpers
@dataclass
class MatchCfg:
    min_score: int = 80
    wos_if_missing: bool = True
    scopus_exact_first: bool = True

def normalize_journal(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = s.lower().replace("&", "and")
    for ch in [",", ".", ":", ";", "(", ")", "[", "]"]:
        s = s.replace(ch, " ")
    return " ".join(s.split())

# Readers (accept file-like objects)
def read_jcr(io_obj) -> pd.DataFrame:
    xls = pd.ExcelFile(io_obj, engine="openpyxl")
    df = pd.read_excel(xls, xls.sheet_names[0])
    if df.shape[1] < 17:
        raise ValueError("JCR file has fewer than 17 columns; cannot map B/M/Q reliably.")
    journal_col = df.columns[1]   # B
    impact_col = df.columns[12]   # M
    quartile_col = df.columns[16] # Q
    out = df[[journal_col, impact_col, quartile_col]].copy()
    out.columns = ["Journal", "Impact Factor", "Quartile"]
    out["__norm"] = out["Journal"].map(normalize_journal)
    return out

_SCOPUS_TITLE_LIKELY = {
    "source title", "title", "journal", "publication title", "full title",
    "journal title", "journal name", "scopus title", "scopus source title",
}
def _pick_scopus_title_col(df: pd.DataFrame) -> str:
    cols = {c.lower().strip(): c for c in df.columns}
    for key in _SCOPUS_TITLE_LIKELY:
        if key in cols:
            return cols[key]
    for c in df.columns:
        if pd.api.types.is_object_dtype(df[c]):
            return c
    return df.columns[0]

def read_scopus_titles(io_obj) -> pd.DataFrame:
    xls = pd.ExcelFile(io_obj, engine="openpyxl")
    df = pd.read_excel(xls, xls.sheet_names[0])
    title_col = _pick_scopus_title_col(df)
    out = df[[title_col]].copy()
    out.columns = ["Scopus Title"]
    out["__norm"] = out["Scopus Title"].map(normalize_journal)
    return out

# Cache heavy loads (12h)
@st.cache_data(show_spinner=True, ttl=60*60*12)
def load_jcr_cached(url: str) -> pd.DataFrame:
    return read_jcr(_download_excel(url))

@st.cache_data(show_spinner=True, ttl=60*60*12)
def load_scopus_cached(url: str) -> pd.DataFrame:
    return read_scopus_titles(_download_excel(url))

# Metadata fetchers: Crossref + DOI content negotiation fallback
def _crossref_fetch_raw(doi: str, timeout: float = 15.0) -> dict:
    url = f"https://api.crossref.org/works/{doi}"
    r = _get_session().get(url, timeout=timeout)
    r.raise_for_status()
    return r.json().get("message", {})

def _doi_content_negotiation(doi: str, timeout: float = 15.0) -> dict:
    """
    Universal fallback: request CSL-JSON via doi.org (works for Crossref/DataCite/mEDRA).
    """
    url = f"https://doi.org/{doi}"
    headers = {"Accept": "application/vnd.citationstyles.csl+json"}
    r = _get_session().get(url, headers=headers, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r.json()

def _format_authors(msg: dict) -> str:
    """
    Build 'Given Family' for each author (e.g., 'Pravin D. Patil').
    - Keeps middle initials; adds a dot to single-letter initials
    - Falls back to 'name'/'literal' if not split
    - Joins with '; ' (no trailing semicolon)
    """
    authors = msg.get("author", [])
    parts = []

    def fix_initials(s: str) -> str:
        tokens = s.split()
        fixed = []
        for tok in tokens:
            if len(tok) == 1 and tok.isalpha():
                fixed.append(tok + ".")
            else:
                fixed.append(tok)
        return " ".join(fixed)

    if isinstance(authors, list):
        for a in authors:
            if not isinstance(a, dict):
                continue
            given = (a.get("given") or "").strip()
            family = (a.get("family") or "").strip()
            literal = (a.get("name") or a.get("literal") or "").strip()
            if given or family:
                given_fixed = fix_initials(given)
                name = (given_fixed + " " + family).strip()
            else:
                name = literal
            if name:
                parts.append(name)

    return "; ".join(parts)

def _first(x):
    if isinstance(x, list):
        return x[0] if x else ""
    return x or ""

def _extract_fields_generic(msg: dict, source: str) -> dict:
    """
    Works with both Crossref 'message' JSON and CSL-JSON from content negotiation.
    """
    title = _first(msg.get("title"))
    # In CSL-JSON, container-title is usually a string; in Crossref it's a list
    journal = _first(msg.get("container-title"))
    publisher = msg.get("publisher", "") or msg.get("publisher-name", "")
    # Year handling: support Crossref ('published-print'/'issued'/'published-online') and CSL 'issued'
    year = None
    for key in ["published-print", "issued", "published-online"]:
        obj = msg.get(key, {})
        if isinstance(obj, dict):
            parts = obj.get("date-parts", [])
            if parts and isinstance(parts[0], list) and parts[0]:
                year = parts[0][0]
                break
    if not year:
        try:
            year = int(str(msg.get("created", {}).get("date-time", ""))[:4])
        except Exception:
            year = None

    cites = msg.get("is-referenced-by-count", None) if source == "crossref" else None

    return {
        "Title": title,
        "Authors": _format_authors(msg),
        "Journal": journal,
        "Publisher": publisher,
        "Year": year,
        "Citations (Crossref)": cites,  # only present if Crossref provided it
    }

@st.cache_data(show_spinner=False, ttl=60*60*24*7)
def fetch_metadata_unified(doi: str) -> dict:
    """
    Try Crossref first (gives us Crossref citations when available);
    if not found, fallback to DOI content negotiation (CSL-JSON).
    """
    # 1) Crossref
    try:
        msg = _crossref_fetch_raw(doi)
        data = _extract_fields_generic(msg, source="crossref")
        if data.get("Title") or data.get("Journal"):
            return data
    except Exception:
        pass

    # 2) Fallback: DOI content negotiation (universal)
    try:
        csl = _doi_content_negotiation(doi)
        data = _extract_fields_generic(csl, source="csl")
        if data.get("Title") or data.get("Journal"):
            return data
    except Exception as e:
        return {"error": f"Not found via Crossref; DOI content negotiation also failed: {e}"}

    return {"error": "Metadata not available from Crossref or DOI content negotiation."}

def fetch_parallel(dois: list[str], max_workers: int = 12) -> list[dict]:
    """Parallel fetch with progress; preserves input order."""
    order = {d: i for i, d in enumerate(dois)}
    entries: list[dict] = []
    with ThreadPoolExecutor(max_workers=min(max_workers, max(1, len(dois)))) as ex:
        futs = {ex.submit(fetch_metadata_unified, d): d for d in dois}
        total, done = len(futs), 0
        progress = st.progress(0.0, text="Initializing...")
        with st.spinner("🔍 Fetching metadata with universal DOI fallback..."):
            for fut in as_completed(futs):
                doi = futs[fut]
                data = fut.result()
                if "error" in data:
                    entry = {
                        "DOI": doi,
                        "Title": f"[ERROR] {data['error']}",
                        "Authors": "",
                        "Journal": "",
                        "Publisher": "",
                        "Year": None,
                        "Citations (Crossref)": None,
                    }
                else:
                    entry = {"DOI": doi, **data}
                entries.append(entry)
                done += 1
                progress.progress(done / total, text=f"Processing {done}/{total} papers...")
        progress.empty()
    entries.sort(key=lambda e: order.get(e["DOI"], 10**9))
    return entries

# Batch merge with RapidFuzz cdist (very fast)
def merge_enrich_fast(df: pd.DataFrame, jcr: pd.DataFrame, scopus: pd.DataFrame, cfg: MatchCfg) -> pd.DataFrame:
    if df.empty:
        return df
    q = df["Journal"].fillna("").astype(str).map(normalize_journal).tolist()

    # --- JCR (Impact Factor & Quartile) ---
    imp = [None] * len(q)
    qrt = [None] * len(q)
    wos = [False if cfg.wos_if_missing else None] * len(q)

    if not jcr.empty:
        j_choices = jcr["__norm"].tolist()
        if _USE_RAPIDFUZZ and q and j_choices:
            scores = process.cdist(q, j_choices, scorer=fuzz.WRatio, workers=-1)
            best_idx = scores.argmax(axis=1)
            best_scr = scores.max(axis=1)
            for i, s in enumerate(best_scr):
                if s >= cfg.min_score:
                    row = jcr.iloc[best_idx[i]]
                    imp[i] = row["Impact Factor"]
                    qrt[i] = row["Quartile"]
                    if cfg.wos_if_missing:
                        wos[i] = True
        else:
            for i, name in enumerate(q):
                if not name:
                    continue
                match = difflib.get_close_matches(name, j_choices, n=1, cutoff=0.0)
                if match:
                    score = int(100 * difflib.SequenceMatcher(None, name, match[0]).ratio())
                    if score >= cfg.min_score:
                        row = jcr.iloc[j_choices.index(match[0])]
                        imp[i] = row["Impact Factor"]
                        qrt[i] = row["Quartile"]
                        if cfg.wos_if_missing:
                            wos[i] = True

    # --- Scopus (Indexed?) ---
    scp = [False] * len(q)
    if not scopus.empty:
        s_choices = scopus["__norm"].tolist()
        s_set = set(s_choices) if cfg.scopus_exact_first else set()
        for i, name in enumerate(q):
            if cfg.scopus_exact_first and name in s_set:
                scp[i] = True
        if _USE_RAPIDFUZZ and q and s_choices:
            need = [i for i, v in enumerate(scp) if not v]
            if need:
                qs = [q[i] for i in need]
                scores = process.cdist(qs, s_choices, scorer=fuzz.WRatio, workers=-1)
                best_scr = scores.max(axis=1)
                for k, s in enumerate(best_scr):
                    if s >= cfg.min_score:
                        scp[need[k]] = True
        else:
            for i, name in enumerate(q):
                if scp[i]:
                    continue
                match = difflib.get_close_matches(name, s_choices, n=1, cutoff=0.0)
                if match:
                    score = int(100 * difflib.SequenceMatcher(None, name, match[0]).ratio())
                    if score >= cfg.min_score:
                        scp[i] = True

    out = df.copy()
    out["Impact Factor (JCR)"] = imp
    out["Quartile (JCR)"] = qrt
    out["Indexed in Scopus"] = scp
    out["Indexed in Web of Science"] = wos
    return out

# Sidebar with Enhanced UI
with st.sidebar:
    st.markdown('<h2 style="color: #e2e8f0; margin-bottom: 20px;">⚙️ Configuration</h2>', unsafe_allow_html=True)
    
    st.markdown('<h3 style="color: #e2e8f0;">Matching Settings</h3>', unsafe_allow_html=True)
    min_score = st.slider("🎯 Fuzzy Match Threshold", 60, 95, 80, 
                          help="Higher score = stricter matching. Default: 80")
    st.caption("💡 Tip: Start with default (80) for balanced accuracy")
    
    wos_if_jcr = st.checkbox("📊 Auto-mark WoS if in JCR", value=True,
                             help="Automatically mark as indexed in Web of Science if found in JCR database")
    scopus_exact = st.checkbox("🔍 Scopus exact match first", value=True,
                              help="Try exact normalized matching before fuzzy matching for Scopus")
    st.markdown('<hr>', unsafe_allow_html=True)
    
    st.markdown('<h3 style="color: #e2e8f0;">Performance</h3>', unsafe_allow_html=True)
    fast_workers = st.slider("⚡ Parallel requests", 2, 16, 12,
                             help="Number of concurrent API requests")
    st.caption("🔒 Keep respectful to public APIs")
    st.markdown('<hr>', unsafe_allow_html=True)
    
    # Permanent stats only
    st.markdown('<h3 style="color: #e2e8f0;">📈 Database Stats</h3>', unsafe_allow_html=True)
    st.markdown(f'<div class="metric-card"><div class="metric-value">29,270</div><div class="metric-label">JCR Journals Scanned</div></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="metric-card"><div class="metric-value">47,838</div><div class="metric-label">Scopus Journals Scanned</div></div>', unsafe_allow_html=True)

cfg = MatchCfg(min_score=min_score, wos_if_missing=wos_if_jcr, scopus_exact_first=scopus_exact)

# Main panel with enhanced UI
# Input Section
st.markdown('<h3 style="color: #e2e8f0;">📝 Input DOIs</h3>', unsafe_allow_html=True)

# Create tab for input method
tab1 = st.tabs(["📋 Paste DOIs"])[0]
with tab1:
    dois_text = st.text_area(
        "Enter one DOI per line",
        height=200,
        placeholder="10.1016/j.arr.2025.102847\n10.1016/j.arr.2025.102834\n10.17179/excli2014-541\nhttps://doi.org/10.1038/nature12373",
        help="You can paste DOIs with or without https://doi.org/ prefix"
    )
st.markdown('<hr>', unsafe_allow_html=True)

# Action Buttons with enhanced styling
st.markdown('<h3 style="color: #e2e8f0;">Action Buttons</h3>', unsafe_allow_html=True)
col1, col2, col3 = st.columns([2, 2, 1])
with col1:
    fetch = st.button("🚀 Fetch Metadata", type="primary", use_container_width=True)
with col2:
    if st.button("🗑️ Clear All", use_container_width=True):
        # Clear session state immediately
        if 'jcr_df' in st.session_state:
            del st.session_state.jcr_df
        if 'sc_df' in st.session_state:
            del st.session_state.sc_df
        st.rerun()
with col3:
    # Display DOI count
    raw_lines = [d for d in dois_text.splitlines() if d.strip()]
    dois = list(dict.fromkeys(normalize_doi_input(d) for d in raw_lines))
    st.markdown(f'<div class="metric-card"><div class="metric-value">{len(dois)}</div><div class="metric-label">DOIs</div></div>', unsafe_allow_html=True)
st.markdown('<hr>', unsafe_allow_html=True)

results_df = None

def load_jcr_and_scopus():
    # Use fallback URLs directly - no secrets needed
    jcr_url = JCR_FALLBACK_URL
    scp_url = SCOPUS_FALLBACK_URL
    
    # Create a nice loading container
    with st.container():
        st.info("📄 Loading JCR and Scopus databases...")
        progress_bar = st.progress(0)
        status = st.empty()
        
        try:
            status.text("Loading JCR database...")
            progress_bar.progress(25)
            jcr = load_jcr_cached(jcr_url) if jcr_url else pd.DataFrame(
                columns=["Journal", "Impact Factor", "Quartile", "__norm"]
            )
            
            status.text("Loading Scopus database...")
            progress_bar.progress(75)
            scp = load_scopus_cached(scp_url) if scp_url else pd.DataFrame(
                columns=["Scopus Title", "__norm"]
            )
            
            progress_bar.progress(100)
            status.success("✅ Databases loaded successfully!")
            
            # Store in session state for processing
            st.session_state.jcr_df = jcr
            st.session_state.sc_df = scp
            
            # Brief pause to show success
            import time
            time.sleep(1)
            
        finally:
            progress_bar.empty()
            status.empty()
    
    return jcr, scp

if fetch:
    if len(dois) == 0:
        st.error("⚠️ Please enter at least one DOI to proceed.")
    else:
        jcr_df, sc_df = load_jcr_and_scopus()
        
        # Fetch metadata with enhanced progress display
        st.markdown('<h3 style="color: #e2e8f0;">🔍 Fetching Metadata</h3>', unsafe_allow_html=True)
        
        rows = fetch_parallel(dois, max_workers=fast_workers)
        base_df = pd.DataFrame(rows)
        
        if not base_df.empty:
            with st.spinner("📄 Matching with JCR and Scopus databases..."):
                results_df = merge_enrich_fast(base_df, jcr_df, sc_df, cfg)
            st.success(f"✅ Successfully processed {len(results_df)} papers!")
        st.markdown('<hr>', unsafe_allow_html=True)

# ---------- DISPLAY & DOWNLOAD ----------
if results_df is not None and not results_df.empty:
    # 1-based index for display
    results_df.index = pd.RangeIndex(start=1, stop=len(results_df) + 1, name="S.No.")
    
    # Statistics Section
    st.markdown('<h3 style="color: #e2e8f0;">📊 Analysis Summary</h3>', unsafe_allow_html=True)
    
    col1, col2, col3, col4 = st.columns(4)
    
    # Calculate statistics
    total_papers = len(results_df)
    wos_count = results_df["Indexed in Web of Science"].sum()
    scopus_count = results_df["Indexed in Scopus"].sum()
    q1_count = (results_df["Quartile (JCR)"] == "Q1").sum()
    
    with col1:
        st.markdown(f'''
        <div class="metric-card">
            <div class="metric-value">{total_papers}</div>
            <div class="metric-label">Total Papers</div>
        </div>
        ''', unsafe_allow_html=True)
    
    with col2:
        wos_pct = (wos_count/total_papers*100) if total_papers > 0 else 0
        st.markdown(f'''
        <div class="metric-card">
            <div class="metric-value">{wos_count}</div>
            <div class="metric-label">WoS Indexed ({wos_pct:.1f}%)</div>
        </div>
        ''', unsafe_allow_html=True)
    
    with col3:
        scopus_pct = (scopus_count/total_papers*100) if total_papers > 0 else 0
        st.markdown(f'''
        <div class="metric-card">
            <div class="metric-value">{scopus_count}</div>
            <div class="metric-label">Scopus Indexed ({scopus_pct:.1f}%)</div>
        </div>
        ''', unsafe_allow_html=True)
    
    with col4:
        q1_pct = (q1_count/total_papers*100) if total_papers > 0 else 0
        st.markdown(f'''
        <div class="metric-card">
            <div class="metric-value">{q1_count}</div>
            <div class="metric-label">Q1 Papers ({q1_pct:.1f}%)</div>
        </div>
        ''', unsafe_allow_html=True)
    st.markdown('<hr>', unsafe_allow_html=True)
    
    # Results Table
    st.markdown('<h3 style="color: #e2e8f0;">📑 Results Table</h3>', unsafe_allow_html=True)
    
    # DISPLAY with enhanced emojis
    disp = results_df.copy()
    
    def yn_to_emoji(v):
        if v is True:
            return "✅ Yes"
        if v is False:
            return "❌ No"
        return "➖ N/A"
    
    def format_quartile(v):
        if pd.isna(v) or v == "":
            return "➖"
        return f"🏆 {v}" if v == "Q1" else f"📊 {v}"
    
    disp["Indexed in Scopus"] = disp["Indexed in Scopus"].map(yn_to_emoji)
    disp["Indexed in Web of Science"] = disp["Indexed in Web of Science"].map(yn_to_emoji)
    disp["Quartile (JCR)"] = disp["Quartile (JCR)"].map(format_quartile)
    
    st.dataframe(
        disp, 
        use_container_width=True,
        height=400,
        column_config={
            "DOI": st.column_config.TextColumn("DOI", help="Digital Object Identifier"),
            "Title": st.column_config.TextColumn("Title", width="large"),
            "Authors": st.column_config.TextColumn("Authors", width="medium"),
            "Journal": st.column_config.TextColumn("Journal", width="medium"),
            "Year": st.column_config.NumberColumn("Year", format="%d"),
            "Citations (Crossref)": st.column_config.NumberColumn("Citations", format="%d"),
            "Impact Factor (JCR)": st.column_config.NumberColumn("Impact Factor", format="%.1f"),
        }
    )
    st.markdown('<hr>', unsafe_allow_html=True)
    
    # Download Section
    st.markdown('<h3 style="color: #e2e8f0;">💾 Export Options</h3>', unsafe_allow_html=True)
    
    # DOWNLOAD: Excel-friendly text
    export_df = results_df.copy()
    export_df["Indexed in Scopus"] = export_df["Indexed in Scopus"].map(
        lambda v: "Yes" if v is True else "No" if v is False else ""
    )
    export_df["Indexed in Web of Science"] = export_df["Indexed in Web of Science"].map(
        lambda v: "Yes" if v is True else "No" if v is False else ""
    )
    
    # Create Excel file
    from io import BytesIO
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        export_df.to_excel(writer, index=True, sheet_name='DOI Metadata')
    excel_data = output.getvalue()
    
    st.download_button(
        "📊 Download as Excel",
        excel_data,
        "doi_metadata.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
    st.markdown('<hr>', unsafe_allow_html=True)

else:
    # Welcome message when no data
    st.markdown("""
    <div style="text-align: center; padding: 40px;">
        <h2 style="color: #e2e8f0; margin-bottom: 20px;">👋 Welcome to DOI Navigator</h2>
        <p style="color: #94a3b8; font-size: 16px; line-height: 1.6;">
            Enter DOIs above and click <strong>Fetch Metadata</strong> to extract comprehensive paper information.<br>
            The app automatically matches papers with JCR and Scopus databases for impact factors and indexing status.
        </p>
        <div style="margin-top: 30px; display: flex; justify-content: center; gap: 40px;">
            <div style="text-align: center;">
                <div style="font-size: 32px; margin-bottom: 10px;">📚</div>
                <div style="color: #94a3b8; font-size: 14px;">Multi-DOI Support</div>
            </div>
            <div style="text-align: center;">
                <div style="font-size: 32px; margin-bottom: 10px;">⚡</div>
                <div style="color: #94a3b8; font-size: 14px;">Fast Processing</div>
            </div>
            <div style="text-align: center;">
                <div style="font-size: 32px; margin-bottom: 10px;">🎯</div>
                <div style="color: #94a3b8; font-size: 14px;">Accurate Matching</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown('<hr>', unsafe_allow_html=True)

# Footer
year = datetime.now().year
st.markdown(f'''
<div class="footer-section">
    <div class="footer-credit">
        <strong>DOI Navigator v1.1</strong><br>
        © {year} · Developed with ❤️ by Dr. Kunal Bhattacharya<br>
        <span style="font-size: 12px; color: #5e72e4;">Powered by Crossref API · JCR · Scopus</span>
    </div>
</div>
''', unsafe_allow_html=True)
