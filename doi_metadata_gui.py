# doi_metadata_gui.py
# DOI Navigator — ultra fast & cloud-friendly
# - Users paste DOIs (URLs ok: https://doi.org/....)
# - JCR & Scopus auto-load (Secrets override fallbacks)
# - Caching (JCR/Scopus 12h, Crossref 7d), parallel Crossref with retries
# - RapidFuzz batch matching (cdist) for speed, bright ticks, 1-based index

import io
import time
import typing as t
from dataclasses import dataclass
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    import difflib
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
# Page & Styles
# --------------------------------------------------------------------
st.set_page_config(page_title="DOI Navigator", layout="wide", page_icon="🧭")
st.markdown("""
<style>
.stApp { background: #0b1220; color: #e5e7eb; }
.big-title { color: #e5e7eb; font-size: 36px; font-weight: 850; letter-spacing: .2px; margin: 0 0 6px 0; }
.section-card { background: #111827; border: 1px solid #1f2937; border-radius: 14px; padding: 16px 18px; box-shadow: 0 10px 24px rgba(0,0,0,.35); }
div[data-baseweb="input"] input, textarea { background: #0f172a !important; color: #e5e7eb !important; border: 1px solid #334155 !important; border-radius: 10px !important; }
.stSlider>div>div>div>div { background: #3b82f6 !important; } .stSlider>div>div>div[role="slider"] { background: #93c5fd !important; }
.stButton>button, .stDownloadButton>button { background: #3b82f6; color: #fff; border-radius: 10px; padding: .55rem 1rem; border: 0; box-shadow: 0 8px 18px rgba(59,130,246,.35); }
.stButton>button:hover, .stDownloadButton>button:hover { filter: brightness(1.06); }
.dataframe-wrap { background: #0f172a; border: 1px solid #1f2937; border-radius: 14px; box-shadow: 0 10px 22px rgba(0,0,0,.35); padding: 8px; }
.footer-credit { margin-top: 20px; text-align: center; color: #94a3b8; font-size: 13px; }
</style>
""", unsafe_allow_html=True)
st.markdown('<div class="big-title">DOI Navigator</div>', unsafe_allow_html=True)
st.caption("Paste DOIs. The app auto-loads JCR & Scopus. Download CSV.")

# --------------------------------------------------------------------
# Session / networking
# --------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def _get_session() -> requests.Session:
    s = requests.Session()
    retries = Retry(
        total=4, backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET"])
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=32, pool_maxsize=32)
    s.mount("https://", adapter); s.mount("http://", adapter)
    # Crossref polite pool: include a real email here
    s.headers.update({"User-Agent": "DOI-Navigator/1.0 (mailto:your.email@domain)"})
    return s

def _download_excel(url: str) -> io.BytesIO:
    r = _get_session().get(url, timeout=60)
    r.raise_for_status()
    return io.BytesIO(r.content)

# --------------------------------------------------------------------
# DOI normalization (accept full https://doi.org/ links)
# --------------------------------------------------------------------
def normalize_doi_input(s: str) -> str:
    s = s.strip()
    low = s.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:", "doi "):
        if low.startswith(prefix):
            s = s[len(prefix):]
            break
    return s.strip()

# --------------------------------------------------------------------
# Matching config & helpers
# --------------------------------------------------------------------
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

# --------------------------------------------------------------------
# Readers (accept file-like objects)
# --------------------------------------------------------------------
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
    "journal title", "journal name", "scopus title", "scopus source title"
}
def _pick_scopus_title_col(df: pd.DataFrame) -> str:
    cols = {c.lower().strip(): c for c in df.columns}
    for key in _SCOPUS_TITLE_LIKELY:
        if key in cols: return cols[key]
    for c in df.columns:
        if pd.api.types.is_object_dtype(df[c]): return c
    return df.columns[0]

def read_scopus_titles(io_obj) -> pd.DataFrame:
    xls = pd.ExcelFile(io_obj, engine="openpyxl")
    df = pd.read_excel(xls, xls.sheet_names[0])
    title_col = _pick_scopus_title_col(df)
    out = df[[title_col]].copy()
    out.columns = ["Scopus Title"]
    out["__norm"] = out["Scopus Title"].map(normalize_journal)
    return out

# --------------------------------------------------------------------
# Cache heavy loads (12h)
# --------------------------------------------------------------------
@st.cache_data(show_spinner=True, ttl=60*60*12)
def load_jcr_cached(url: str) -> pd.DataFrame:
    return read_jcr(_download_excel(url))

@st.cache_data(show_spinner=True, ttl=60*60*12)
def load_scopus_cached(url: str) -> pd.DataFrame:
    return read_scopus_titles(_download_excel(url))

# --------------------------------------------------------------------
# Crossref fetching (parallel + 7d cache)
# --------------------------------------------------------------------
def _crossref_fetch_raw(doi: str, timeout: float = 15.0) -> dict:
    url = f"https://api.crossref.org/works/{doi}"
    r = _get_session().get(url, timeout=timeout)
    r.raise_for_status()
    return r.json().get("message", {})

def _extract_fields(msg: dict) -> dict:
    title = msg.get("title", [""])
    title = title[0] if isinstance(title, list) and title else ""
    ctitle = msg.get("container-title", [""])
    journal = ctitle[0] if isinstance(ctitle, list) and ctitle else ""
    publisher = msg.get("publisher", "")
    year = None
    for key in ["published-print", "issued", "published-online"]:
        obj = msg.get(key, {})
        if isinstance(obj, dict):
            parts = obj.get("date-parts", [])
            if parts and isinstance(parts[0], list) and parts[0]:
                year = parts[0][0]; break
    if not year:
        try: year = int(str(msg.get("created", {}).get("date-time", ""))[:4])
        except Exception: year = None
    cites = msg.get("is-referenced-by-count", None)
    return {"Title": title, "Journal": journal, "Publisher": publisher,
            "Year": year, "Citations (Crossref)": cites}

@st.cache_data(show_spinner=False, ttl=60*60*24*7)  # cache each DOI for 7 days
def fetch_crossref_cached(doi: str) -> dict:
    try:
        return _extract_fields(_crossref_fetch_raw(doi))
    except Exception as e:
        return {"error": str(e)}

def fetch_crossref_parallel(dois: list[str], max_workers: int = 8) -> list[dict]:
    entries: list[dict] = []
    with ThreadPoolExecutor(max_workers=min(max_workers, max(1, len(dois)))) as ex:
        futs = {ex.submit(fetch_crossref_cached, d): d for d in dois}
        total, done = len(futs), 0
        progress = st.progress(0.0, text="Starting…")
        with st.spinner("🔎 Searching Crossref and matching JCR / Scopus…"):
            for fut in as_completed(futs):
                doi = futs[fut]
                data = fut.result()
                if "error" in data:
                    entry = {"DOI": doi, "Title": f"[ERROR] {data['error']}",
                             "Journal": "", "Publisher": "", "Year": None,
                             "Citations (Crossref)": None}
                else:
                    entry = {"DOI": doi, **data}
                entries.append(entry)
                done += 1
                progress.progress(done/total, text=f"Processing {done}/{total}…")
        progress.empty()
    return entries

# --------------------------------------------------------------------
# Batch merge with RapidFuzz cdist (very fast)
# --------------------------------------------------------------------
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
            # scores[i, j] = similarity(q[i], j_choices[j])
            scores = process.cdist(q, j_choices, scorer=fuzz.WRatio, workers=-1)
            best_idx = scores.argmax(axis=1)
            best_scr = scores.max(axis=1)
            for i, s in enumerate(best_scr):
                if s >= cfg.min_score:
                    row = jcr.iloc[best_idx[i]]
                    imp[i] = row["Impact Factor"]
                    qrt[i] = row["Quartile"]
                    if cfg.wos_if_missing: wos[i] = True
        else:
            # Fallback: slower per-row
            for i, name in enumerate(q):
                if not name: continue
                if _USE_RAPIDFUZZ:
                    best = process.extractOne(name, j_choices, scorer=fuzz.WRatio)
                    if best and best[1] >= cfg.min_score:
                        row = jcr.iloc[best[2] if len(best) > 2 else j_choices.index(best[0])]
                        imp[i] = row["Impact Factor"]; qrt[i] = row["Quartile"]; 
                        if cfg.wos_if_missing: wos[i] = True
                else:
                    match = difflib.get_close_matches(name, j_choices, n=1, cutoff=0.0)
                    if match:
                        score = int(100 * difflib.SequenceMatcher(None, name, match[0]).ratio())
                        if score >= cfg.min_score:
                            row = jcr.iloc[j_choices.index(match[0])]
                            imp[i] = row["Impact Factor"]; qrt[i] = row["Quartile"]; 
                            if cfg.wos_if_missing: wos[i] = True

    # --- Scopus (Indexed?) ---
    scp = [False] * len(q)
    if not scopus.empty:
        s_choices = scopus["__norm"].tolist()
        s_set = set(s_choices) if cfg.scopus_exact_first else set()
        # exact first
        for i, name in enumerate(q):
            if cfg.scopus_exact_first and name in s_set:
                scp[i] = True
        # fuzzy for the rest
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
                if scp[i]: continue
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

# --------------------------------------------------------------------
# Sidebar
# --------------------------------------------------------------------
with st.sidebar:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("Matching Settings")
    min_score = st.slider("Fuzzy match minimum score", 60, 95, 80)
    st.caption("Higher Score = Higher Accuracy. Start with Default Score")
    wos_if_jcr = st.checkbox("Mark 'Indexed in Web of Science' if present in JCR", value=True)
    scopus_exact = st.checkbox("Scopus: try exact normalized match before fuzzy", value=True)
    st.markdown("---")
    fast_workers = st.slider("Max parallel requests (Crossref)", 2, 16, 8)
    st.caption("Use a sensible number to stay polite with Crossref.")
    st.markdown('</div>', unsafe_allow_html=True)

cfg = MatchCfg(min_score=min_score, wos_if_missing=wos_if_jcr, scopus_exact_first=scopus_exact)

# --------------------------------------------------------------------
# Main panel
# --------------------------------------------------------------------
st.markdown('<div class="section-card">', unsafe_allow_html=True)
st.subheader("Enter DOIs")
dois_text = st.text_area(
    "Paste one DOI per line",
    height=150,
    placeholder="https://doi.org/10.1016/j.arr.2025.102847\nhttps://doi.org/10.1016/j.arr.2025.102834"
)
st.markdown('</div>', unsafe_allow_html=True)

st.markdown('<div class="section-card">', unsafe_allow_html=True)
col1, col2 = st.columns([1,1])
with col1: fetch = st.button("Fetch Metadata", type="primary")
with col2: clear = st.button("Clear")
st.markdown('</div>', unsafe_allow_html=True)

if clear:
    st.experimental_rerun()

raw_lines = [d for d in dois_text.splitlines() if d.strip()]
# de-dupe early so we do fewer network calls
dois = list(dict.fromkeys(normalize_doi_input(d) for d in raw_lines))

results_df = None

def load_jcr_and_scopus():
    jcr_url = st.secrets.get("JCR_URL", JCR_FALLBACK_URL)
    scp_url = st.secrets.get("SCOPUS_URL", SCOPUS_FALLBACK_URL)
    status = st.empty(); status.info("Loading JCR / Scopus lists…")
    try:
        jcr = load_jcr_cached(jcr_url) if jcr_url else pd.DataFrame(columns=["Journal","Impact Factor","Quartile","__norm"])
        scp = load_scopus_cached(scp_url) if scp_url else pd.DataFrame(columns=["Scopus Title","__norm"])
    finally:
        status.empty()
    return jcr, scp

if fetch:
    jcr_df, sc_df = load_jcr_and_scopus()

    if len(dois) == 0:
        st.info("Enter at least one DOI.")
    else:
        rows = fetch_crossref_parallel(dois, max_workers=fast_workers)
        base_df = pd.DataFrame(rows)
        if not base_df.empty:
            results_df = merge_enrich_fast(base_df, jcr_df, sc_df, cfg)

if results_df is not None and not results_df.empty:
    # 1-based index for display
    results_df.index = pd.RangeIndex(start=1, stop=len(results_df) + 1, name="S.No.")

    # Bright tick icons
    disp = results_df.copy()
    def yn_to_emoji(v):
        if v is True: return "✅"
        if v is False: return "❌"
        return ""
    disp["Indexed in Scopus"] = disp["Indexed in Scopus"].map(yn_to_emoji)
    disp["Indexed in Web of Science"] = disp["Indexed in Web of Science"].map(yn_to_emoji)

    st.markdown('<div class="dataframe-wrap">', unsafe_allow_html=True)
    st.subheader("Results")
    st.dataframe(disp, use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

    csv_bytes = disp.to_csv(index=True).encode()
    st.download_button("Download CSV", csv_bytes, "doi_metadata.csv", "text/csv")
else:
    st.info("Enter DOIs and click **Fetch Metadata** to see results.")

# Footer
year = datetime.now().year
st.markdown(f'<div class="footer-credit">© {year} · Developed by Dr. Kunal Bhattacharya</div>', unsafe_allow_html=True)
