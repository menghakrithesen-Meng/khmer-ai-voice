import streamlit as st
import asyncio
import edge_tts
from pydub import AudioSegment, effects
import tempfile
import os
import json
import datetime
import random
import string
import io
import extra_streamlit_components as stx 

# ==========================================
# CONFIG & SETUP
# ==========================================
st.set_page_config(page_title="Khmer AI Voice (Edge)", page_icon="🎙️", layout="wide")

KEYS_FILE = "web_keys.json"
PRESETS_FILE = "user_presets.json"

# 🎨 CUSTOM CSS
st.markdown("""
<style>
    .stApp { background: linear-gradient(to right, #0f172a, #1e293b); color: white; }
    section[data-testid="stSidebar"] { background-color: #111827; border-right: 1px solid #374151; }
    .stButton > button { border-radius: 6px; font-size: 13px; padding: 4px 10px; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# SHARED FUNCTIONS
# ==========================================
def load_json(path):
    if not os.path.exists(path): return {}
    try: with open(path, "r") as f: return json.load(f)
    except: return {}

def save_json(path, data):
    try: with open(path, "w") as f: json.dump(data, f, indent=2)
    except: pass

def get_cookie_manager():
    if 'cookie_manager' not in st.session_state: st.session_state.cookie_manager = stx.CookieManager()
    return st.session_state.cookie_manager

def check_access_key(user_key):
    keys_db = load_json(KEYS_FILE)
    if user_key not in keys_db: return "Invalid Key", 0
    k_data = keys_db[user_key]
    if k_data["status"] != "active": return "Key Disabled", 0
    
    if not k_data.get("activated_date"):
        k_data["activated_date"] = str(datetime.date.today())
        save_json(KEYS_FILE, keys_db)
    
    start = datetime.date.fromisoformat(k_data["activated_date"])
    exp = start + datetime.timedelta(days=k_data["duration_days"])
    left = (exp - datetime.date.today()).days
    return ("Expired", 0) if left < 0 else ("Valid", left)

def save_preset(user_key, slot, settings, name):
    data = load_json(PRESETS_FILE)
    if user_key not in data: data[user_key] = {}
    settings['name'] = name if name else f"S{slot}"
    data[user_key][str(slot)] = settings
    save_json(PRESETS_FILE, data)

def get_preset(user_key, slot):
    data = load_json(PRESETS_FILE)
    return data.get(user_key, {}).get(str(slot), None)

async def generate_edge_audio(text, voice, rate, pitch):
    file_path = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3").name
    rate_str = f"{rate:+d}%" if rate != 0 else "+0%"
    pitch_str = f"{pitch:+d}Hz" if pitch != 0 else "+0Hz"
    communicate = edge_tts.Communicate(text, voice, rate=rate_str, pitch=pitch_str)
    await communicate.save(file_path)
    return file_path

def add_effects(file_path, pad_ms):
    try:
        seg = AudioSegment.from_file(file_path)
        pad = AudioSegment.silent(duration=pad_ms)
        return pad + effects.normalize(seg) + pad
    except: return AudioSegment.from_file(file_path)

# ==========================================
# MAIN UI
# ==========================================
# ADMIN PANEL
if st.query_params.get("view") == "admin":
    st.title("🔐 Admin Panel")
    pwd = st.text_input("Password", type="password")
    if pwd == "admin123":
        days = st.number_input("Days", 30)
        if st.button("Create Key"):
            key = "KHM-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            data = load_json(KEYS_FILE)
            data[key] = {"duration_days": days, "activated_date": None, "status": "active"}
            save_json(KEYS_FILE, data)
            st.success(f"Key: {key}")
        st.json(load_json(KEYS_FILE))
    st.stop()

# LOGIN
st.title("🇰🇭 Khmer AI Voice (Edge)")
cm = get_cookie_manager()
if 'auth' not in st.session_state:
    st.session_state.auth = False
    cookie_key = cm.get("auth_key")
    if cookie_key:
        s, d = check_access_key(cookie_key)
        if s == "Valid": st.session_state.auth = True; st.session_state.ukey = cookie_key; st.session_state.days = d

if not st.session_state.auth:
    key = st.text_input("🔑 Access Key", type="password")
    if st.button("Login"):
        s, d = check_access_key(key)
        if s == "Valid":
            st.session_state.auth = True; st.session_state.ukey = key; st.session_state.days = d
            cm.set("auth_key", key, expires_at=datetime.datetime.now() + datetime.timedelta(days=30))
            st.rerun()
        else: st.error(s)
    st.stop()

# APP
with st.sidebar:
    st.success(f"✅ Active: {st.session_state.days} Days")
    if st.button("Logout"): cm.delete("auth_key"); st.session_state.clear(); st.rerun()
    st.divider()
    
    voice_options = {
        "Sreymom (Khmer)": "km-KH-SreymomNeural",
        "Piseth (Khmer)": "km-KH-PisethNeural",
        "Emma (English)": "en-US-EmmaMultilingualNeural"
    }
    
    if "v_name" not in st.session_state: st.session_state.v_name = "Sreymom (Khmer)"
    if "rate" not in st.session_state: st.session_state.rate = 0
    if "pitch" not in st.session_state: st.session_state.pitch = 0
    
    v_name = st.selectbox("Voice", list(voice_options.keys()), key="v_name")
    rate = st.slider("Speed", -50, 50, key="rate")
    pitch = st.slider("Pitch", -50, 50, key="pitch")
    pad = st.number_input("Padding (ms)", value=80)

    st.divider()
    for i in range(1, 4):
        col1, col2 = st.columns([3, 1])
        p = get_preset(st.session_state.ukey, i)
        name = p['name'] if p else f"Slot {i}"
        if col1.button(f"📂 {name}", key=f"l{i}", use_container_width=True):
            if p:
                st.session_state.v_name = p['v_name']
                st.session_state.rate = p['rate']
                st.session_state.pitch = p['pitch']
                st.rerun()
        if col2.button("💾", key=f"s{i}"):
            save_preset(st.session_state.ukey, i, {"v_name":v_name, "rate":rate, "pitch":pitch}, f"Preset {i}")
            st.toast("Saved!")

text = st.text_area("បញ្ចូលអត្ថបទ...", height=150)
if st.button("Generate Audio 🎵", type="primary", use_container_width=True):
    if text:
        with st.spinner("Generating..."):
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                file_path = loop.run_until_complete(generate_edge_audio(text, voice_options[v_name], rate, pitch))
                final_audio = add_effects(file_path, pad)
                buf = io.BytesIO()
                final_audio.export(buf, format="mp3")
                st.audio(buf)
                st.download_button("Download MP3", buf, "audio.mp3", "audio/mp3", use_container_width=True)
            except Exception as e: st.error(f"Error: {e}")
