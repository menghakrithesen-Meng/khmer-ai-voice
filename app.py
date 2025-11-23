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
    
    /* Hide Number Input +/- */
    button[data-testid="stNumberInputStepDown"], button[data-testid="stNumberInputStepUp"] { display: none; }
    div[data-testid="stNumberInput"] input { text-align: center; }

    /* Preset Buttons */
    div[data-testid="column"] button {
        padding: 0px 2px !important;
        font-size: 11px !important;
        min-height: 32px !important;
        width: 100%;
        overflow: hidden;
        text-overflow: ellipsis;
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
# 1. FUNCTIONS
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
    left = (start + datetime.timedelta(days=k_data["duration_days"]) - datetime.date.today()).days
    return ("Expired", 0) if left < 0 else ("Valid", left)

def save_user_preset(user_key, slot, data, name):
    db = load_json(PRESETS_FILE)
    if user_key not in db: db[user_key] = {}
    data['name'] = name if name else f"{slot}"
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

def srt_time_to_ms(time_str):
    try:
        start, end = time_str.split(' --> ')
        h,m,s = start.replace(',', '.').split(':')
        return int(float(h)*3600000 + float(m)*60000 + float(s)*1000)
    except: return 0

def parse_srt(content):
    subs = []
    blocks = re.split(r'\n\s*\n', content.strip())
    for b in blocks:
        lines = b.strip().split('\n')
        if len(lines) >= 3:
            time_idx = 1
            if '-->' not in lines[1]:
                for i, l in enumerate(lines):
                    if '-->' in l: 
                        time_idx = i; break
            start_ms = srt_time_to_ms(lines[time_idx])
            text = " ".join(lines[time_idx+1:])
            text = re.sub(r'<[^>]+>', '', text)
            subs.append({"start": start_ms, "text": text})
    return subs

# ==========================================
# 2. MAIN UI
# ==========================================
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

st.title("🇰🇭 Khmer AI Voice Pro (Edge)")
cm = get_cookie_manager()

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

# --- VOICES ---
VOICES = {
    "Sreymom (Khmer)": "km-KH-SreymomNeural",
    "Piseth (Khmer)": "km-KH-PisethNeural",
    "Emma (English)": "en-US-EmmaMultilingualNeural",
    "Xiaoxiao (Chinese)": "zh-CN-XiaoxiaoNeural"
}

# --- SIDEBAR ---
with st.sidebar:
    st.success(f"✅ Active: {st.session_state.days} Days")
    if st.button("Logout"): cm.delete("auth_key"); st.session_state.clear(); st.rerun()
    
    st.divider()
    st.subheader("⚙️ Global Settings")
    if "g_voice" not in st.session_state:
        st.session_state.g_voice = "Sreymom (Khmer)"
        st.session_state.g_rate = 0
        st.session_state.g_pitch = 0
    
    st.session_state.g_voice = st.selectbox("Voice", list(VOICES.keys()), index=list(VOICES.keys()).index(st.session_state.g_voice))
    st.session_state.g_rate = st.slider("Speed", -50, 50, value=st.session_state.g_rate)
    st.session_state.g_pitch = st.slider("Pitch", -50, 50, value=st.session_state.g_pitch)
    pad_sel = st.number_input("Padding (ms)", value=80)

    st.divider()
    st.subheader("💾 6 Presets")
    p_name = st.text_input("Name", placeholder="Ex: Boy")
    for i in range(1, 7):
        c1, c2 = st.columns([3, 1])
        sp = get_user_preset(st.session_state.ukey, i)
        bn = sp['name'] if sp else f"Slot {i}"
        if c1.button(f"📂 {bn}", key=f"l{i}", use_container_width=True):
            if sp:
                st.session_state.g_voice = sp['voice']
                st.session_state.g_rate = sp['rate']
                st.session_state.g_pitch = sp['pitch']
                st.rerun()
        if c2.button("💾", key=f"s{i}"):
            save_user_preset(st.session_state.ukey, i, {"voice": st.session_state.g_voice, "rate": st.session_state.g_rate, "pitch": st.session_state.g_pitch}, p_name)
            st.toast(f"Saved {p_name}!")
            time.sleep(0.5)
            st.rerun()

# --- TABS ---
tab1, tab2, tab3 = st.tabs(["📝 Text Mode", "🎬 SRT Multi-Speaker", "🤖 SRT Translator"])

with tab1:
    txt = st.text_area("Input Text...", height=150)
    if st.button("Generate Audio", type="primary"):
        if txt:
            with st.spinner("Generating..."):
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    raw = loop.run_until_complete(gen_edge(txt, VOICES[st.session_state.g_voice], st.session_state.g_rate, st.session_state.g_pitch))
                    final = process_audio(raw, pad_sel)
                    buf = io.BytesIO()
                    final.export(buf, format="mp3")
                    st.audio(buf); st.download_button("Download", buf, "audio.mp3")
                except Exception as e: st.error(f"Error: {e}")

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
                    "voice": st.session_state.g_voice,
                    "rate": st.session_state.g_rate,
                    "pitch": st.session_state.g_pitch,
                    "active_slot": None
                })

        with st.container(height=600):
            for idx, sub in enumerate(st.session_state.srt_lines):
                st.markdown(f"<div class='srt-box'><b>#{idx+1}</b> <small>Start: {sub['start']}ms</small><br>{sub['text']}</div>", unsafe_allow_html=True)
                c_voice, c_rate, c_pitch, c_presets = st.columns([2, 1, 1, 4])
                
                cur = st.session_state.line_settings[idx]
                new_v = c_voice.selectbox("V", list(VOICES.keys()), index=list(VOICES.keys()).index(cur['voice']), key=f"v_{idx}", label_visibility="collapsed")
                new_r = c_rate.number_input("R", -50, 50, value=cur['rate'], key=f"r_{idx}", label_visibility="collapsed")
                new_p = c_pitch.number_input("P", -50, 50, value=cur['pitch'], key=f"p_{idx}", label_visibility="collapsed")
                
                # Manual Change -> Reset active slot
                active = cur['active_slot']
                if new_v != cur['voice'] or new_r != cur['rate'] or new_p != cur['pitch']:
                    active = None
                
                st.session_state.line_settings[idx] = {"voice": new_v, "rate": new_r, "pitch": new_p, "active_slot": active}

                with c_presets:
                    cols = st.columns(6)
                    for slot_id in range(1, 7):
                        pd = get_user_preset(st.session_state.ukey, slot_id)
                        label = pd['name'] if pd and pd.get('name') else str(slot_id)
                        if len(label) > 4: label = label[:4]
                        
                        # Button Color Logic
                        b_type = "primary" if active == slot_id else "secondary"
                        
                        if cols[slot_id-1].button(label, key=f"btn_{idx}_{slot_id}", type=b_type, help=f"Apply {label}"):
                            if pd:
                                st.session_state.line_settings[idx] = {
                                    "voice": pd['voice'],
                                    "rate": pd['rate'],
                                    "pitch": pd['pitch'],
                                    "active_slot": slot_id
                                }
                                st.rerun()

        if st.button("🚀 Generate Full Audio (Synced)", type="primary"):
            progress = st.progress(0); status = st.empty()
            final_mix = AudioSegment.silent(duration=0)
            curr_time = 0
            
            try:
                loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
                for i, sub in enumerate(st.session_state.srt_lines):
                    status.text(f"Processing line {i+1}/{len(st.session_state.srt_lines)}...")
                    s = st.session_state.line_settings[i]
                    raw = loop.run_until_complete(gen_edge(sub['text'], VOICES[s['voice']], s['rate'], s['pitch']))
                    clip = AudioSegment.from_file(raw)
                    
                    # SYNC LOGIC (STRICT)
                    target = sub['start']
                    if target > curr_time:
                        final_mix += AudioSegment.silent(duration=target - curr_time)
                        curr_time = target
                    
                    final_mix += clip
                    curr_time += len(clip)
                    try: os.remove(raw)
                    except: pass
                    progress.progress((i+1)/len(st.session_state.srt_lines))
                
                status.success("Done!"); buf = io.BytesIO()
                final_mix.export(buf, format="mp3")
                st.audio(buf); st.download_button("Download", buf, "conversation.mp3")
            except Exception as e: st.error(f"Error: {e}")

with tab3:
    st.subheader("Gemini Translator"); st.info("Coming Soon...")
