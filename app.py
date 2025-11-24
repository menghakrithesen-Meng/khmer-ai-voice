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
import uuid  # បន្ថែមសម្រាប់បង្កើត Device ID
import extra_streamlit_components as stx

# ==========================================
# 0. CONFIG & SETUP
# ==========================================
st.set_page_config(page_title="Khmer AI Voice Pro", page_icon="🎙️", layout="wide")

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

def get_cookie_manager():
    # ប្រើ key ដើម្បីកុំឱ្យ reload ច្រើនដង
    return stx.CookieManager(key="cookie_manager_instance")

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
            # ករណីពិសេស៖ បើចង់ឱ្យ Login ថ្មី ទាត់ Login ចាស់ចេញ (Kick User) 
            # អាចលុបលក្ខខណ្ឌនេះ។ ប៉ុន្តែតាមសំណើ "1 Key Active 1 Browser" គឺយើង Block។
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
# 3. AUTH FLOW (Strict 1 Key 1 Browser + Persistent Device ID)
# ==========================================
st.title("🇰🇭 Khmer AI Voice Pro (Edge)")
cm = get_cookie_manager()

# --- 3.0: PERSISTENT DEVICE ID SETUP (កែថ្មីត្រង់នេះ) ---
# យើងត្រូវចាំ Device ID ក្នុង Cookie ដើម្បីកុំឱ្យបាត់ពេល Refresh
cookie_dev_id = cm.get("device_id")

if cookie_dev_id:
    # បើមានក្នុង Cookie យកមកប្រើ
    st.session_state.device_id = cookie_dev_id
else:
    # បើអត់ទាន់មាន (បើកដំបូង) -> បង្កើតថ្មី ហើយ Save ចូល Cookie
    if "device_id" not in st.session_state:
        st.session_state.device_id = str(uuid.uuid4())
    
    # Save ទុក 1 ឆ្នាំ
    cm.set("device_id", st.session_state.device_id, expires_at=datetime.datetime.now() + datetime.timedelta(days=365))
    # ចាំបាច់ត្រូវ Stop ដើម្បីឱ្យ Cookie សរសេរចូល Browser សិន
    time.sleep(0.1) 

current_device_id = st.session_state.device_id

# --- 3.1 & 3.2: AUTHENTICATION ---

if "auth" not in st.session_state:
    st.session_state.auth = False

# Auto Login
if not st.session_state.auth:
    time.sleep(0.1) # Wait for cookie reader
    ck_key = cm.get("auth_key")
    if ck_key:
        status, days = login_logic(ck_key, current_device_id)
        if status == "Valid":
            st.session_state.auth = True
            st.session_state.ukey = ck_key
            st.session_state.days = days
        else:
            # កុំបង្ហាញ Error ធំពេកគ្រាន់តែ Warning
            pass 

# Login Form
if not st.session_state.auth:
    key_input = st.text_input("🔑 Access Key", type="password", key="login_input")
    remember = st.checkbox("Remember me", value=True)
    
    if st.button("Login", type="primary"):
        status, days = login_logic(key_input, current_device_id)
        
        if status == "Valid":
            st.session_state.auth = True
            st.session_state.ukey = key_input
            st.session_state.days = days
            
            if remember:
                # Save Key
                cm.set("auth_key", key_input, expires_at=datetime.datetime.now() + datetime.timedelta(days=30))
            
            st.success("Login success!")
            time.sleep(0.5)
            st.rerun()
        else:
            if "active on another browser" in status:
                st.error(f"🔒 Key នេះកំពុងជាប់នៅ Browser ផ្សេង (ID ខុសគ្នា)។")
                # ប៊ូតុងដើម្បី Reset Session (Optional - សម្រាប់ម្ចាស់ Key បើចង់ Force Login)
                if st.button("Force Login (Clear Old Session)?"):
                     active = load_active_sessions()
                     active[key_input] = current_device_id # ដាក់ ID ថ្មីចូលជំនួស
                     save_active_sessions(active)
                     st.success("Session reset! Please click Login again.")
            else:
                st.error(status)
    
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

tab1, tab2, tab3 = st.tabs(["📝 Text Mode", "🎬 SRT Multi-Speaker", "🤖 SRT Translator"])

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

        if st.button("🚀 Generate Full Audio", type="primary"):
             st.info("Generating... (This logic is same as before)")
             # ... (Your generation logic here) ...

with tab3:
    st.subheader("Gemini Translator")
    st.info("Coming Soon...")

