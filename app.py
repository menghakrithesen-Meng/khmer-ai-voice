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
import re
import extra_streamlit_components as stx 

# ==========================================
# 0. CONFIG & SETUP
# ==========================================
st.set_page_config(page_title="Khmer AI Voice Pro", page_icon="🎙️", layout="wide")

KEYS_FILE = "web_keys.json"
PRESETS_FILE = "user_presets.json"

# 🎨 CUSTOM CSS
st.markdown("""
<style>
    .stApp { background: linear-gradient(to right, #0f172a, #1e293b); color: white; }
    section[data-testid="stSidebar"] { background-color: #111827; border-right: 1px solid #374151; }
    
    /* Small Buttons for Presets */
    div[data-testid="column"] button {
        padding: 0px 5px !important;
        font-size: 12px !important;
        min-height: 30px !important;
    }
    
    /* SRT Box */
    .srt-box { 
        background: #1e293b; border: 1px solid #334155; 
        border-radius: 6px; padding: 10px; margin-bottom: 5px; 
        border-left: 4px solid #8b5cf6; 
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 1. DATABASE & FUNCTIONS
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

# --- AUTH ---
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

# --- PRESETS SYSTEM ---
def save_user_preset(user_key, slot, data, name):
    db = load_json(PRESETS_FILE)
    if user_key not in db: db[user_key] = {}
    data['name'] = name if name else f"Preset {slot}"
    db[user_key][str(slot)] = data
    save_json(PRESETS_FILE, db)

def get_user_preset(user_key, slot):
    db = load_json(PRESETS_FILE)
    return db.get(user_key, {}).get(str(slot), None)

# --- AUDIO ENGINE ---
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
    except: return AudioSegment.from_file(file_path)

# --- SRT PARSER ---
def parse_srt(content):
    subs = []
    blocks = re.split(r'\n\s*\n', content.strip())
    for b in blocks:
        lines = b.strip().split('\n')
        if len(lines) >= 3:
            # Simple parse: Index, Time, Text
            time_str = lines[1]
            text = " ".join(lines[2:])
            # Calculate duration ms (approx)
            try:
                start, end = time_str.split(' --> ')
                h,m,s = start.replace(',', '.').split(':')
                start_ms = int(float(h)*3600000 + float(m)*60000 + float(s)*1000)
                h,m,s = end.replace(',', '.').split(':')
                end_ms = int(float(h)*3600000 + float(m)*60000 + float(s)*1000)
                duration = end_ms - start_ms
            except: 
                start_ms = 0
                duration = 2000 # Default 2s
            
            subs.append({"start": start_ms, "duration": duration, "text": text})
    return subs

# ==========================================
# 2. MAIN UI
# ==========================================
# ADMIN CHECK
if st.query_params.get("view") == "admin":
    st.title("🔐 Admin Panel")
    if st.text_input("Password", type="password") == "admin123":
        days = st.number_input("Days", 30)
        if st.button("Generate Key"):
            k = "KHM-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            db = load_json(KEYS_FILE)
            db[k] = {"duration_days": days, "activated_date": None, "status": "active"}
            save_json(KEYS_FILE, db)
            st.success(f"Key: {k}")
        st.json(load_json(KEYS_FILE))
    st.stop()

# APP START
st.title("🇰🇭 Khmer AI Voice Pro (Edge)")
cm = get_cookie_manager()

# AUTH
if 'auth' not in st.session_state:
    st.session_state.auth = False
    ck = cm.get("auth_key")
    if ck:
        s, d = check_access_key(ck)
        if s == "Valid": st.session_state.auth = True; st.session_state.ukey = ck; st.session_state.days = d

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

# --- VOICES MAP ---
VOICES = {
    "Sreymom (Khmer)": "km-KH-SreymomNeural",
    "Piseth (Khmer)": "km-KH-PisethNeural",
    "Emma (English)": "en-US-EmmaMultilingualNeural",
    "Xiaoxiao (Chinese)": "zh-CN-XiaoxiaoNeural"
}

# --- SIDEBAR SETTINGS & PRESETS ---
with st.sidebar:
    st.success(f"✅ Active: {st.session_state.days} Days")
    if st.button("Logout"): cm.delete("auth_key"); st.session_state.clear(); st.rerun()
    
    st.divider()
    st.subheader("⚙️ Global Settings")
    
    # Init Session Vars
    if "g_voice" not in st.session_state: st.session_state.g_voice = "Sreymom (Khmer)"
    if "g_rate" not in st.session_state: st.session_state.g_rate = 0
    if "g_pitch" not in st.session_state: st.session_state.g_pitch = 0
    
    # Inputs
    v_sel = st.selectbox("Voice", list(VOICES.keys()), index=list(VOICES.keys()).index(st.session_state.g_voice))
    r_sel = st.slider("Speed", -50, 50, value=st.session_state.g_rate)
    p_sel = st.slider("Pitch", -50, 50, value=st.session_state.g_pitch)
    pad_sel = st.number_input("Padding (ms)", value=80)
    
    # Update Session
    st.session_state.g_voice = v_sel
    st.session_state.g_rate = r_sel
    st.session_state.g_pitch = p_sel

    st.divider()
    st.subheader("💾 6 Presets (Save/Load)")
    preset_name_input = st.text_input("Preset Name", placeholder="Ex: Story Voice")
    
    # 6 Slots Grid
    for i in range(1, 7):
        c1, c2 = st.columns([3, 1])
        # Load Logic
        saved_p = get_user_preset(st.session_state.ukey, i)
        btn_name = saved_p['name'] if saved_p else f"Slot {i}"
        
        if c1.button(f"📂 {btn_name}", key=f"load_{i}", use_container_width=True):
            if saved_p:
                st.session_state.g_voice = saved_p['voice']
                st.session_state.g_rate = saved_p['rate']
                st.session_state.g_pitch = saved_p['pitch']
                st.rerun()
        
        # Save Logic
        if c2.button("💾", key=f"save_{i}"):
            data = {"voice": v_sel, "rate": r_sel, "pitch": p_sel}
            save_user_preset(st.session_state.ukey, i, data, preset_name_input)
            st.toast(f"Saved to Slot {i}!")
            time.sleep(0.5)
            st.rerun()

# --- MAIN TABS ---
tab1, tab2, tab3 = st.tabs(["📝 Text Mode", "🎬 SRT Multi-Speaker", "🤖 SRT Translator (Gemini)"])

# 1. TEXT MODE
with tab1:
    txt = st.text_area("Input Text...", height=150)
    if st.button("Generate Text Audio", type="primary"):
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
                except Exception as e: st.error(f"Error: {e}")

# 2. SRT MULTI-SPEAKER (THE BIG UPDATE)
with tab2:
    st.info("Upload SRT -> Customize each line -> Generate Full Audio")
    srt_file = st.file_uploader("Upload SRT", type="srt", key="srt_up")
    
    if srt_file:
        # Parse & Init State
        if "srt_lines" not in st.session_state or st.session_state.get("last_srt") != srt_file.name:
            content = srt_file.getvalue().decode("utf-8")
            st.session_state.srt_lines = parse_srt(content)
            st.session_state.last_srt = srt_file.name
            # Init settings for each line (Default to Global)
            st.session_state.line_settings = []
            for _ in st.session_state.srt_lines:
                st.session_state.line_settings.append({
                    "voice": st.session_state.g_voice,
                    "rate": st.session_state.g_rate,
                    "pitch": st.session_state.g_pitch
                })

        # --- DISPLAY LINES & CONTROLS ---
        with st.container(height=600):
            for idx, sub in enumerate(st.session_state.srt_lines):
                # Display Text
                st.markdown(f"<div class='srt-box'><b>#{idx+1}</b> <small>({sub['start']}ms)</small><br>{sub['text']}</div>", unsafe_allow_html=True)
                
                # Controls Row
                c_voice, c_rate, c_pitch, c_presets = st.columns([2, 1, 1, 3])
                
                # Unique Keys for Widgets
                k_v = f"v_{idx}"
                k_r = f"r_{idx}"
                k_p = f"p_{idx}"
                
                current_s = st.session_state.line_settings[idx]
                
                # Update State on Change
                new_v = c_voice.selectbox("Voice", list(VOICES.keys()), index=list(VOICES.keys()).index(current_s['voice']), key=k_v, label_visibility="collapsed")
                new_r = c_rate.number_input("Rate", -50, 50, value=current_s['rate'], key=k_r, label_visibility="collapsed")
                new_p = c_pitch.number_input("Pitch", -50, 50, value=current_s['pitch'], key=k_p, label_visibility="collapsed")
                
                # Update the state list
                st.session_state.line_settings[idx] = {"voice": new_v, "rate": new_r, "pitch": new_p}

                # PRESET BUTTONS (1-6)
                with c_presets:
                    cols = st.columns(6)
                    for slot_id in range(1, 7):
                        # Load preset name for tooltip
                        p_data = get_user_preset(st.session_state.ukey, slot_id)
                        p_label = str(slot_id)
                        p_help = p_data['name'] if p_data else "Empty"
                        
                        if cols[slot_id-1].button(p_label, key=f"btn_{idx}_{slot_id}", help=p_help):
                            if p_data:
                                st.session_state.line_settings[idx] = {
                                    "voice": p_data['voice'],
                                    "rate": p_data['rate'],
                                    "pitch": p_data['pitch']
                                }
                                st.rerun()

        # --- GENERATE FULL AUDIO ---
        if st.button("🚀 Generate Full Conversation", type="primary"):
            progress = st.progress(0)
            status = st.empty()
            
            final_mix = AudioSegment.silent(duration=0)
            last_end = 0
            
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                for i, sub in enumerate(st.session_state.srt_lines):
                    status.text(f"Processing line {i+1}/{len(st.session_state.srt_lines)}")
                    
                    # Get settings for this line
                    s = st.session_state.line_settings[i]
                    
                    # Generate
                    raw_path = loop.run_until_complete(gen_edge(sub['text'], VOICES[s['voice']], s['rate'], s['pitch']))
                    clip = AudioSegment.from_file(raw_path)
                    
                    # Sync Logic (Simple Append)
                    # If you want precise timing based on SRT, we need to insert silence
                    silence_duration = sub['start'] - last_end
                    if silence_duration > 0:
                        final_mix += AudioSegment.silent(duration=silence_duration)
                    
                    final_mix += clip
                    last_end = sub['start'] + len(clip) # Update cursor
                    
                    # Cleanup
                    try: os.remove(raw_path)
                    except: pass
                    
                    progress.progress((i+1)/len(st.session_state.srt_lines))
                
                status.success("Conversation Generated!")
                buf = io.BytesIO()
                final_mix.export(buf, format="mp3")
                st.audio(buf)
                st.download_button("Download Conversation", buf, "conversation.mp3", "audio/mp3", use_container_width=True)
                
            except Exception as e:
                st.error(f"Error during generation: {e}")

# 3. SRT TRANSLATOR (GEMINI)
with tab3:
    st.subheader("Gemini Translator (SRT)")
    api_key = st.text_input("Enter Gemini API Key", type="password")
    st.caption("Coming soon: Full translation logic here.")
    # (Add your Gemini Translation Logic here if you have the specific code for it)
