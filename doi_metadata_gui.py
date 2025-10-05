# doi_metadata_gui_adaptive.py
# DOI Navigator with Authentication System - Adaptive Light/Dark Theme
# Enhanced to work with both light and dark Windows themes

import io
import difflib
import hashlib
import sqlite3
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
# Database Setup for User Management (UNCHANGED)
# --------------------------------------------------------------------
DB_PATH = "doi_navigator_users.db"

def init_database():
    """Initialize the SQLite database for user management"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Users table
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT,
            organization TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP,
            is_active BOOLEAN DEFAULT 1
        )
    ''')
    
    # Login history table
    c.execute('''
        CREATE TABLE IF NOT EXISTS login_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ip_address TEXT,
            user_agent TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    conn.commit()
    conn.close()

def hash_password(password: str) -> str:
    """Hash a password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_user(username: str, password: str) -> dict:
    """Verify user credentials"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    password_hash = hash_password(password)
    c.execute('''
        SELECT id, username, email, full_name, organization 
        FROM users 
        WHERE (username = ? OR email = ?) AND password_hash = ? AND is_active = 1
    ''', (username, username, password_hash))
    
    user = c.fetchone()
    conn.close()
    
    if user:
        return {
            'id': user[0],
            'username': user[1],
            'email': user[2],
            'full_name': user[3],
            'organization': user[4]
        }
    return None

def create_user(username: str, email: str, password: str, full_name: str = "", organization: str = "") -> tuple:
    """Create a new user account"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    try:
        password_hash = hash_password(password)
        c.execute('''
            INSERT INTO users (username, email, password_hash, full_name, organization)
            VALUES (?, ?, ?, ?, ?)
        ''', (username, email, password_hash, full_name, organization))
        conn.commit()
        conn.close()
        return True, "Account created successfully!"
    except sqlite3.IntegrityError as e:
        conn.close()
        if 'username' in str(e):
            return False, "Username already exists!"
        elif 'email' in str(e):
            return False, "Email already registered!"
        else:
            return False, "Registration failed. Please try again."

def log_login(user_id: int):
    """Log user login"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''
        UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?
    ''', (user_id,))
    
    c.execute('''
        INSERT INTO login_history (user_id, ip_address, user_agent)
        VALUES (?, ?, ?)
    ''', (user_id, "N/A", "Streamlit App"))
    
    conn.commit()
    conn.close()

def validate_email(email: str) -> bool:
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

# --------------------------------------------------------------------
# Login Interface with Adaptive Theme
# --------------------------------------------------------------------
def show_login_page():
    """Display the login page with adaptive theme"""
    st.set_page_config(page_title="DOI Navigator - Login", layout="wide", page_icon="🔍", initial_sidebar_state="collapsed")
    
    # Adaptive Login page CSS
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700;800;900&display=swap');
    
    /* CSS Variables for Light/Dark Theme Support */
    :root {
        --primary-bg: #ffffff;
        --secondary-bg: #f8f9fa;
        --card-bg: rgba(255, 255, 255, 0.95);
        --text-primary: #1a1a2e;
        --text-secondary: #6c757d;
        --border-color: rgba(0, 0, 0, 0.1);
        --shadow-light: rgba(0, 0, 0, 0.1);
        --shadow-medium: rgba(0, 0, 0, 0.15);
        --input-bg: rgba(255, 255, 255, 0.8);
        --input-border: rgba(94, 114, 228, 0.3);
    }
    
    /* Dark theme detection */
    @media (prefers-color-scheme: dark) {
        :root {
            --primary-bg: #1a1a2e;
            --secondary-bg: #16213e;
            --card-bg: rgba(15, 23, 42, 0.95);
            --text-primary: #e2e8f0;
            --text-secondary: #94a3b8;
            --border-color: rgba(255, 255, 255, 0.1);
            --shadow-light: rgba(0, 0, 0, 0.3);
            --shadow-medium: rgba(0, 0, 0, 0.4);
            --input-bg: rgba(15, 23, 42, 0.8);
            --input-border: rgba(94, 114, 228, 0.4);
        }
    }
    
    .stApp {
        background: linear-gradient(135deg, var(--primary-bg) 0%, var(--secondary-bg) 50%, var(--primary-bg) 100%);
        font-family: 'Poppins', sans-serif;
        color: var(--text-primary);
    }
    
    .auth-title {
        font-size: 48px;
        font-weight: 800;
        background: linear-gradient(135deg, #e94560 0%, #34d399 25%, #5e72e4 50%, #f59e0b 75%, #8b5cf6 100%);
        background-size: 400% 400%;
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        animation: gradientFlow 10s ease infinite;
        text-align: center;
        margin-bottom: 10px;
    }
    
    @keyframes gradientFlow {
        0%, 100% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
    }
    
    .stTextInput input {
        background: var(--input-bg) !important;
        border: 2px solid var(--input-border) !important;
        border-radius: 12px !important;
        color: var(--text-primary) !important;
        padding: 12px 16px !important;
    }
    
    .stTextInput input::placeholder {
        color: var(--text-secondary) !important;
        opacity: 0.7;
    }
    
    .stButton > button {
        background: linear-gradient(135deg, #5e72e4 0%, #667eea 100%);
        color: white;
        border: none;
        border-radius: 12px;
        padding: 12px 32px;
        font-weight: 600;
        box-shadow: 0 4px 15px rgba(94, 114, 228, 0.3);
    }
    
    /* Ensure text visibility in both themes */
    .stMarkdown, .stText, p {
        color: var(--text-primary) !important;
    }
    
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    
    .stTabs [data-baseweb="tab"] {
        background-color: var(--card-bg);
        border: 1px solid var(--border-color);
        border-radius: 8px;
        color: var(--text-primary);
    }
    
    .stTabs [aria-selected="true"] {
        background-color: var(--input-bg);
        border-color: #5e72e4;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Center the login form
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown('<h1 class="auth-title">🔍 DOI Navigator</h1>', unsafe_allow_html=True)
        st.markdown('<p style="text-align: center; color: var(--text-secondary); margin-bottom: 30px;">Sign in to access the research paper metadata tool</p>', unsafe_allow_html=True)
        
        tab1, tab2 = st.tabs(["🔐 Login", "📝 Sign Up"])
        
        with tab1:
            with st.form("login_form"):
                username = st.text_input("Username or Email", placeholder="Enter your username or email")
                password = st.text_input("Password", type="password", placeholder="Enter your password")
                
                col_a, col_b = st.columns(2)
                with col_a:
                    submit = st.form_submit_button("🚀 Sign In", use_container_width=True, type="primary")
                
                if submit:
                    if username and password:
                        user = verify_user(username, password)
                        if user:
                            st.session_state.authenticated = True
                            st.session_state.user = user
                            log_login(user['id'])
                            st.success(f"Welcome, {user['full_name'] or user['username']}!")
                            st.rerun()
                        else:
                            st.error("Invalid credentials. Please try again.")
                    else:
                        st.warning("Please enter both username/email and password.")
        
        with tab2:
            with st.form("signup_form"):
                col1, col2 = st.columns(2)
                with col1:
                    new_username = st.text_input("Username*", placeholder="Choose a username")
                    new_password = st.text_input("Password*", type="password", placeholder="Min 6 characters")
                    new_full_name = st.text_input("Full Name", placeholder="John Doe")
                
                with col2:
                    new_email = st.text_input("Email*", placeholder="john@example.com")
                    new_password_confirm = st.text_input("Confirm Password*", type="password")
                    new_organization = st.text_input("Organization", placeholder="University/Company")
                
                submit_signup = st.form_submit_button("🎯 Create Account", use_container_width=True, type="primary")
                
                if submit_signup:
                    errors = []
                    
                    if not new_username or not new_email or not new_password:
                        errors.append("Please fill in all required fields")
                    
                    if not validate_email(new_email):
                        errors.append("Please enter a valid email address")
                    
                    if len(new_password) < 6:
                        errors.append("Password must be at least 6 characters")
                    
                    if new_password != new_password_confirm:
                        errors.append("Passwords do not match")
                    
                    if errors:
                        for error in errors:
                            st.error(error)
                    else:
                        success, message = create_user(
                            new_username, new_email, new_password, 
                            new_full_name, new_organization
                        )
                        if success:
                            st.success(message + " Please login to continue.")
                            st.balloons()
                        else:
                            st.error(message)

# --------------------------------------------------------------------
# Built-in data sources (UNCHANGED)
# --------------------------------------------------------------------
JCR_FALLBACK_URL = (
    "https://www.dropbox.com/scl/fi/z1xdk4pbpko4p2x0brgq7/AllJournalsJCR2025.xlsx"
    "?rlkey=3kxhjziorfbo2xwf4p177ukin&st=0bu01tph&dl=1"
)
SCOPUS_FALLBACK_URL = (
    "https://www.dropbox.com/scl/fi/1uv8s3207pojp4tzzt8f4/ext_list_Aug_2025.xlsx"
    "?rlkey=kyieyvc0b08vgo0asxhe0j061&st=ooszzvmx&dl=1"
)

def run_original_app():
    """Main app with adaptive theme support"""
    
    # --------------------------------------------------------------------
    # Page & Styles - ADAPTIVE THEME
    # --------------------------------------------------------------------
    st.set_page_config(page_title="DOI Navigator", layout="wide", page_icon="🔍", initial_sidebar_state="expanded")

    # Enhanced CSS with adaptive light/dark theme support
    st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700;800;900&display=swap');

/* CSS Variables for Adaptive Theme */
:root {
    /* Light theme default */
    --primary-bg: #ffffff;
    --secondary-bg: #f8f9fa;
    --tertiary-bg: #e9ecef;
    --card-bg: rgba(255, 255, 255, 0.95);
    --card-bg-alt: rgba(248, 249, 250, 0.95);
    --text-primary: #212529;
    --text-secondary: #6c757d;
    --text-muted: #868e96;
    --border-color: rgba(0, 0, 0, 0.125);
    --border-light: rgba(0, 0, 0, 0.06);
    --shadow-light: rgba(0, 0, 0, 0.08);
    --shadow-medium: rgba(0, 0, 0, 0.12);
    --shadow-heavy: rgba(0, 0, 0, 0.16);
    --input-bg: rgba(255, 255, 255, 0.9);
    --input-border: rgba(94, 114, 228, 0.25);
    --sidebar-bg: rgba(248, 249, 250, 0.95);
    --gradient-bg: linear-gradient(135deg, #ffffff 0%, #f8f9fa 50%, #e9ecef 100%);
}

/* Dark theme overrides */
@media (prefers-color-scheme: dark) {
    :root {
        --primary-bg: #1a1a2e;
        --secondary-bg: #16213e;
        --tertiary-bg: #0f3460;
        --card-bg: rgba(15, 23, 42, 0.95);
        --card-bg-alt: rgba(22, 33, 62, 0.95);
        --text-primary: #e2e8f0;
        --text-secondary: #94a3b8;
        --text-muted: #64748b;
        --border-color: rgba(255, 255, 255, 0.1);
        --border-light: rgba(255, 255, 255, 0.05);
        --shadow-light: rgba(0, 0, 0, 0.2);
        --shadow-medium: rgba(0, 0, 0, 0.3);
        --shadow-heavy: rgba(0, 0, 0, 0.4);
        --input-bg: rgba(15, 23, 42, 0.8);
        --input-border: rgba(94, 114, 228, 0.4);
        --sidebar-bg: rgba(15, 23, 42, 0.95);
        --gradient-bg: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    }
}

/* Global Styles */
.stApp {
    background: var(--gradient-bg);
    font-family: 'Poppins', sans-serif;
    color: var(--text-primary);
}

/* Animated Background - Subtle */
.stApp::before {
    content: '';
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background-image: 
        radial-gradient(circle at 20% 80%, rgba(233, 69, 96, 0.03) 0%, transparent 50%),
        radial-gradient(circle at 80% 20%, rgba(52, 211, 153, 0.03) 0%, transparent 50%),
        radial-gradient(circle at 40% 40%, rgba(94, 114, 228, 0.03) 0%, transparent 50%);
    animation: gradientShift 25s ease infinite;
    pointer-events: none;
    z-index: -1;
}

@keyframes gradientShift {
    0%, 100% { transform: translate(0, 0) rotate(0deg); }
    33% { transform: translate(-15px, -15px) rotate(120deg); }
    66% { transform: translate(15px, -10px) rotate(240deg); }
}

/* Bouncing Balls Animation - Adaptive colors */
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
    box-shadow: 0 0 20px rgba(233, 69, 96, 0.4);
}

.ball:nth-child(2) {
    left: 35%;
    background: linear-gradient(135deg, #34d399, #10b981);
    animation-delay: 0.2s;
    box-shadow: 0 0 20px rgba(52, 211, 153, 0.4);
}

.ball:nth-child(3) {
    left: 50%;
    background: linear-gradient(135deg, #5e72e4, #667eea);
    animation-delay: 0.4s;
    box-shadow: 0 0 20px rgba(94, 114, 228, 0.4);
}

.ball:nth-child(4) {
    left: 65%;
    background: linear-gradient(135deg, #f59e0b, #fbbf24);
    animation-delay: 0.6s;
    box-shadow: 0 0 20px rgba(245, 158, 11, 0.4);
}

.ball:nth-child(5) {
    left: 80%;
    background: linear-gradient(135deg, #8b5cf6, #a78bfa);
    animation-delay: 0.8s;
    box-shadow: 0 0 20px rgba(139, 92, 246, 0.4);
}

@keyframes bounce {
    0%, 100% {
        transform: translateY(0) scale(1);
    }
    50% {
        transform: translateY(-30px) scale(1.1);
    }
}

/* Header Styles - Adaptive */
.hero-section {
    background: var(--card-bg);
    border: 1px solid var(--border-light);
    border-radius: 24px;
    padding: 40px;
    margin: -20px -50px 30px -50px;
    backdrop-filter: blur(20px);
    box-shadow: 
        0 10px 40px var(--shadow-light),
        inset 0 1px 0 var(--border-light);
    animation: slideDown 0.6s ease-out;
    position: relative;
    overflow: hidden;  /* Changed from visible to hidden */
    min-height: 200px;  /* Added minimum height */
}

/* Particle Canvas */
#particleCanvas {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
    opacity: 0.6;
}

@keyframes slideDown {
    from { opacity: 0; transform: translateY(-30px); }
    to { opacity: 1; transform: translateY(0); }
}
/* Geometric Background Pattern */
.geometric-bg {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    overflow: hidden;
    opacity: 0.1;
}

.geo-shape {
    position: absolute;
    border: 2px solid;
    border-radius: 30% 70% 70% 30% / 30% 30% 70% 70%;
    animation: morphShape 15s ease-in-out infinite;
}

.geo-shape-1 {
    width: 300px;
    height: 300px;
    top: -100px;
    left: -100px;
    border-color: #e94560;
    animation-delay: 0s;
}

.geo-shape-2 {
    width: 200px;
    height: 200px;
    top: 50%;
    right: -50px;
    border-color: #34d399;
    animation-delay: 3s;
}

.geo-shape-3 {
    width: 150px;
    height: 150px;
    bottom: -50px;
    left: 20%;
    border-color: #5e72e4;
    animation-delay: 6s;
}

.geo-shape-4 {
    width: 250px;
    height: 250px;
    top: 20%;
    left: 40%;
    border-color: #f59e0b;
    animation-delay: 9s;
}

.geo-shape-5 {
    width: 180px;
    height: 180px;
    bottom: 10%;
    right: 20%;
    border-color: #8b5cf6;
    animation-delay: 12s;
}

.geo-shape-6 {
    width: 220px;
    height: 220px;
    top: -50px;
    right: 30%;
    border-color: #10b981;
    animation-delay: 15s;
}

@keyframes morphShape {
    0%, 100% {
        border-radius: 30% 70% 70% 30% / 30% 30% 70% 70%;
        transform: rotate(0deg) scale(1);
    }
    25% {
        border-radius: 70% 30% 30% 70% / 70% 70% 30% 30%;
        transform: rotate(90deg) scale(1.1);
    }
    50% {
        border-radius: 30% 70% 70% 30% / 70% 30% 30% 70%;
        transform: rotate(180deg) scale(0.9);
    }
    75% {
        border-radius: 70% 30% 30% 70% / 30% 70% 70% 30%;
        transform: rotate(270deg) scale(1.05);
    }
}

/* Floating Dots Animation */
.floating-dots {
    position: absolute;
    width: 100%;
    height: 100%;
    overflow: hidden;
}

.floating-dots span {
    position: absolute;
    display: block;
    width: 20px;
    height: 20px;
    background: linear-gradient(135deg, #5e72e4, #e94560);
    border-radius: 50%;
    opacity: 0.1;
    animation: floatUp 15s linear infinite;
}

.floating-dots span:nth-child(1) { left: 5%; animation-delay: 0s; width: 15px; height: 15px; }
.floating-dots span:nth-child(2) { left: 15%; animation-delay: 1s; width: 12px; height: 12px; }
.floating-dots span:nth-child(3) { left: 25%; animation-delay: 2s; width: 18px; height: 18px; }
.floating-dots span:nth-child(4) { left: 35%; animation-delay: 3s; width: 10px; height: 10px; }
.floating-dots span:nth-child(5) { left: 45%; animation-delay: 4s; width: 22px; height: 22px; }
.floating-dots span:nth-child(6) { left: 55%; animation-delay: 5s; width: 14px; height: 14px; }
.floating-dots span:nth-child(7) { left: 65%; animation-delay: 6s; width: 16px; height: 16px; }
.floating-dots span:nth-child(8) { left: 75%; animation-delay: 7s; width: 20px; height: 20px; }
.floating-dots span:nth-child(9) { left: 85%; animation-delay: 8s; width: 11px; height: 11px; }
.floating-dots span:nth-child(10) { left: 95%; animation-delay: 9s; width: 25px; height: 25px; }
.floating-dots span:nth-child(11) { left: 10%; animation-delay: 10s; width: 13px; height: 13px; }
.floating-dots span:nth-child(12) { left: 30%; animation-delay: 11s; width: 17px; height: 17px; }
.floating-dots span:nth-child(13) { left: 50%; animation-delay: 12s; width: 19px; height: 19px; }
.floating-dots span:nth-child(14) { left: 70%; animation-delay: 13s; width: 15px; height: 15px; }
.floating-dots span:nth-child(15) { left: 90%; animation-delay: 14s; width: 21px; height: 21px; }

@keyframes floatUp {
    0% {
        bottom: -100px;
        transform: translateX(0);
    }
    25% {
        transform: translateX(-30px);
    }
    50% {
        transform: translateX(30px);
    }
    75% {
        transform: translateX(-15px);
    }
    100% {
        bottom: calc(100% + 100px);
        transform: translateX(0);
    }
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
    color: var(--text-secondary);
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

/* Input Styles - Adaptive */
.stTextArea textarea, .stTextInput input {
    background: var(--input-bg) !important;
    border: 2px solid var(--input-border) !important;
    border-radius: 12px !important;
    color: var(--text-primary) !important;
    font-size: 15px !important;
    padding: 12px 16px !important;
    transition: all 0.3s ease !important;
    backdrop-filter: blur(10px) !important;
}

.stTextArea textarea::placeholder, .stTextInput input::placeholder {
    color: var(--text-secondary) !important;
    opacity: 0.7 !important;
}

.stTextArea textarea:focus, .stTextInput input:focus {
    border-color: rgba(94, 114, 228, 0.6) !important;
    box-shadow: 0 0 0 3px rgba(94, 114, 228, 0.1) !important;
    background: var(--input-bg) !important;
}

/* Button Styles */
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

.stButton > button:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(94, 114, 228, 0.4);
}

/* Primary Button */
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
    background: var(--card-bg) !important;
    border: 2px solid var(--border-color) !important;
    box-shadow: 0 2px 10px var(--shadow-medium) !important;
}

/* Checkbox Styles */
.stCheckbox label {
    color: var(--text-primary) !important;
    font-weight: 500;
}

/* DataFrame Container */
.dataframe-container {
    background: var(--card-bg);
    border: 1px solid var(--border-color);
    border-radius: 16px;
    padding: 20px;
    backdrop-filter: blur(10px);
    box-shadow: 0 10px 40px var(--shadow-medium);
    margin: 20px 0;
    animation: slideUp 0.6s ease-out;
}

@keyframes slideUp {
    from { opacity: 0; transform: translateY(20px); }
    to { opacity: 1; transform: translateY(0); }
}

/* Progress Bar */
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

/* Sidebar Styles - Adaptive */
.css-1d391kg, [data-testid="stSidebar"] {
    background: var(--sidebar-bg) !important;
    backdrop-filter: blur(20px);
    border-right: 1px solid var(--border-color) !important;
}

.css-1d391kg .stMarkdown, [data-testid="stSidebar"] .stMarkdown {
    color: var(--text-primary) !important;
}

/* Metrics Cards - Adaptive */
.metric-card {
    background: var(--card-bg-alt);
    border: 1px solid var(--border-light);
    border-radius: 16px;
    padding: 20px;
    text-align: center;
    transition: all 0.3s ease;
    box-shadow: 0 4px 12px var(--shadow-light);
}

.metric-card:hover {
    transform: translateY(-5px);
    box-shadow: 0 10px 30px var(--shadow-medium);
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
    color: var(--text-secondary);
    font-size: 14px;
    font-weight: 500;
    margin-top: 8px;
}

/* Text Color Overrides for Consistency */
.stMarkdown, .stText, p, h1, h2, h3, h4, h5, h6 {
    color: var(--text-primary) !important;
}

.stCaption {
    color: var(--text-secondary) !important;
}

/* Alert Styles */
.stAlert {
    background: var(--card-bg) !important;
    border: 1px solid var(--border-color) !important;
    border-radius: 12px !important;
    color: var(--text-primary) !important;
    backdrop-filter: blur(10px);
}

/* Footer */
.footer-section {
    margin-top: 60px;
    padding: 30px;
    background: var(--card-bg);
    border-radius: 20px;
    border: 1px solid var(--border-color);
    text-align: center;
    color: var(--text-secondary);
}

.footer-credit {
    color: var(--text-secondary);
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

/* Custom scrollbar - Adaptive */
::-webkit-scrollbar {
    width: 10px;
    height: 10px;
}

::-webkit-scrollbar-track {
    background: var(--card-bg);
}

::-webkit-scrollbar-thumb {
    background: linear-gradient(135deg, #5e72e4, #e94560);
    border-radius: 5px;
}

::-webkit-scrollbar-thumb:hover {
    background: linear-gradient(135deg, #e94560, #5e72e4);
}

/* Tabs - Adaptive */
.stTabs [data-baseweb="tab-list"] {
    gap: 8px;
    background: transparent;
}

.stTabs [data-baseweb="tab"] {
    background-color: var(--card-bg) !important;
    border: 1px solid var(--border-color) !important;
    border-radius: 8px !important;
    color: var(--text-primary) !important;
}

.stTabs [aria-selected="true"] {
    background-color: var(--input-bg) !important;
    border-color: #5e72e4 !important;
    color: var(--text-primary) !important;
}

/* DataFrame styling */
[data-testid="stDataFrame"], [data-testid="stTable"] {
    background: var(--card-bg) !important;
    color: var(--text-primary) !important;
}

/* Ensure all text elements use adaptive colors */
.stSelectbox label, .stSlider label, .stTextArea label, .stTextInput label {
    color: var(--text-primary) !important;
}

/* Info/Success/Warning Messages */
.stInfo, .stSuccess, .stWarning, .stError {
    background: var(--card-bg) !important;
    border: 1px solid var(--border-color) !important;
    color: var(--text-primary) !important;
}

.stSpinner > div {
    border-color: #5e72e4 !important;
}

hr {
    border: 0;
    height: 1px;
    background: var(--border-color);
    margin: 20px 0;
}
</style>
""", unsafe_allow_html=True)

  # Hero Section with Enhanced Background Animation
    st.markdown("""
<div class="hero-section">
    <div class="geometric-bg">
        <div class="geo-shape geo-shape-1"></div>
        <div class="geo-shape geo-shape-2"></div>
        <div class="geo-shape geo-shape-3"></div>
        <div class="geo-shape geo-shape-4"></div>
        <div class="geo-shape geo-shape-5"></div>
        <div class="geo-shape geo-shape-6"></div>
    </div>
    <div class="floating-dots">
        <span></span><span></span><span></span><span></span><span></span>
        <span></span><span></span><span></span><span></span><span></span>
        <span></span><span></span><span></span><span></span><span></span>
    </div>
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
    
    # Add logout button in sidebar
    with st.sidebar:
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.authenticated = False
            st.rerun()
        st.markdown("---")

    # Session / networking (UNCHANGED from original)
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
        s.headers.update({"User-Agent": "DOI-Navigator/1.1 (mailto:your.email@domain)"})
        return s

    def _download_excel(url: str) -> io.BytesIO:
        r = _get_session().get(url, timeout=60)
        r.raise_for_status()
        return io.BytesIO(r.content)

    # DOI normalization
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

    # Readers
    def read_jcr(io_obj) -> pd.DataFrame:
        xls = pd.ExcelFile(io_obj, engine="openpyxl")
        df = pd.read_excel(xls, xls.sheet_names[0])
        if df.shape[1] < 17:
            raise ValueError("JCR file has fewer than 17 columns; cannot map B/M/Q reliably.")
        journal_col = df.columns[1]
        impact_col = df.columns[12]
        quartile_col = df.columns[16]
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

    # Cache heavy loads
    @st.cache_data(show_spinner=True, ttl=60*60*12)
    def load_jcr_cached(url: str) -> pd.DataFrame:
        return read_jcr(_download_excel(url))

    @st.cache_data(show_spinner=True, ttl=60*60*12)
    def load_scopus_cached(url: str) -> pd.DataFrame:
        return read_scopus_titles(_download_excel(url))

    # Metadata fetchers
    def _crossref_fetch_raw(doi: str, timeout: float = 15.0) -> dict:
        url = f"https://api.crossref.org/works/{doi}"
        r = _get_session().get(url, timeout=timeout)
        r.raise_for_status()
        return r.json().get("message", {})

    def _doi_content_negotiation(doi: str, timeout: float = 15.0) -> dict:
        url = f"https://doi.org/{doi}"
        headers = {"Accept": "application/vnd.citationstyles.csl+json"}
        r = _get_session().get(url, headers=headers, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        return r.json()

    def _format_authors(msg: dict) -> str:
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
        title = _first(msg.get("title"))
        journal = _first(msg.get("container-title"))
        publisher = msg.get("publisher", "") or msg.get("publisher-name", "")
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
            "Citations (Crossref)": cites,
        }

    @st.cache_data(show_spinner=False, ttl=60*60*24*7)
    def fetch_metadata_unified(doi: str) -> dict:
        try:
            msg = _crossref_fetch_raw(doi)
            data = _extract_fields_generic(msg, source="crossref")
            if data.get("Title") or data.get("Journal"):
                return data
        except Exception:
            pass

        try:
            csl = _doi_content_negotiation(doi)
            data = _extract_fields_generic(csl, source="csl")
            if data.get("Title") or data.get("Journal"):
                return data
        except Exception as e:
            return {"error": f"Not found via Crossref; DOI content negotiation also failed: {e}"}

        return {"error": "Metadata not available from Crossref or DOI content negotiation."}

    def fetch_parallel(dois: list[str], max_workers: int = 12) -> list[dict]:
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

    # Batch merge with RapidFuzz
    def merge_enrich_fast(df: pd.DataFrame, jcr: pd.DataFrame, scopus: pd.DataFrame, cfg: MatchCfg) -> pd.DataFrame:
        if df.empty:
            return df
        q = df["Journal"].fillna("").astype(str).map(normalize_journal).tolist()

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
        st.markdown('<h2 style="color: var(--text-primary); margin-bottom: 20px;">⚙️ Configuration</h2>', unsafe_allow_html=True)
        
        st.markdown('<h3 style="color: var(--text-primary);">Matching Settings</h3>', unsafe_allow_html=True)
        min_score = st.slider("🎯 Fuzzy Match Threshold", 60, 95, 80, 
                              help="Higher score = stricter matching. Default: 80")
        st.caption("💡 Tip: Start with default (80) for balanced accuracy")
        
        wos_if_jcr = st.checkbox("📊 Auto-mark WoS if in JCR", value=True,
                                 help="Automatically mark as indexed in Web of Science if found in JCR database")
        scopus_exact = st.checkbox("🔍 Scopus exact match first", value=True,
                                  help="Try exact normalized matching before fuzzy matching for Scopus")
        st.markdown('<hr>', unsafe_allow_html=True)
        
        st.markdown('<h3 style="color: var(--text-primary);">Performance</h3>', unsafe_allow_html=True)
        fast_workers = st.slider("⚡ Parallel requests", 2, 16, 12,
                                 help="Number of concurrent API requests")
        st.markdown('<hr>', unsafe_allow_html=True)
        
        st.markdown('<h3 style="color: var(--text-primary);">📈 Database Stats</h3>', unsafe_allow_html=True)
        st.markdown(f'<div class="metric-card"><div class="metric-value">29,270</div><div class="metric-label">JCR Journals Scanned</div></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="metric-card"><div class="metric-value">47,838</div><div class="metric-label">Scopus Journals Scanned</div></div>', unsafe_allow_html=True)

    cfg = MatchCfg(min_score=min_score, wos_if_missing=wos_if_jcr, scopus_exact_first=scopus_exact)

    # Main panel
    st.markdown('<h3 style="color: var(--text-primary);">🔍 Input DOIs</h3>', unsafe_allow_html=True)

    tab1 = st.tabs(["📋 Paste DOIs"])[0]
    with tab1:
        dois_text = st.text_area(
            "Enter one DOI per line",
            height=200,
            placeholder="10.1016/j.arr.2025.102847\n10.1016/j.arr.2025.102834\n10.17179/excli2014-541\nhttps://doi.org/10.1038/nature12373",
            help="You can paste DOIs with or without https://doi.org/ prefix"
        )
    st.markdown('<hr>', unsafe_allow_html=True)

    # Action Buttons
    st.markdown('<h3 style="color: var(--text-primary);">Action Buttons</h3>', unsafe_allow_html=True)
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        fetch = st.button("🚀 Fetch Metadata", type="primary", use_container_width=True)
    with col2:
        if st.button("🗑️ Clear All", use_container_width=True):
            if 'jcr_df' in st.session_state:
                del st.session_state.jcr_df
            if 'sc_df' in st.session_state:
                del st.session_state.sc_df
            st.rerun()
    with col3:
        raw_lines = [d for d in dois_text.splitlines() if d.strip()]
        dois = list(dict.fromkeys(normalize_doi_input(d) for d in raw_lines))
        st.markdown(f'<div class="metric-card"><div class="metric-value">{len(dois)}</div><div class="metric-label">DOIs</div></div>', unsafe_allow_html=True)
    st.markdown('<hr>', unsafe_allow_html=True)

    results_df = None

    def load_jcr_and_scopus():
        jcr_url = JCR_FALLBACK_URL
        scp_url = SCOPUS_FALLBACK_URL
        
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
                
                st.session_state.jcr_df = jcr
                st.session_state.sc_df = scp
                
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
            
            st.markdown('<h3 style="color: var(--text-primary);">🔍 Fetching Metadata</h3>', unsafe_allow_html=True)
            
            rows = fetch_parallel(dois, max_workers=fast_workers)
            base_df = pd.DataFrame(rows)
            
            if not base_df.empty:
                with st.spinner("📄 Matching with JCR and Scopus databases..."):
                    results_df = merge_enrich_fast(base_df, jcr_df, sc_df, cfg)
                st.success(f"✅ Successfully processed {len(results_df)} papers!")
            st.markdown('<hr>', unsafe_allow_html=True)

    # Display & Download
    if results_df is not None and not results_df.empty:
        results_df.index = pd.RangeIndex(start=1, stop=len(results_df) + 1, name="S.No.")
        
        st.markdown('<h3 style="color: var(--text-primary);">📊 Analysis Summary</h3>', unsafe_allow_html=True)
        
        col1, col2, col3, col4 = st.columns(4)
        
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
        st.markdown('<h3 style="color: var(--text-primary);">🔓 Results Table</h3>', unsafe_allow_html=True)
        
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
        st.markdown('<h3 style="color: var(--text-primary);">💾 Export Options</h3>', unsafe_allow_html=True)
        
        export_df = results_df.copy()
        export_df["Indexed in Scopus"] = export_df["Indexed in Scopus"].map(
            lambda v: "Yes" if v is True else "No" if v is False else ""
        )
        export_df["Indexed in Web of Science"] = export_df["Indexed in Web of Science"].map(
            lambda v: "Yes" if v is True else "No" if v is False else ""
        )
        
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
        st.markdown("""
        <div style="text-align: center; padding: 40px;">
            <h2 style="color: var(--text-primary); margin-bottom: 20px;">👋 Welcome to DOI Navigator</h2>
            <p style="color: var(--text-secondary); font-size: 16px; line-height: 1.6;">
                Enter DOIs above and click <strong>Fetch Metadata</strong> to extract comprehensive paper information.<br>
                The app automatically matches papers with JCR and Scopus databases for impact factors and indexing status.
            </p>
            <div style="margin-top: 30px; display: flex; justify-content: center; gap: 40px;">
                <div style="text-align: center;">
                    <div style="font-size: 32px; margin-bottom: 10px;">📚</div>
                    <div style="color: var(--text-secondary); font-size: 14px;">Multi-DOI Support</div>
                </div>
                <div style="text-align: center;">
                    <div style="font-size: 32px; margin-bottom: 10px;">⚡</div>
                    <div style="color: var(--text-secondary); font-size: 14px;">Fast Processing</div>
                </div>
                <div style="text-align: center;">
                    <div style="font-size: 32px; margin-bottom: 10px;">🎯</div>
                    <div style="color: var(--text-secondary); font-size: 14px;">Accurate Matching</div>
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

# --------------------------------------------------------------------
# MAIN ENTRY POINT WITH AUTHENTICATION (UNCHANGED)
# --------------------------------------------------------------------
def main():
    """Main application entry point without login/signup"""
    run_original_app()

if __name__ == "__main__":
    main()
