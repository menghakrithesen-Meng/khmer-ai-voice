import streamlit as st
import asyncio
import edge_tts
from pydub import AudioSegment, effects
import tempfile
import os
import json
import datetime
import time
import string
import random
import io
import re
import uuid
import extra_streamlit_components as stx

# ==========================================
# 0. CONFIG & SETUP
# ==========================================
st.set_page_config(page_title="Khmer AI Voice Pro", page_icon="🎙️", layout="wide")

KEYS_FILE = "web_keys.json"
PRESETS_FILE = "user_presets.json"
ACTIVE_FILE = "active_sessions.json"

# 🎨 CUSTOM CSS
st.markdown("""
<style>
    .stApp { background: linear-gradient(to right, #0f172a, #1e293b); color: white; }
    section[data-testid="stSidebar"] { background-color: #111827; border-right: 1px solid #374151; }
    /* Hide Number Input Steppers */
    button[data-testid="stNumberInputStepDown"], button[data-testid="stNumberInputStepUp"] { display: none; }
    div[data-testid="stNumberInput"] input { text-align: center; }
    /* Small Preset Buttons */
    div[data-testid="column"] button { padding: 0px 2px !important; font-size: 11px !important; min-height: 32px !important; width: 100%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    /* Active Button Color */
    div[data-testid="column"] button[kind="primary"] { border-color: #ff4b4b !important; background-color: #ff4b4b !important; color: white !important; }
    /* SRT Box */
    .srt-box { background: #1e293b; border: 1px solid #334155; border-radius: 6px; padding: 10px; margin-bottom: 5px; border-left: 4px solid #8b5cf6; }
    .srt-box.slot-1 { border-left-color: #f97316 !important; } 
    .srt-box.slot-2 { border-left-color: #22c55e !important; } 
    .srt-box.slot-3 { border-left-color: #3b82f6 !important; } 
    .srt-box.slot-4 { border-left-color: #e11d48 !important; } 
    .srt-box.slot-5 { border-left-color: #a855f7 !important; } 
    .srt-box.slot-6 { border-left-color: #facc15 !important; } 
    .preset-tag { display: inline-block; padding: 2px 6px; border-radius: 999px; font-size: 11px; background: #4b5563; margin-left: 6px; color: #e5e7eb; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 1. FUNCTIONS
# ==========================================
def load_json(path):
    if not os.path.exists(path): return {}
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except: return {}

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f: json.dump(data, f, indent=2, ensure_ascii=False)
    except: pass

# --- ACTIVE SESSION MANAGEMENT ---
def load_active_sessions():
    """Load fresh data every time to ensure Real-Time check"""
    return load_json(ACTIVE_FILE)

def get_server_token(user_key):
    """Get the current valid token for this key from JSON"""
    active = load_active_sessions()
    return active.get(user_key)

def set_new_session(user_key):
    """Invalidate old sessions and create a new one"""
    new_token = str(uuid.uuid4())
    active = load_active_sessions()
    active[user_key] = new_token
    save_json(ACTIVE_FILE, active)
    return new_token

def check_access_key(user_key):
    keys_db = load_json(KEYS_FILE)
    if user_key not in keys_db: return "Invalid Key", 0
    k_data = keys_db[user_key]
    if k_data.get("status") != "active": return "Key Disabled", 0
    if not k_data.get("activated_date"):
        k_data["activated_date"] = str(datetime.date.today())
        save_json(KEYS_FILE, keys_db)
    start = datetime.date.fromisoformat(k_data["activated_date"])
    exp = start + datetime.timedelta(days=k_data["duration_days"])
    left = (exp - datetime.date.today()).days
    if left < 0: return "Expired", 0
    return "Valid", left

# --- PRESETS & AUDIO ENGINE ---
def save_user_preset(user_key, slot, data, name):
    db = load_json(PRESETS_FILE)
    if user_key not in db: db[user_key] = {}
    data["name"] = name if name else f"{slot}"
    db[user_key][str(slot)] = data
    save_json(PRESETS_FILE, db)

def get_user_preset(user_key, slot):
    db = load_json(PRESETS_FILE)
    return db.get(user_key, {}).get(str(slot), None)

def apply_preset_to_line(user_key, line_index, slot_id):
    pd = get_user_preset(user_key, slot_id)
    if not pd: return
    st.session_state.line_settings[line_index] = {
        "voice": pd["voice"], "rate": pd["rate"], "pitch": pd["pitch"], "slot": slot_id,
    }

async def gen_edge(text, voice, rate, pitch):
    file_path = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3").name
    communicate = edge_tts.Communicate(text, voice, rate=f"{rate:+d}%" if rate!=0 else "+0%", pitch=f"{pitch:+d}Hz" if pitch!=0 else "+0Hz")
    await communicate.save(file_path)
    return file_path

def process_audio(file_path, pad_ms):
    try:
        seg = AudioSegment.from_file(file_path)
        pad = AudioSegment.silent(duration=pad_ms)
        return pad + effects.normalize(seg) + pad
    except: return AudioSegment.from_file(file_path)

def srt_time_to_ms(time_str):
    try:
        start, _ = time_str.split(" --> ")
        h, m, s = start.replace(",", ".").split(":")
        return int(float(h)*3600000 + float(m)*60000 + float(s)*1000)
    except: return 0

def parse_srt(content):
    subs = []
    blocks = re.split(r"\n\s*\n", content.strip())
    for b in blocks:
        lines = b.strip().split("\n")
        if len(lines) >= 3:
            time_idx = 1
            if "-->" not in lines[1]:
                for i, l in enumerate(lines):
                    if "-->" in l: time_idx = i; break
            text = " ".join(lines[time_idx + 1 :])
            text = re.sub(r"<[^>]+>", "", text)
            if text.strip(): subs.append({"start": srt_time_to_ms(lines[time_idx]), "text": text})
    return subs

# ==========================================
# 3. AUTH FLOW (1 KEY 1 BROWSER - STRICT)
# ==========================================
st.title("🇰🇭 Khmer AI Voice Pro (Edge)")
cm = stx.CookieManager(key="main_cm")

# --- 3.1: COOKIE RETRY LOGIC (FIX REFRESH ISSUE) ---
if "retry_count" not in st.session_state:
    st.session_state.retry_count = 0

cookie_key = cm.get("auth_key")
cookie_token = cm.get("session_token")

# Retry Mechanism: If no cookie found, wait and rerun once
if not cookie_key and st.session_state.retry_count < 1:
    time.sleep(0.5)
    st.session_state.retry_count += 1
    st.rerun()

if cookie_key:
    st.session_state.retry_count = 0

# --- 3.2: AUTH CHECK LOGIC ---
if "auth" not in st.session_state:
    st.session_state.auth = False

# Auto-Login Attempt
if not st.session_state.auth and cookie_key and cookie_token:
    status, days = check_access_key(cookie_key)
    server_token = get_server_token(cookie_key)
    
    # Check if this browser holds the valid token
    if status == "Valid" and cookie_token == server_token:
        st.session_state.auth = True
        st.session_state.ukey = cookie_key
        st.session_state.days = days
        st.session_state.my_token = cookie_token # Keep track of my token
    else:
        # Token mismatch = Logged out
        pass

# --- 3.3: LOGIN UI ---
if not st.session_state.auth:
    if st.session_state.retry_count > 0:
        st.spinner("Checking session...")
        st.stop()

    st.markdown("##### 🔐 Login Required")
    with st.form("login_form"):
        key_input = st.text_input("🔑 Access Key", type="password")
        remember = st.checkbox("Remember me", value=True)
        submitted = st.form_submit_button("Login", type="primary")

    if submitted:
        status, days = check_access_key(key_input)
        if status != "Valid":
            st.error(status)
            st.stop()
            
        # FORCE LOGIN: Create NEW token (Kicks out everyone else)
        new_token = set_new_session(key_input)
        
        st.session_state.auth = True
        st.session_state.ukey = key_input
        st.session_state.days = days
        st.session_state.my_token = new_token
        st.session_state.retry_count = 0
        
        if remember:
            exp = datetime.datetime.now() + datetime.timedelta(days=30)
            cm.set("auth_key", key_input, expires_at=exp, key="s_k")
            cm.set("session_token", new_token, expires_at=exp, key="s_t")
        
        st.success("Login Success!")
        time.sleep(0.5)
        st.rerun()
    
    st.stop()

# ==========================================
# 4. REAL-TIME SESSION ENFORCEMENT
# ==========================================
# នេះជាកន្លែងសំខាន់! ទោះបីជា Login ជាប់ហើយក៏ដោយ
# ត្រូវតែ Check Token ជាមួយ Server ជានិច្ច
if st.session_state.auth:
    # 1. Read fresh data from JSON
    current_valid_token = get_server_token(st.session_state.ukey)
    
    # 2. Compare with MY token
    my_token = st.session_state.get("my_token")
    
    # 3. If they don't match -> KICK OUT IMMEDIATELY
    if current_valid_token != my_token:
        st.error("🚨 Session Expired! You have logged in on another browser.")
        st.warning("Please refresh or login again.")
        
        # Clear local session
        st.session_state.auth = False
        st.session_state.clear()
        
        # Delete cookies
        cm.delete("auth_key")
        cm.delete("session_token")
        
        # Stop app execution
        time.sleep(3)
        st.rerun()

# ==========================================
# 5. MAIN APP CONTENT (Only runs if Token is Valid)
# ==========================================

VOICES = {
    "Sreymom (Khmer)": "km-KH-SreymomNeural",
    "Piseth (Khmer)": "km-KH-PisethNeural",
    "Emma (EN Multi)": "en-US-EmmaMultilingualNeural",
    "Xiaoxiao (Chinese)": "zh-CN-XiaoxiaoNeural",
}

with st.sidebar:
    st.success(f"✅ Active: {st.session_state.days} Days")
    if st.button("Logout", type="primary"):
        st.session_state.clear()
        cm.delete("auth_key")
        cm.delete("session_token")
        st.rerun()
    
    st.divider()
    st.subheader("⚙️ Settings")
    
    if "g_voice" not in st.session_state: st.session_state.g_voice = "Sreymom (Khmer)"
    if "g_rate" not in st.session_state: st.session_state.g_rate = 0
    if "g_pitch" not in st.session_state: st.session_state.g_pitch = 0
    
    v_sel = st.selectbox("Voice", list(VOICES.keys()), index=list(VOICES.keys()).index(st.session_state.g_voice))
    r_sel = st.slider("Speed", -50, 50, value=st.session_state.g_rate)
    p_sel = st.slider("Pitch", -50, 50, value=st.session_state.g_pitch)
    
    st.session_state.g_voice = v_sel
    st.session_state.g_rate = r_sel
    st.session_state.g_pitch = p_sel

tab1, tab2 = st.tabs(["📝 Text Mode", "🎬 SRT Multi-Speaker"])

with tab1:
    txt = st.text_area("Input Text...", height=150)
    if st.button("Generate Audio 🎵", type="primary"):
        if txt:
            with st.spinner("Generating..."):
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    raw = loop.run_until_complete(gen_edge(txt, VOICES[v_sel], r_sel, p_sel))
                    final = process_audio(raw, 80)
                    buf = io.BytesIO()
                    final.export(buf, format="mp3")
                    st.audio(buf)
                except Exception as e: st.error(str(e))

with tab2:
    st.info("SRT Mode")
    srt_file = st.file_uploader("Upload SRT", type="srt")
    # ... (SRT Logic can be pasted here from previous code if needed) ...
