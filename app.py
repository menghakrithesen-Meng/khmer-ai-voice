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
# 0. CONFIG & HEADERS
# ==========================================
st.set_page_config(page_title="Khmer AI Voice Pro", page_icon="🎙️", layout="wide")

# ព្យាយាមប្រើ Header នេះនៅពេលដែល Library ត្រូវការ Request (ជាការកំណត់ Global)
# ទោះបីជា Server នៅ US ក៏ដោយ កូដនេះប្រាប់ថាជាអ្នកប្រើប្រាស់ខ្មែរ
HEADERS = {
    "Accept-Language": "km-KH,km;q=0.9",  # ប្រាប់ថាខ្ញុំជាអ្នកអានខ្មែរ
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36"
}

KEYS_FILE = "web_keys.json"
PRESETS_FILE = "user_presets.json"
ACTIVE_FILE = "active_sessions.json"  # Format: { "USER_KEY": "DEVICE_UUID" }

# បង្កើត Device ID សម្រាប់ Browser Session នីមួយៗ (Unique per tab/browser)
if "device_id" not in st.session_state:
    st.session_state.device_id = str(uuid.uuid4())

# 🎨 CUSTOM CSS
st.markdown("""
<style>
    .stApp { background: linear-gradient(to right, #0f172a, #1e293b); color: white; }
    section[data-testid="stSidebar"] { background-color: #111827; border-right: 1px solid #374151; }
    
    /* Hide Number Input Steppers */
    button[data-testid="stNumberInputStepDown"], button[data-testid="stNumberInputStepUp"] {
        display: none;
    }
    div[data-testid="stNumberInput"] input {
        text-align: center;
    }

    /* Small Preset Buttons */
    div[data-testid="column"] button {
        padding: 0px 2px !important;
        font-size: 11px !important;
        min-height: 32px !important;
        width: 100%;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    
    /* Active Button Color */
    div[data-testid="column"] button[kind="primary"] {
        border-color: #ff4b4b !important;
        background-color: #ff4b4b !important;
        color: white !important;
    }

    /* SRT Box */
    .srt-box { 
        background: #1e293b; 
        border: 1px solid #334155; 
        border-radius: 6px; 
        padding: 10px; 
        margin-bottom: 5px; 
        border-left: 4px solid #8b5cf6; 
    }

    /* 🎨 Color per Preset Slot */
    .srt-box.slot-1 { border-left-color: #f97316 !important; }  /* orange */
    .srt-box.slot-2 { border-left-color: #22c55e !important; }  /* green */
    .srt-box.slot-3 { border-left-color: #3b82f6 !important; }  /* blue */
    .srt-box.slot-4 { border-left-color: #e11d48 !important; }  /* rose */
    .srt-box.slot-5 { border-left-color: #a855f7 !important; }  /* purple */
    .srt-box.slot-6 { border-left-color: #facc15 !important; }  /* yellow */

    /* Preset label pill */
    .preset-tag {
        display: inline-block;
        padding: 2px 6px;
        border-radius: 999px;
        font-size: 11px;
        background: #4b5563;
        margin-left: 6px;
        color: #e5e7eb;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 1. FUNCTIONS
# ==========================================
def load_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

# --- ACTIVE KEYS (1 Key = 1 Device ID) ---
def load_active_sessions():
    data = load_json(ACTIVE_FILE)
    if isinstance(data, dict):
        return data
    return {}

def save_active_sessions(data):
    save_json(ACTIVE_FILE, data)

# --- AUTH ---
def check_access_key(user_key):
    keys_db = load_json(KEYS_FILE)
    if user_key not in keys_db:
        return "Invalid Key", 0
    k_data = keys_db[user_key]
    if k_data.get("status") != "active":
        return "Key Disabled", 0
    
    # Activate on first use
    if not k_data.get("activated_date"):
        k_data["activated_date"] = str(datetime.date.today())
        save_json(KEYS_FILE, keys_db)
    
    start = datetime.date.fromisoformat(k_data["activated_date"])
    exp = start + datetime.timedelta(days=k_data["duration_days"])
    left = (exp - datetime.date.today()).days
    
    if left < 0:
        return "Expired", 0
    return "Valid", left

def login_logic(user_key, current_device_id):
    """
    Core Login Logic:
    1. Check Valid Key
    2. Check if Key is used by another Device ID
    """
    status, days = check_access_key(user_key)
    if status != "Valid":
        return status, days

    active = load_active_sessions()
    
    # ប្រសិនបើ Key នេះកំពុងប្រើ ហើយ Device ID មិនដូចគ្នា -> Block
    if user_key in active:
        recorded_device = active[user_key]
        if recorded_device != current_device_id:
            # Key is active on another browser
            return "Key is active on another browser", days

    # Save Session
    active[user_key] = current_device_id
    save_active_sessions(active)
    
    return "Valid", days

def logout_key(user_key):
    active = load_active_sessions()
    if user_key in active:
        del active[user_key]
        save_active_sessions(active)

# --- PRESETS & AUDIO ---
def save_user_preset(user_key, slot, data, name):
    db = load_json(PRESETS_FILE)
    if user_key not in db:
        db[user_key] = {}
    data["name"] = name if name else f"{slot}"
    db[user_key][str(slot)] = data
    save_json(PRESETS_FILE, db)

def get_user_preset(user_key, slot):
    db = load_json(PRESETS_FILE)
    return db.get(user_key, {}).get(str(slot), None)

def apply_preset_to_line(user_key, line_index, slot_id):
    pd = get_user_preset(user_key, slot_id)
    if not pd:
        return
    st.session_state.line_settings[line_index] = {
        "voice": pd["voice"],
        "rate": pd["rate"],
        "pitch": pd["pitch"],
        "slot": slot_id,
    }

async def gen_edge(text, voice, rate, pitch):
    # Edge TTS មិនប្រើ Header ផ្ទាល់ក្នុង Function នេះទេ ប៉ុន្តែវាដំណើរការល្អជាមួយ Unicode ខ្មែរ
    file_path = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3").name
    rate_str = f"{rate:+d}%" if rate != 0 else "+0%"
    pitch_str = f"{pitch:+d}Hz" if pitch != 0 else "+0Hz"
    communicate = edge_tts.Communicate(text, voice, rate=rate_str, pitch=pitch_str)
    await communicate.save(file_path)
    return file_path

def process_audio(file_path, pad_ms):
    try:
        seg = AudioSegment.from_file(file_path)
        pad = AudioSegment.silent(duration=pad_ms)
        return pad + effects.normalize(seg) + pad
    except Exception:
        return AudioSegment.from_file(file_path)

def srt_time_to_ms(time_str):
    try:
        start, end = time_str.split(" --> ")
        h, m, s = start.replace(",", ".").split(":")
        start_ms = int(float(h) * 3600000 + float(m) * 60000 + float(s) * 1000)
        return start_ms
    except Exception:
        return 0

def parse_srt(content):
    subs = []
    blocks = re.split(r"\n\s*\n", content.strip())
    for b in blocks:
        lines = b.strip().split("\n")
        if len(lines) >= 3:
            time_idx = 1
            if "-->" not in lines[1]:
                for i, l in enumerate(lines):
                    if "-->" in l:
                        time_idx = i
                        break
            start_ms = srt_time_to_ms(lines[time_idx])
            text = " ".join(lines[time_idx + 1 :])
            text = re.sub(r"<[^>]+>", "", text)
            if text.strip():
                subs.append({"start": start_ms, "text": text})
    return subs

# ==========================================
# 2. ADMIN PANEL (?view=admin)
# ==========================================
if st.query_params.get("view") == "admin":
    st.title("🔐 Admin Panel")
    pwd = st.text_input("Password", type="password")
    if pwd == "admin123":
        c1, c2 = st.columns(2)
        with c1:
            days = st.number_input("Days", 30)
            if st.button("Generate Key"):
                k = "KHM-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
                db = load_json(KEYS_FILE)
                db[k] = {"duration_days": days, "activated_date": None, "status": "active"}
                save_json(KEYS_FILE, db)
                st.success(f"Key: {k}")
        with c2:
            if st.button("Clear All Active Sessions"):
                save_json(ACTIVE_FILE, {})
                st.success("All users logged out.")
        
        st.write("### Active Keys")
        st.json(load_json(KEYS_FILE))
        st.write("### Active Sessions (Device IDs)")
        st.json(load_json(ACTIVE_FILE))
    st.stop()

# ==========================================
# 3. AUTH FLOW (RETRY MECHANISM)
# ==========================================
st.title("🇰🇭 Khmer AI Voice Pro (Edge)")

# ប្រើ key តែមួយគត់សម្រាប់ Cookie Manager កុំប្តូរ key
cm = stx.CookieManager(key="main_cookie_manager")

# --- HELPER FUNCTIONS ---
def get_active_token(user_key):
    active = load_active_sessions()
    return active.get(user_key)

def set_active_session(user_key):
    new_token = str(uuid.uuid4())
    active = load_active_sessions()
    active[user_key] = new_token
    save_active_sessions(active)
    return new_token

# --- 3.0: SMART COOKIE LOADER ---
if "retry_count" not in st.session_state:
    st.session_state.retry_count = 0

cookie_key = cm.get("auth_key")
cookie_token = cm.get("session_token")

# Retry if cookie not found immediately
if not cookie_key and st.session_state.retry_count < 2:
    time.sleep(0.5)
    st.session_state.retry_count += 1
    st.rerun()

if cookie_key:
    st.session_state.retry_count = 0

# --- 3.1: AUTO-LOGIN LOGIC ---
if "auth" not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth and cookie_key and cookie_token:
    # 1. Check Key
    status, days = check_access_key(cookie_key)
    # 2. Check Session Token
    server_token = get_active_token(cookie_key)
    
    if status == "Valid" and cookie_token == server_token:
        st.session_state.auth = True
        st.session_state.ukey = cookie_key
        st.session_state.days = days
    else:
        # Cookie invalid or session replaced
        pass

# --- 3.2: LOGIN INTERFACE ---
if not st.session_state.auth:
    if st.session_state.retry_count > 0 and st.session_state.retry_count < 2:
        with st.spinner("🔄 Checking session..."):
            time.sleep(1)
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

        # Create New Session (Kick other devices)
        new_token = set_active_session(key_input)
        
        st.session_state.auth = True
        st.session_state.ukey = key_input
        st.session_state.days = days
        st.session_state.retry_count = 0
        
        if remember:
            exp = datetime.datetime.now() + datetime.timedelta(days=30)
            cm.set("auth_key", key_input, expires_at=exp, key="set_k_final")
            cm.set("session_token", new_token, expires_at=exp, key="set_t_final")
        
        st.success(f"Login Success! ({days} days left)")
        time.sleep(0.5)
        st.rerun()
    
    # Warning message if needed
    if cookie_key and cookie_token:
        server_token = get_active_token(cookie_key)
        if server_token and server_token != cookie_token:
             st.warning("⚠️ Session Expired: Key នេះត្រូវបាន Login នៅកន្លែងផ្សេង។")

    st.stop()


# ==========================================
# 4. APP INTERFACE (Logged In)
# ==========================================
VOICES = {
    "Sreymom (Khmer)": "km-KH-SreymomNeural",
    "Piseth (Khmer)": "km-KH-PisethNeural",
    "Emma (EN Multi)": "en-US-EmmaMultilingualNeural",
    "William (EN AU Multi)": "en-AU-WilliamMultilingualNeural",
    "Jenny (EN Multi)": "en-US-JennyMultilingualNeural",
    "Guy (EN Multi)": "en-US-GuyMultilingualNeural",
    "Xiaoxiao (Chinese)": "zh-CN-XiaoxiaoNeural",
}

with st.sidebar:
    st.success(f"✅ Active: {st.session_state.days} Days")
    st.caption(f"ID: {st.session_state.ukey[:6]}...")

    if st.button("Logout", type="primary"):
        logout_key(st.session_state.ukey)
        cm.delete("auth_key")
        st.session_state.clear()
        st.rerun()

    st.divider()
    st.subheader("⚙️ Global Settings")

    if "g_voice" not in st.session_state:
        st.session_state.g_voice = "Sreymom (Khmer)"
    if "g_rate" not in st.session_state:
        st.session_state.g_rate = 0
    if "g_pitch" not in st.session_state:
        st.session_state.g_pitch = 0

    v_sel = st.selectbox("Voice", list(VOICES.keys()), index=list(VOICES.keys()).index(st.session_state.g_voice))
    r_sel = st.slider("Speed", -50, 50, value=st.session_state.g_rate)
    p_sel = st.slider("Pitch", -50, 50, value=st.session_state.g_pitch)
    pad_sel = st.number_input("Padding (ms)", value=80)

    st.session_state.g_voice = v_sel
    st.session_state.g_rate = r_sel
    st.session_state.g_pitch = p_sel

    st.divider()
    st.subheader("💾 6 Presets")
    preset_name_input = st.text_input("Name (Short)", placeholder="Ex: Boy")

    for i in range(1, 7):
        c1, c2 = st.columns([3, 1])
        saved_p = get_user_preset(st.session_state.ukey, i)
        btn_name = saved_p["name"] if saved_p else f"Slot {i}"

        if c1.button(f"📂 {btn_name}", key=f"load_{i}", use_container_width=True):
            if saved_p:
                st.session_state.g_voice = saved_p["voice"]
                st.session_state.g_rate = saved_p["rate"]
                st.session_state.g_pitch = saved_p["pitch"]
                st.rerun()

        if c2.button("💾", key=f"save_{i}"):
            data = {"voice": v_sel, "rate": r_sel, "pitch": p_sel}
            save_user_preset(st.session_state.ukey, i, data, preset_name_input)
            st.toast(f"Saved to Slot {i}!")
            time.sleep(0.5)
            st.rerun()

# Removed Tab 3 (Gemini Translator) as requested
tab1, tab2 = st.tabs(["📝 Text Mode", "🎬 SRT Multi-Speaker"])

# --- TAB 1: TEXT ---
with tab1:
    txt = st.text_area("Input Text...", height=150)
    if st.button("Generate Audio 🎵", type="primary"):
        if txt:
            with st.spinner("Generating..."):
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    raw = loop.run_until_complete(gen_edge(txt, VOICES[v_sel], r_sel, p_sel))
                    final = process_audio(raw, pad_sel)
                    buf = io.BytesIO()
                    final.export(buf, format="mp3")
                    st.audio(buf)
                except Exception as e:
                    st.error(f"Error: {e}")

# --- TAB 2: SRT ---
with tab2:
    srt_file = st.file_uploader("Upload SRT", type="srt", key="srt_up")
    if srt_file:
        if "srt_lines" not in st.session_state or st.session_state.get("last_srt") != srt_file.name:
            content = srt_file.getvalue().decode("utf-8")
            st.session_state.srt_lines = parse_srt(content)
            st.session_state.last_srt = srt_file.name
            st.session_state.line_settings = []
            for _ in st.session_state.srt_lines:
                st.session_state.line_settings.append({
                    "voice": st.session_state.g_voice, "rate": st.session_state.g_rate, "pitch": st.session_state.g_pitch, "slot": None
                })
        
        # PRESET ALL
        st.markdown("#### 🎭 SRT Default Preset")
        preset_options = ["-- No Preset --"]
        preset_map = {}
        for i in range(1, 7):
            pd = get_user_preset(st.session_state.ukey, i)
            if pd:
                name = f"Slot {i}: {pd.get('name', f'Slot {i}')}"
                preset_options.append(name)
                preset_map[name] = (i, pd)
        
        srt_def = st.selectbox("Apply to ALL", preset_options, key="srt_def")
        if st.button("Apply Preset to All"):
            if srt_def in preset_map:
                slot_id, _ = preset_map[srt_def]
                for idx in range(len(st.session_state.srt_lines)):
                    apply_preset_to_line(st.session_state.ukey, idx, slot_id)
                st.success("Applied!")
                st.rerun()

        # EDITOR
        with st.container(height=600):
            for idx, sub in enumerate(st.session_state.srt_lines):
                cur = st.session_state.line_settings[idx]
                slot = cur.get("slot")
                slot_class = f" slot-{slot}" if slot else ""
                p_html = f"<span class='preset-tag'>{get_user_preset(st.session_state.ukey, slot)['name']}</span>" if slot else ""
                
                st.markdown(f"<div class='srt-box{slot_class}'><b>#{idx+1}</b> <small>{sub['start']}ms</small> {p_html}<br>{sub['text']}</div>", unsafe_allow_html=True)
                
                c_v, c_r, c_p, c_pr = st.columns([2, 1, 1, 4])
                
                new_v = c_v.selectbox("V", list(VOICES.keys()), index=list(VOICES.keys()).index(cur["voice"]), key=f"v_{idx}", label_visibility="collapsed")
                new_r = c_r.number_input("R", -50, 50, value=cur["rate"], key=f"r_{idx}", label_visibility="collapsed")
                new_p = c_p.number_input("P", -50, 50, value=cur["pitch"], key=f"p_{idx}", label_visibility="collapsed")
                
                st.session_state.line_settings[idx].update({"voice": new_v, "rate": new_r, "pitch": new_p, "slot": slot})

                with c_pr:
                    cols = st.columns(6)
                    for sid in range(1, 7):
                        pd = get_user_preset(st.session_state.ukey, sid)
                        if cols[sid-1].button(pd['name'][:4] if pd else "-", key=f"b_{idx}_{sid}", type="primary" if slot==sid else "secondary"):
                            apply_preset_to_line(st.session_state.ukey, idx, sid)
                            st.rerun()

        # FULL AUDIO GENERATION LOGIC (COMPLETED)
        if st.button("🚀 Generate Full Audio", type="primary"):
             if not st.session_state.srt_lines:
                 st.error("No lines to process")
             else:
                 progress_bar = st.progress(0)
                 status_text = st.empty()
                 
                 full_audio = AudioSegment.silent(duration=0)
                 current_time = 0
                 
                 # Loop Setup
                 loop = asyncio.new_event_loop()
                 asyncio.set_event_loop(loop)
                 
                 try:
                     for i, sub in enumerate(st.session_state.srt_lines):
                         status_text.text(f"Processing line {i+1}/{len(st.session_state.srt_lines)}...")
                         
                         # 1. Calculate Silence needed before this line
                         start_time = sub["start"]
                         silence_duration = start_time - current_time
                         if silence_duration > 0:
                             full_audio += AudioSegment.silent(duration=silence_duration)
                             current_time += silence_duration
                         
                         # 2. Generate Audio for this line
                         s = st.session_state.line_settings[i]
                         temp_file = loop.run_until_complete(
                             gen_edge(sub["text"], VOICES[s["voice"]], s["rate"], s["pitch"])
                         )
                         
                         # 3. Process & Append
                         # Note: Padding is handled by silence calculation usually, 
                         # but we can normalize here.
                         segment = AudioSegment.from_file(temp_file)
                         segment = effects.normalize(segment)
                         
                         full_audio += segment
                         current_time += len(segment)
                         
                         # Clean up temp
                         try:
                             os.remove(temp_file)
                         except:
                             pass
                         
                         progress_bar.progress((i + 1) / len(st.session_state.srt_lines))
                     
                     # Export
                     status_text.text("Merging final audio...")
                     buf = io.BytesIO()
                     full_audio.export(buf, format="mp3")
                     
                     st.success("✅ Done!")
                     st.audio(buf)
                     
                 except Exception as e:
                     st.error(f"Failed: {e}")
