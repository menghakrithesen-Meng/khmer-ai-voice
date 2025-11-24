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
    button[data-testid="stNumberInputStepDown"], button[data-testid="stNumberInputStepUp"] { display: none; }
    div[data-testid="stNumberInput"] input { text-align: center; }
    div[data-testid="column"] button { padding: 0px 2px !important; font-size: 11px !important; min-height: 32px !important; width: 100%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    div[data-testid="column"] button[kind="primary"] { border-color: #ff4b4b !important; background-color: #ff4b4b !important; color: white !important; }
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
    return load_json(ACTIVE_FILE)

def get_server_token(user_key):
    active = load_active_sessions()
    return active.get(user_key)

def is_key_already_in_use(user_key):
    """Check if key exists in active_sessions.json"""
    active = load_active_sessions()
    return user_key in active

def create_session(user_key):
    """Create new session token"""
    new_token = str(uuid.uuid4())
    active = load_active_sessions()
    active[user_key] = new_token
    save_json(ACTIVE_FILE, active)
    return new_token

def delete_session(user_key):
    """Remove key from active sessions (LOGOUT)"""
    active = load_active_sessions()
    if user_key in active:
        del active[user_key]
        save_json(ACTIVE_FILE, active)

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

# --- PRESETS & AUDIO ---
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
# 2. ADMIN PANEL (URL/?view=admin)
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
                st.success(f"New Key: {k}")
        with c2:
            if st.button("Reset All Sessions (Emergency)"):
                save_json(ACTIVE_FILE, {})
                st.success("All users logged out!")

        st.divider()
        st.write("### 🟢 Active Sessions (Locked)")
        st.json(load_active_sessions())
    st.stop()


# ==========================================
# 3. AUTH FLOW (STRICT MODE: LOGOUT REQUIRED)
# ==========================================
st.title("🇰🇭 Khmer AI Voice Pro (Edge)")
cm = stx.CookieManager(key="main_manager")

# --- 3.1 COOKIE RETRY (Fix Refresh Issue) ---
if "retry_count" not in st.session_state:
    st.session_state.retry_count = 0

cookie_key = cm.get("auth_key")
cookie_token = cm.get("session_token")

# Wait for cookie (Retry Mechanism)
if not cookie_key and st.session_state.retry_count < 1:
    time.sleep(0.5)
    st.session_state.retry_count += 1
    st.rerun()

if cookie_key:
    st.session_state.retry_count = 0

# --- 3.2 AUTO LOGIN LOGIC ---
if "auth" not in st.session_state:
    st.session_state.auth = False

# Auto Login: Only if Token matches Server
if not st.session_state.auth and cookie_key and cookie_token:
    status, days = check_access_key(cookie_key)
    server_token = get_server_token(cookie_key)
    
    if status == "Valid" and cookie_token == server_token:
        st.session_state.auth = True
        st.session_state.ukey = cookie_key
        st.session_state.days = days
        st.session_state.my_token = cookie_token
    else:
        pass # Token mismatch or Key removed from server

# --- 3.3 LOGIN FORM (STRICT) ---
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
        # 1. Check Key Validity
        status, days = check_access_key(key_input)
        if status != "Valid":
            st.error(status)
            st.stop()

        # 2. STRICT CHECK: Is Key already in use?
        if is_key_already_in_use(key_input):
            st.error("⛔ Access Denied!")
            st.warning("Key នេះកំពុង Online នៅ Browser/Device ផ្សេង។")
            st.info("សូមទៅចុច Logout ពី Device ចាស់ជាមុនសិន ទើបអាចចូលទីនេះបាន។")
            st.stop()

        # 3. If not in use, Create Session
        new_token = create_session(key_input)
        
        st.session_state.auth = True
        st.session_state.ukey = key_input
        st.session_state.days = days
        st.session_state.my_token = new_token
        st.session_state.retry_count = 0
        
        if remember:
            exp = datetime.datetime.now() + datetime.timedelta(days=30)
            cm.set("auth_key", key_input, expires_at=exp, key="sk")
            cm.set("session_token", new_token, expires_at=exp, key="st")
        
        st.success("Login Success!")
        time.sleep(0.5)
        st.rerun()
    
    st.stop()


# ==========================================
# 4. REAL-TIME SECURITY CHECK
# ==========================================
if st.session_state.auth:
    # Check if my token is still valid on server
    current_valid_token = get_server_token(st.session_state.ukey)
    my_token = st.session_state.get("my_token")
    
    # If server token is gone (Logged out) OR changed
    if current_valid_token != my_token:
        st.error("🚨 Session Ended.")
        st.session_state.clear()
        cm.delete("auth_key")
        cm.delete("session_token")
        time.sleep(1)
        st.rerun()


# ==========================================
# 5. MAIN APP CONTENT
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
    
    # LOGOUT BUTTON (CRITICAL FOR STRICT MODE)
    if st.button("Logout", type="primary"):
        # 1. Remove from JSON (Server)
        delete_session(st.session_state.ukey)
        
        # 2. Clear Local Session
        st.session_state.clear()
        
        # 3. Clear Cookies
        cm.delete("auth_key")
        cm.delete("session_token")
        
        st.success("Logged out successfully!")
        time.sleep(0.5)
        st.rerun()

    st.divider()
    st.subheader("⚙️ Settings")
    if "g_voice" not in st.session_state: st.session_state.g_voice = "Sreymom (Khmer)"
    if "g_rate" not in st.session_state: st.session_state.g_rate = 0
    if "g_pitch" not in st.session_state: st.session_state.g_pitch = 0

    v_sel = st.selectbox("Voice", list(VOICES.keys()), index=list(VOICES.keys()).index(st.session_state.g_voice))
    r_sel = st.slider("Speed", -50, 50, value=st.session_state.g_rate)
    p_sel = st.slider("Pitch", -50, 50, value=st.session_state.g_pitch)
    pad_sel = st.number_input("Padding (ms)", value=80)

    st.session_state.g_voice = v_sel
    st.session_state.g_rate = r_sel
    st.session_state.g_pitch = p_sel

    st.divider()
    st.subheader("💾 Presets")
    preset_name_input = st.text_input("Name (Short)", placeholder="Ex: Boy")
    for i in range(1, 7):
        c1, c2 = st.columns([3, 1])
        saved_p = get_user_preset(st.session_state.ukey, i)
        btn_name = saved_p["name"] if saved_p else f"Slot {i}"
        if c1.button(f"📂 {btn_name}", key=f"l{i}", use_container_width=True):
            if saved_p:
                st.session_state.g_voice = saved_p["voice"]
                st.session_state.g_rate = saved_p["rate"]
                st.session_state.g_pitch = saved_p["pitch"]
                st.rerun()
        if c2.button("💾", key=f"s{i}"):
            data = {"voice": v_sel, "rate": r_sel, "pitch": p_sel}
            save_user_preset(st.session_state.ukey, i, data, preset_name_input)
            st.toast(f"Saved Slot {i}!")
            time.sleep(0.5); st.rerun()

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
                    st.download_button("Download MP3", buf, "audio.mp3", "audio/mp3")
                except Exception as e: st.error(str(e))

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
                st.session_state.line_settings.append({"voice": st.session_state.g_voice, "rate": st.session_state.g_rate, "pitch": st.session_state.g_pitch, "slot": None})

        st.markdown("#### 🎭 SRT Default Preset")
        preset_opts = ["-- No Preset --"]
        preset_map = {}
        for i in range(1, 7):
            pd = get_user_preset(st.session_state.ukey, i)
            if pd:
                name = f"Slot {i}: {pd.get('name', f'Slot {i}')}"
                preset_opts.append(name)
                preset_map[name] = (i, pd)
        
        srt_def = st.selectbox("Apply to ALL", preset_opts, key="srt_def")
        if st.button("Apply Preset to All"):
            if srt_def in preset_map:
                sid, _ = preset_map[srt_def]
                for idx in range(len(st.session_state.srt_lines)): apply_preset_to_line(st.session_state.ukey, idx, sid)
                st.rerun()

        with st.container(height=600):
            for idx, sub in enumerate(st.session_state.srt_lines):
                cur = st.session_state.line_settings[idx]
                slot = cur.get("slot")
                slot_cls = f" slot-{slot}" if slot else ""
                p_html = f"<span class='preset-tag'>{get_user_preset(st.session_state.ukey, slot)['name']}</span>" if slot else ""
                st.markdown(f"<div class='srt-box{slot_cls}'><b>#{idx+1}</b> <small>{sub['start']}ms</small> {p_html}<br>{sub['text']}</div>", unsafe_allow_html=True)
                
                c_v, c_r, c_p, c_pr = st.columns([2, 1, 1, 4])
                new_v = c_v.selectbox("V", list(VOICES.keys()), index=list(VOICES.keys()).index(cur["voice"]), key=f"v{idx}", label_visibility="collapsed")
                new_r = c_r.number_input("R", -50, 50, value=cur["rate"], key=f"r{idx}", label_visibility="collapsed")
                new_p = c_p.number_input("P", -50, 50, value=cur["pitch"], key=f"p{idx}", label_visibility="collapsed")
                st.session_state.line_settings[idx].update({"voice": new_v, "rate": new_r, "pitch": new_p, "slot": slot})

                with c_pr:
                    cols = st.columns(6)
                    for sid in range(1, 7):
                        pd = get_user_preset(st.session_state.ukey, sid)
                        if cols[sid-1].button(pd['name'][:4] if pd else "-", key=f"b{idx}_{sid}", type="primary" if slot==sid else "secondary"):
                            apply_preset_to_line(st.session_state.ukey, idx, sid)
                            st.rerun()

        if st.button("🚀 Generate Full Audio (Strict Sync)", type="primary"):
            progress = st.progress(0); status = st.empty()
            last_start = st.session_state.srt_lines[-1]["start"]
            final_mix = AudioSegment.silent(duration=last_start + 10000)
            try:
                loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
                for i, sub in enumerate(st.session_state.srt_lines):
                    status.text(f"Processing line {i+1}...")
                    s = st.session_state.line_settings[i]
                    raw_path = loop.run_until_complete(gen_edge(sub["text"], VOICES[s["voice"]], s["rate"], s["pitch"]))
                    clip = AudioSegment.from_file(raw_path)
                    final_mix = final_mix.overlay(clip, position=sub["start"])
                    try: os.remove(raw_path)
                    except: pass
                    progress.progress((i+1)/len(st.session_state.srt_lines))
                status.success("Done!")
                buf = io.BytesIO(); final_mix.export(buf, format="mp3"); buf.seek(0)
                st.audio(buf)
                st.download_button("Download Conversation", buf, "conversation.mp3", "audio/mp3")
            except Exception as e: status.error(f"Error: {e}")

with tab3:
    st.subheader("Gemini Translator (SRT)")
    st.info("Coming Soon...")
