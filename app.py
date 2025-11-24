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
from PIL import Image
import google.generativeai as genai  # បន្ថែម Library សម្រាប់ Gemini

# ==========================================
# 0. CONFIG & SETUP
# ==========================================
try:
    img_icon = Image.open("logo.png")
except:
    img_icon = "🎙️"

st.set_page_config(page_title="Khmer AI Voice Pro", page_icon=img_icon, layout="wide")

KEYS_FILE = "web_keys.json"
PRESETS_FILE = "user_presets.json"
ACTIVE_FILE = "active_sessions.json"

st.markdown("""
<style>
    .stApp { background: linear-gradient(to right, #0f172a, #1e293b); color: white; }
    section[data-testid="stSidebar"] { background-color: #111827; border-right: 1px solid #374151; }
    
    /* Hide input spinners */
    button[data-testid="stNumberInputStepDown"], button[data-testid="stNumberInputStepUp"] { display: none; }
    div[data-testid="stNumberInput"] input { text-align: center; }
    
    /* Preset Buttons styling */
    div[data-testid="column"] button { padding: 0px 2px !important; font-size: 10px !important; min-height: 28px !important; width: 100%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    div[data-testid="column"] button[kind="primary"] { border-color: #ff4b4b !important; background-color: #ff4b4b !important; color: white !important; }
    
    /* SRT Box Design */
    .srt-box { background: #1e293b; border: 1px solid #334155; border-radius: 6px; padding: 10px; margin-bottom: 5px; border-left: 4px solid #8b5cf6; }
    .srt-box.slot-1 { border-left-color: #f97316 !important; } 
    .srt-box.slot-2 { border-left-color: #22c55e !important; } 
    .srt-box.slot-3 { border-left-color: #3b82f6 !important; } 
    .srt-box.slot-4 { border-left-color: #e11d48 !important; } 
    .srt-box.slot-5 { border-left-color: #a855f7 !important; } 
    .srt-box.slot-6 { border-left-color: #facc15 !important; } 
    
    .preset-tag { display: inline-block; padding: 2px 6px; border-radius: 999px; font-size: 11px; background: #4b5563; margin-left: 6px; color: #e5e7eb; }
    textarea { font-size: 16px !important; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 1. HELPER FUNCTIONS
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

def load_active_sessions(): return load_json(ACTIVE_FILE)
def get_server_token(user_key): return load_active_sessions().get(user_key)
def is_key_already_in_use(user_key): return user_key in load_active_sessions()

def create_session(user_key):
    new_token = str(uuid.uuid4())
    active = load_active_sessions()
    active[user_key] = new_token
    save_json(ACTIVE_FILE, active)
    return new_token

def delete_session(user_key):
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
# 2. ADMIN PANEL
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
            if st.button("Reset All Sessions"):
                save_json(ACTIVE_FILE, {})
                st.success("All users logged out!")
        st.write("### 🟢 Active Sessions")
        st.json(load_active_sessions())
    st.stop()


# ==========================================
# 3. AUTH FLOW (STRICT & ROBUST)
# ==========================================
# Logo Header
c1, c2, c3 = st.columns([1, 2, 1])
with c2:
    try: st.image("logo.png", width=150)
    except: pass

st.title("🇰🇭 Khmer AI Voice Pro (Edge)")
cm = stx.CookieManager(key="mgr")

if "auth" not in st.session_state:
    st.session_state.auth = False

# --- Auto Login ---
cookie_key = cm.get("auth_key")
cookie_token = cm.get("session_token")

if not st.session_state.auth and cookie_key and cookie_token:
    status, days = check_access_key(cookie_key)
    server_token = get_server_token(cookie_key)
    
    if status == "Valid" and cookie_token == server_token:
        st.session_state.auth = True
        st.session_state.ukey = cookie_key
        st.session_state.days = days
        st.session_state.my_token = cookie_token
        time.sleep(0.1)
        st.rerun()

# --- Login Form ---
if not st.session_state.auth:
    st.markdown("### 🔐 Login Required")
    with st.form("login"):
        key_input = st.text_input("Access Key", type="password")
        remember = st.checkbox("Remember me", value=True)
        btn = st.form_submit_button("Login", type="primary")

    if btn:
        status, days = check_access_key(key_input)
        if status != "Valid":
            st.error(status)
            st.stop()

        if is_key_already_in_use(key_input):
            st.error("⛔ Access Denied!")
            st.warning("Key នេះកំពុង Online នៅ Browser ផ្សេង។ សូម Logout ពីកន្លែងចាស់សិន។")
            st.stop()

        new_token = create_session(key_input)
        st.session_state.auth = True
        st.session_state.ukey = key_input
        st.session_state.days = days
        st.session_state.my_token = new_token
        
        if remember:
            exp = datetime.datetime.now() + datetime.timedelta(days=30)
            cm.set("auth_key", key_input, expires_at=exp, key="sk")
            cm.set("session_token", new_token, expires_at=exp, key="st")
            time.sleep(1.0) # Delay for Termux
        
        st.success("Login Success!")
        st.rerun()
    st.stop()


# ==========================================
# 4. SECURITY CHECK
# ==========================================
if st.session_state.auth:
    current_token = get_server_token(st.session_state.ukey)
    if current_token != st.session_state.my_token:
        st.error("🚨 Session Expired / Logged out.")
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
    if st.button("Logout", type="primary"):
        delete_session(st.session_state.ukey)
        st.session_state.clear()
        cm.delete("auth_key")
        cm.delete("session_token")
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
    preset_name_input = st.text_input("Name", placeholder="Ex: Boy")
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

tab1, tab2, tab3 = st.tabs(["📝 Text Mode", "🎬 SRT Multi-Speaker", "🤖 Gemini Translator"])

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

# --- TAB 2: SRT EDITOR (IMPROVED) ---
with tab2:
    srt_file = st.file_uploader("Upload SRT", type="srt", key="srt_up")
    
    if srt_file:
        # Load SRT if new file uploaded
        if "srt_lines" not in st.session_state or st.session_state.get("last_srt") != srt_file.name:
            content = srt_file.getvalue().decode("utf-8")
            st.session_state.srt_lines = parse_srt(content)
            st.session_state.last_srt = srt_file.name
            st.session_state.line_settings = []
            # Initialize settings for each line with Global Settings
            for _ in st.session_state.srt_lines:
                st.session_state.line_settings.append({
                    "voice": st.session_state.g_voice, 
                    "rate": st.session_state.g_rate, 
                    "pitch": st.session_state.g_pitch, 
                    "slot": None
                })
        
        # --- GLOBAL PRESET APPLY ---
        st.markdown("#### 🎭 Apply Preset to All")
        preset_opts = ["-- Select Preset --"]
        preset_map = {}
        for i in range(1, 7):
            pd = get_user_preset(st.session_state.ukey, i)
            if pd:
                name = f"Slot {i}: {pd.get('name', f'Slot {i}')}"
                preset_opts.append(name)
                preset_map[name] = (i, pd)
        
        c_all_1, c_all_2 = st.columns([3, 1])
        srt_def = c_all_1.selectbox("Choose Preset", preset_opts, label_visibility="collapsed")
        if c_all_2.button("Apply to All Lines"):
            if srt_def in preset_map:
                sid, _ = preset_map[srt_def]
                for idx in range(len(st.session_state.srt_lines)): 
                    apply_preset_to_line(st.session_state.ukey, idx, sid)
                st.rerun()

        # --- SRT LINE EDITOR ---
        st.divider()
        with st.container(height=600):
            for idx, sub in enumerate(st.session_state.srt_lines):
                cur = st.session_state.line_settings[idx]
                s = cur["slot"]
                cls = f" slot-{s}" if s else ""
                p_html = f"<span class='preset-tag'>{get_user_preset(st.session_state.ukey, s)['name']}</span>" if s else ""
                
                # Frame SRT Display
                st.markdown(
                    f"<div class='srt-box{cls}'>"
                    f"<b>#{idx+1}</b> <small>{sub['start']}ms</small> {p_html}<br>"
                    f"{sub['text']}"
                    f"</div>", 
                    unsafe_allow_html=True
                )
                
                # Controls Row
                c1, c2, c3, c4 = st.columns([2, 1, 1, 4])
                
                # Voice/Rate/Pitch Controls
                v = c1.selectbox("V", list(VOICES.keys()), index=list(VOICES.keys()).index(cur["voice"]), key=f"v{idx}", label_visibility="collapsed")
                r = c2.number_input("R", -50, 50, value=cur["rate"], key=f"r{idx}", label_visibility="collapsed")
                p = c3.number_input("P", -50, 50, value=cur["pitch"], key=f"p{idx}", label_visibility="collapsed")
                
                # Update State
                st.session_state.line_settings[idx].update({"voice": v, "rate": r, "pitch": p})
                
                # Preset Buttons
                with c4:
                    cols = st.columns(6)
                    for i in range(1, 7):
                        pd = get_user_preset(st.session_state.ukey, i)
                        # Show short name or "-"
                        lbl = pd['name'][:3] if pd else "-"
                        # Highlight active preset
                        kind = "primary" if s == i else "secondary"
                        
                        if cols[i-1].button(lbl, key=f"b{idx}{i}", type=kind):
                            apply_preset_to_line(st.session_state.ukey, idx, i)
                            st.rerun()

        # --- GENERATE FULL AUDIO ---
        if st.button("🚀 Generate Full Audio (Strict Sync)", type="primary"):
            progress = st.progress(0)
            status = st.empty()
            
            try:
                # Calculate total duration
                last_end = st.session_state.srt_lines[-1]["start"] + 10000 
                final_mix = AudioSegment.silent(duration=last_end)
                
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                for i, sub in enumerate(st.session_state.srt_lines):
                    status.text(f"Processing line {i+1}/{len(st.session_state.srt_lines)}...")
                    
                    # Use specific settings for this line
                    sett = st.session_state.line_settings[i]
                    
                    raw_path = loop.run_until_complete(
                        gen_edge(sub["text"], VOICES[sett["voice"]], sett["rate"], sett["pitch"])
                    )
                    
                    clip = AudioSegment.from_file(raw_path)
                    
                    # Add to timeline at specific timestamp
                    final_mix = final_mix.overlay(clip, position=sub["start"])
                    
                    try: os.remove(raw_path)
                    except: pass
                    
                    progress.progress((i+1)/len(st.session_state.srt_lines))
                
                status.success("Generation Complete!")
                buf = io.BytesIO()
                final_mix.export(buf, format="mp3")
                buf.seek(0)
                st.audio(buf)
                st.download_button("Download Conversation", buf, "conversation.mp3", "audio/mp3")
                
            except Exception as e:
                status.error(f"Error: {e}")

# --- TAB 3: GEMINI TRANSLATOR (NEW) ---
with tab3:
    st.subheader("🤖 Gemini Translator (SRT -> Khmer)")
    
    api_key_input = st.text_input("Enter Gemini API Key", type="password", placeholder="AIzaSy...")
    
    if "srt_lines" not in st.session_state or not st.session_state.srt_lines:
        st.warning("⚠️ Please upload an SRT file in Tab 2 first.")
    else:
        st.info(f"Ready to translate {len(st.session_state.srt_lines)} lines.")
        
        if st.button("Start Translate to Khmer", type="primary"):
            if not api_key_input:
                st.error("Please enter API Key.")
            else:
                genai.configure(api_key=api_key_input)
                model = genai.GenerativeModel('gemini-1.5-flash')
                
                prog_bar = st.progress(0)
                status_text = st.empty()
                
                try:
                    for i, sub in enumerate(st.session_state.srt_lines):
                        status_text.text(f"Translating line {i+1}...")
                        
                        original_text = sub['text']
                        
                        # Prompt Engineering for Natural Khmer
                        prompt = f"Translate this text to natural, conversational Khmer (Cambodian) suitable for movie dubbing. Only return the Khmer translation, no explanations:\n\n'{original_text}'"
                        
                        response = model.generate_content(prompt)
                        translated_text = response.text.strip()
                        
                        # Update the SRT line in session state
                        st.session_state.srt_lines[i]['text'] = translated_text
                        
                        prog_bar.progress((i+1)/len(st.session_state.srt_lines))
                        time.sleep(0.5) # Avoid hitting rate limits too fast
                    
                    status_text.success("Translation Complete! Go back to Tab 2 to edit/generate.")
                    st.toast("Translation Done!")
                    time.sleep(1)
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"Translation Error: {e}")
