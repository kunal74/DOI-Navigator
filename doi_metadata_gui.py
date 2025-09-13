# doi_metadata_gui.py
# DOI Navigator — cloud-friendly (no local paths)
# Users only paste DOIs. App auto-loads JCR & Scopus Excel from the URLs below
# (or from Streamlit Secrets if you set JCR_URL / SCOPUS_URL).
# Crossref citations only; CSV download; dark neutral UI.

import io
import time
import typing as t
from dataclasses import dataclass
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

try:
    from rapidfuzz import fuzz, process  # optional but faster
    _USE_RAPIDFUZZ = True
except Exception:
    import difflib
    _USE_RAPIDFUZZ = False


# --------------------------------------------------------------------
# Built-in data sources (your Dropbox links)
# If Streamlit Secrets are set, they override these.
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
st.caption("Paste DOIs. The app auto-loads JCR & Scopus lists provided by the owner. Download CSV.")


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------
def _download_excel(url: str) -> io.BytesIO:
    r = requests.get(url, timeout=45)
    r.raise_for_status()
    return io.BytesIO(r.content)

def _load_bytes_from_secret(key: str) -> t.Optional[io.BytesIO]:
    url = st.secrets.get(key, "")
    if not url:
        return None
    try:
        return _download_excel(url)
    except Exception as e:
        st.warning(f"Could not download {key} from secrets: {e}")
        return None


# --------------------------------------------------------------------
# Matching config & helpers
# --------------------------------------------------------------------
@dataclass
class MatchConfig:
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

def best_fuzzy_match(name: str, candidates: t.List[str], min_score: int = 80) -> t.Tuple[str, int]:
    name = normalize_journal(name)
    if not name or not candidates:
        return ("", 0)
    if _USE_RAPIDFUZZ:
        best = process.extractOne(name, candidates, scorer=fuzz.WRatio)
        if best:
            return best[0], int(best[1])
        return ("", 0)
    else:
        match = difflib.get_close_matches(name, candidates, n=1, cutoff=0.0)
        if match:
            score = int(100 * difflib.SequenceMatcher(None, name, match[0]).ratio())
            return match[0], score
        return ("", 0)


# --------------------------------------------------------------------
# Readers (accept file-like objects)
# --------------------------------------------------------------------
def read_jcr(io_obj) -> pd.DataFrame:
    """Read first sheet; map columns: B=Journal, M=Impact Factor, Q=Quartile."""
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
# Crossref
# --------------------------------------------------------------------
def crossref_fetch(doi: str, timeout: float = 15.0) -> dict:
    url = f"https://api.crossref.org/works/{doi}"
    headers = {"User-Agent": "DOI-Navigator/1.0 (mailto:your.email@domain)"}  # ← put your real email
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json().get("message", {})

def extract_fields(msg: dict) -> dict:
    title = ""
    if isinstance(msg.get("title"), list) and msg["title"]:
        title = msg["title"][0]
    journal = ""
    if isinstance(msg.get("container-title"), list) and msg["container-title"]:
        journal = msg["container-title"][0]
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
    return {"Title": title, "Journal": journal, "Publisher": publisher, "Year": year,
            "Citations (Crossref)": cites}


# --------------------------------------------------------------------
# Merge & Enrich
# --------------------------------------------------------------------
@dataclass
class MatchCfg:
    min_score: int = 80
    wos_if_missing: bool = True
    scopus_exact_first: bool = True

def merge_enrich(df: pd.DataFrame, jcr: pd.DataFrame, scopus: pd.DataFrame, mcfg: MatchCfg) -> pd.DataFrame:
    jcr_map = dict(zip(jcr["__norm"], jcr.index))
    scopus_set = set(scopus["__norm"].tolist())
    jcr_candidates = list(jcr_map.keys())

    imp, qrt, scp, wos = [], [], [], []
    for j in df["Journal"].fillna("").astype(str):
        norm = normalize_journal(j)
        # JCR
        best, score = best_fuzzy_match(norm, jcr_candidates, mcfg.min_score)
        if best and score >= mcfg.min_score:
            row = jcr.iloc[jcr_map[best]]
            imp.append(row["Impact Factor"]); qrt.append(row["Quartile"]); wos.append(True if mcfg.wos_if_missing else None)
        else:
            imp.append(None); qrt.append(None); wos.append(False if mcfg.wos_if_missing else None)
        # Scopus
        found = (norm in scopus_set) if mcfg.scopus_exact_first else False
        if not found:
            best_s, score_s = best_fuzzy_match(norm, list(scopus_set), mcfg.min_score)
            found = bool(best_s and score_s >= mcfg.min_score)
        scp.append(found)

    df["Impact Factor (JCR)"] = imp
    df["Quartile (JCR)"] = qrt
    df["Indexed in Scopus"] = scp
    df["Indexed in Web of Science"] = wos
    return df


# --------------------------------------------------------------------
# Sidebar — only matching options (no path fields, no uploads)
# --------------------------------------------------------------------
with st.sidebar:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("Matching Settings")
    min_score = st.slider("Fuzzy match minimum score", 60, 95, 80)
    st.caption("Higher Score = Higher Accuracy. Start with Default Score")
    wos_if_jcr = st.checkbox("Mark 'Indexed in Web of Science' if present in JCR", value=True)
    scopus_exact = st.checkbox("Scopus: try exact normalized match before fuzzy", value=True)
    st.markdown('</div>', unsafe_allow_html=True)

mcfg = MatchCfg(min_score=min_score, wos_if_missing=wos_if_jcr, scopus_exact_first=scopus_exact)


# --------------------------------------------------------------------
# Main panel
# --------------------------------------------------------------------
st.markdown('<div class="section-card">', unsafe_allow_html=True)
st.subheader("Enter DOIs")
dois_text = st.text_area(
    "Paste one DOI per line",
    height=150,
    placeholder="10.1038/s41586-020-2649-2\n10.1126/science.aba3389"
)
st.markdown('</div>', unsafe_allow_html=True)

st.markdown('<div class="section-card">', unsafe_allow_html=True)
col1, col2 = st.columns([1,1])
with col1: fetch = st.button("Fetch Metadata", type="primary")
with col2: clear = st.button("Clear")
st.markdown('</div>', unsafe_allow_html=True)

if clear:
    st.experimental_rerun()

dois = [d.strip() for d in dois_text.splitlines() if d.strip()]
results_df = None

def load_jcr_and_scopus():
    """
    Return (jcr_df, scopus_df).
    Priority: Secrets URLs (if present) -> fallback URLs above -> empty frames.
    """
    jcr_url = st.secrets.get("JCR_URL", JCR_FALLBACK_URL)
    scp_url = st.secrets.get("SCOPUS_URL", SCOPUS_FALLBACK_URL)

    jcr = pd.DataFrame(columns=["Journal", "Impact Factor", "Quartile", "__norm"])
    sc  = pd.DataFrame(columns=["Scopus Title", "__norm"])

    if jcr_url:
        try:
            jcr = read_jcr(_download_excel(jcr_url))
        except Exception as e:
            st.warning(f"JCR preload failed: {e}")

    if scp_url:
        try:
            sc = read_scopus_titles(_download_excel(scp_url))
        except Exception as e:
            st.warning(f"Scopus preload failed: {e}")

    return jcr, sc

if fetch:
    jcr_df, sc_df = load_jcr_and_scopus()

    rows = []
    for doi in dois:
        entry = {"DOI": doi, "Title": "", "Journal": "", "Publisher": "", "Year": None, "Citations (Crossref)": None}
        try:
            msg = crossref_fetch(doi)
            entry.update(extract_fields(msg))
        except Exception as e:
            entry["Title"] = f"[ERROR] {e}"
        rows.append(entry); time.sleep(0.15)

    base_df = pd.DataFrame(rows)
    if not base_df.empty:
        results_df = merge_enrich(base_df, jcr_df, sc_df, mcfg)

if results_df is not None and not results_df.empty:
    st.markdown('<div class="dataframe-wrap">', unsafe_allow_html=True)
    st.subheader("Results")
    st.dataframe(results_df, use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)
    csv_bytes = results_df.to_csv(index=False).encode()
    st.download_button("Download CSV", csv_bytes, "doi_metadata.csv", "text/csv")
else:
    st.info("Enter DOIs and click **Fetch Metadata** to see results.")

# Footer
year = datetime.now().year
st.markdown(f'<div class="footer-credit">© {year} · Developed by Dr. Kunal Bhattacharya</div>', unsafe_allow_html=True)
