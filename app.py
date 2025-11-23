import streamlit as st
import asyncio
import edge_tts
from pydub import AudioSegment, effects
import tempfile
import os
import json
import datetime
import uuid
import time
import string
import random
import io
import extra_streamlit_components as stx 

# ==========================================
# 0. CONFIG & SETUP
# ==========================================
st.set_page_config(page_title="Khmer AI Voice Pro", page_icon="🎙️", layout="wide")

# File Paths
KEYS_FILE = "web_keys.json"
PRESETS_FILE = "user_presets.json"

# 🎨 CUSTOM CSS
st.markdown("""
<style>
    .stApp { background: linear-gradient(to right, #0f172a, #1e293b); color: white; }
    section[data-testid="stSidebar"] { background-color: #111827; border-right: 1px solid #374151; }
    .stButton > button { border-radius: 6px; font-size: 13px; padding: 4px 10px; }
    div[data-testid="stExpander"] { background-color: #1e293b; border-radius: 6px; margin-bottom: 10px; }
    .srt-box { background: #1e293b; border: 1px solid #334155; border-radius: 6px; padding: 8px; margin-bottom: 2px; border-left: 3px solid #8b5cf6; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 1. DATABASE & HELPER FUNCTIONS
# ==========================================
def load_json(path):
    if not os.path.exists(path): return {}
    try: with open(path, "r") as f: return json.load(f)
    except: return {}

def save_json(path, data):
    try: with open(path, "w") as f: json.dump(data, f, indent=2)
    except: pass

# --- DEVICE ID & COOKIES ---
def get_cookie_manager():
    if 'cookie_manager' not in st.session_state: st.session_state.cookie_manager = stx.CookieManager()
    return st.session_state.cookie_manager

def get_device_id(cm):
    did = cm.get("device_uuid")
    if not did:
        did = str(uuid.uuid4())
        cm.set("device_uuid", did, key="set_device_uuid", expires_at=datetime.datetime.now() + datetime.timedelta(days=365))
        time.sleep(0.1)
    return did

# --- KEY VALIDATION ---
def check_access_key(user_key, device_id):
    keys_db = load_json(KEYS_FILE)
    if user_key not in keys_db: return "Invalid Key", 0
    k_data = keys_db[user_key]
    if k_data["status"] != "active": return "Key Disabled", 0

    # Bind Device if new
    if not k_data.get("bound_device"):
        k_data["bound_device"] = device_id
        k_data["activated_date"] = str(datetime.date.today())
        save_json(KEYS_FILE, keys_db)
        return "Valid", k_data["duration_days"]
    
    # Check Device Lock
    if k_data["bound_device"] != device_id: return "Device Mismatch (Contact Admin)", 0

    # Check Expiry
    start = datetime.date.fromisoformat(k_data["activated_date"])
    exp = start + datetime.timedelta(days=k_data["duration_days"])
    left = (exp - datetime.date.today()).days
    return ("Expired", 0) if left < 0 else ("Valid", left)

# --- PRESETS ---
def save_preset(user_key, slot, settings, name):
    data = load_json(PRESETS_FILE)
    if user_key not in data: data[user_key] = {}
    settings['name'] = name if name else f"S{slot}"
    data[user_key][str(slot)] = settings
    save_json(PRESETS_FILE, data)

def get_preset(user_key, slot):
    data = load_json(PRESETS_FILE)
    return data.get(user_key, {}).get(str(slot), None)

# ==========================================
# 2. AUDIO ENGINE (EDGE-TTS ONLY)
# ==========================================
async def generate_audio_edge(text, voice, rate, pitch):
    file_path = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3").name
    rate_str = f"{rate:+d}%" if rate != 0 else "+0%"
    pitch_str = f"{pitch:+d}Hz" if pitch != 0 else "+0Hz"
    
    communicate = edge_tts.Communicate(text, voice, rate=rate_str, pitch=pitch_str)
    await communicate.save(file_path)
    return file_path

def add_audio_effects(file_path, pad_ms):
    try:
        seg = AudioSegment.from_file(file_path)
        pad = AudioSegment.silent(duration=pad_ms)
        return pad + effects.normalize(seg) + pad
    except: return AudioSegment.from_file(file_path)

# ==========================================
# 3. ADMIN LOGIC
# ==========================================
def admin_generate_key(days):
    chars = string.ascii_uppercase + string.digits
    key = "KHM-" + ''.join(random.choices(chars, k=8))
    data = load_json(KEYS_FILE)
    data[key] = {"duration_days": int(days), "activated_date": None, "status": "active", "bound_device": None}
    save_json(KEYS_FILE, data)
    return key

def admin_reset_device(key):
    data = load_json(KEYS_FILE)
    if key in data:
        data[key]["bound_device"] = None
        save_json(KEYS_FILE, data)
        return True
    return False

def admin_delete_key(key):
    data = load_json(KEYS_FILE)
    if key in data:
        del data[key]
        save_json(KEYS_FILE, data)
        return True
    return False

# ==========================================
# 4. MAIN DISPATCHER
# ==========================================
# Check URL for Admin Mode
if st.query_params.get("view") == "admin":
    # ++++++++++++++++++++++++++++++++++++++++++++++++++++++
    # ADMIN PANEL UI
    # ++++++++++++++++++++++++++++++++++++++++++++++++++++++
    st.title("🔐 Admin Panel")
    
    if 'admin_login' not in st.session_state: st.session_state.admin_login = False

    if not st.session_state.admin_login:
        pwd = st.text_input("Admin Password", type="password")
        if st.button("Login Admin"):
            if pwd == "admin123": # <--- CHANGE PASSWORD HERE
                st.session_state.admin_login = True
                st.rerun()
            else:
                st.error("Wrong Password")
        
        st.markdown("---")
        if st.button("⬅️ Back to App"):
            st.query_params.clear()
            st.rerun()
        st.stop()

    # Sidebar
    with st.sidebar:
        st.success("Admin Logged In")
        if st.button("Logout Admin"):
            st.session_state.admin_login = False
            st.rerun()
        if st.button("Go to User App"):
            st.query_params.clear()
            st.rerun()

    tab1, tab2 = st.tabs(["➕ Generate Key", "📋 Manage Keys"])

    with tab1:
        st.subheader("Create New Key")
        c1, c2 = st.columns([2,1])
        days = c1.number_input("Days", min_value=1, value=30)
        if c2.button("Generate", use_container_width=True):
            k = admin_generate_key(days)
            st.success(f"Key Created: {k}")
            st.code(k)

    with tab2:
        st.subheader("All Keys")
        data = load_json(KEYS_FILE)
        search = st.text_input("Search Key", "")
        
        if not data: st.info("No keys found.")
        else:
            # Sort by creation (approx) or just list
            for key, info in list(data.items())[::-1]:
                if search and search.upper() not in key: continue
                
                status_icon = "🟢" if info['status'] == "active" else "🔴"
                with st.expander(f"{status_icon} {key} ({info['duration_days']} Days)"):
                    c1, c2 = st.columns(2)
                    c1.write(f"**Active Date:** {info['activated_date']}")
                    c1.write(f"**Device:** {'🔒 Locked' if info['bound_device'] else '🔓 Free'}")
                    
                    if c2.button("Reset Device", key=f"rst_{key}"):
                        admin_reset_device(key)
                        st.success("Device Unlocked!")
                        time.sleep(0.5); st.rerun()
                    
                    if c2.button("Delete Key", key=f"del_{key}", type="primary"):
                        admin_delete_key(key)
                        st.rerun()

else:
    # ++++++++++++++++++++++++++++++++++++++++++++++++++++++
    # USER APP UI (EDGE ONLY)
    # ++++++++++++++++++++++++++++++++++++++++++++++++++++++
    cm = get_cookie_manager()
    did = get_device_id(cm)

    # Auto Login Check
    if 'auth' not in st.session_state:
        st.session_state.auth = False
        cookie_key = cm.get("auth_key")
        if cookie_key:
            s, d = check_access_key(cookie_key, did)
            if s == "Valid":
                st.session_state.auth = True
                st.session_state.ukey = cookie_key
                st.session_state.days = d

    # Login Screen
    if not st.session_state.auth:
        st.title("🇰🇭 Khmer AI Voice Pro")
        st.markdown("<br>", unsafe_allow_html=True)
        st.info("សូមវាយបញ្ចូល Key ដើម្បីប្រើប្រាស់")
        
        key_input = st.text_input("🔑 Access Key", type="password")
        if st.button("Login", type="primary", use_container_width=True):
            s, d = check_access_key(key_input, did)
            if s == "Valid":
                st.session_state.auth = True
                st.session_state.ukey = key_input
                st.session_state.days = d
                cm.set("auth_key", key_input, expires_at=datetime.datetime.now() + datetime.timedelta(days=30))
                st.rerun()
            else:
                st.error(s)
        
        st.markdown("---")
        if st.button("🔐 Admin Login", type="secondary", use_container_width=True):
            st.query_params["view"] = "admin"
            st.rerun()
        
        st.stop()

    # === LOGGED IN APP ===
    st.title("🇰🇭 Khmer AI Voice (Edge)")
    
    with st.sidebar:
        st.success(f"✅ Active: {st.session_state.days} Days Left")
        if st.button("Sign Out"):
            cm.delete("auth_key")
            st.session_state.clear()
            st.rerun()
        
        st.divider()
        st.subheader("⚙️ Settings")
        
        # Voice Options (ONLY EDGE)
        voice_map = {
            "Sreymom (Khmer)": "km-KH-SreymomNeural",
            "Piseth (Khmer)": "km-KH-PisethNeural",
            "Emma (English)": "en-US-EmmaMultilingualNeural"
        }
        
        # Defaults
        if "v_name" not in st.session_state: st.session_state.v_name = "Sreymom (Khmer)"
        if "rate" not in st.session_state: st.session_state.rate = 0
        if "pitch" not in st.session_state: st.session_state.pitch = 0
        if "pad" not in st.session_state: st.session_state.pad = 80

        v_name = st.selectbox("Voice", list(voice_map.keys()), key="v_name")
        rate = st.slider("Speed", -50, 50, key="rate")
        pitch = st.slider("Pitch", -50, 50, key="pitch")
        pad = st.number_input("Padding (ms)", value=80, key="pad")

        st.divider()
        st.caption("💾 Presets")
        for i in range(1, 4):
            col1, col2 = st.columns([3, 1])
            p = get_preset(st.session_state.ukey, i)
            p_name = p['name'] if p else f"Slot {i}"
            
            if col1.button(f"📂 {p_name}", key=f"l{i}", use_container_width=True):
                if p:
                    st.session_state.v_name = p['v_name']
                    st.session_state.rate = p['rate']
                    st.session_state.pitch = p['pitch']
                    st.rerun()
            
            if col2.button("💾", key=f"s{i}"):
                save_preset(st.session_state.ukey, i, {"v_name":v_name, "rate":rate, "pitch":pitch}, f"Preset {i}")
                st.toast(f"Saved to Slot {i}")

    # Main Interface
    text = st.text_area("បញ្ចូលអត្ថបទ...", height=150, placeholder="សួស្តី! តើអ្នកសុខសប្បាយទេ?")
    
    if st.button("Generate Audio 🎵", type="primary", use_container_width=True):
        if text:
            with st.spinner("Generating (Edge-TTS)..."):
                try:
                    # Fix for Asyncio Loop in Streamlit
                    try:
                        loop = asyncio.get_event_loop()
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                    
                    file_path = loop.run_until_complete(generate_audio_edge(text, voice_map[v_name], rate, pitch))
                    
                    # Add Effects
                    final_audio = add_audio_effects(file_path, pad)
                    
                    # Export to buffer
                    buf = io.BytesIO()
                    final_audio.export(buf, format="mp3")
                    
                    st.success("Done!")
                    st.audio(buf, format="audio/mp3")
                    st.download_button("Download MP3", buf, "audio.mp3", "audio/mp3", use_container_width=True)
                    
                    # Cleanup
                    try: os.remove(file_path)
                    except: pass
                    
                except Exception as e:
                    st.error(f"Error: {e}")
        else:
            st.warning("Please enter text first.")
