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
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_json(path, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def get_cookie_manager():
    if 'cookie_manager' not in st.session_state:
        st.session_state.cookie_manager = stx.CookieManager()
    return st.session_state.cookie_manager

# --- AUTH ---
def check_access_key(user_key):
    keys_db = load_json(KEYS_FILE)
    if user_key not in keys_db:
        return "Invalid Key", 0
    k_data = keys_db[user_key]
    if k_data["status"] != "active":
        return "Key Disabled", 0
    
    if not k_data.get("activated_date"):
        k_data["activated_date"] = str(datetime.date.today())
        save_json(KEYS_FILE, keys_db)
    
    start = datetime.date.fromisoformat(k_data["activated_date"])
    exp = start + datetime.timedelta(days=k_data["duration_days"])
    left = (exp - datetime.date.today()).days
    
    if left < 0:
        return "Expired", 0
    return "Valid", left

# --- PRESETS ---
def save_user_preset(user_key, slot, data, name):
    db = load_json(PRESETS_FILE)
    if user_key not in db:
        db[user_key] = {}
    data['name'] = name if name else f"{slot}"
    db[user_key][str(slot)] = data
    save_json(PRESETS_FILE, db)

def get_user_preset(user_key, slot):
    db = load_json(PRESETS_FILE)
    return db.get(user_key, {}).get(str(slot), None)

# 🔧 Apply preset to one SRT line (voice + rate + pitch + remember slot + sync widgets)
def apply_preset_to_line(user_key, line_index, slot_id):
    pd = get_user_preset(user_key, slot_id)
    if not pd:
        return
    
    # Update logic state
    st.session_state.line_settings[line_index] = {
        "voice": pd["voice"],
        "rate": pd["rate"],
        "pitch": pd["pitch"],
        "slot": slot_id,   # remember which preset slot (for color/label)
    }

    # Sync widget state so UI (selectbox / number_input) ក្លាយតាម preset
    st.session_state[f"v_{line_index}"] = pd["voice"]
    st.session_state[f"r_{line_index}"] = pd["rate"]
    st.session_state[f"p_{line_index}"] = pd["pitch"]

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
    except Exception:
        return AudioSegment.from_file(file_path)

# --- SRT PARSER ---
def srt_time_to_ms(time_str):
    try:
        start, end = time_str.split(' --> ')
        h, m, s = start.replace(',', '.').split(':')
        start_ms = int(float(h) * 3600000 + float(m) * 60000 + float(s) * 1000)
        return start_ms
    except Exception:
        return 0

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
                        time_idx = i
                        break
            start_ms = srt_time_to_ms(lines[time_idx])
            text = " ".join(lines[time_idx+1:])
            text = re.sub(r'<[^>]+>', '', text)
            if text.strip():
                subs.append({"start": start_ms, "text": text})
    return subs

# ==========================================
# 2. MAIN APP UI
# ==========================================
# ADMIN
if st.query_params.get("view") == "admin":
    st.title("🔐 Admin Panel")
    pwd = st.text_input("Password", type="password")
    if pwd == "admin123":
        days = st.number_input("Days", 30)
        if st.button("Generate Key"):
            k = "KHM-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            db = load_json(KEYS_FILE)
            db[k] = {"duration_days": days, "activated_date": None, "status": "active"}
            save_json(KEYS_FILE, db)
            st.success(f"Key: {k}")
        st.json(load_json(KEYS_FILE))
    st.stop()

# APP
st.title("🇰🇭 Khmer AI Voice Pro (Edge)")
cm = get_cookie_manager()

if 'auth' not in st.session_state:
    st.session_state.auth = False
    ck = cm.get("auth_key")
    if ck:
        s, d = check_access_key(ck)
        if s == "Valid":
            st.session_state.auth = True
            st.session_state.ukey = ck
            st.session_state.days = d

if not st.session_state.auth:
    key = st.text_input("🔑 Access Key", type="password")
    if st.button("Login"):
        s, d = check_access_key(key)
        if s == "Valid":
            st.session_state.auth = True
            st.session_state.ukey = key
            st.session_state.days = d
            cm.set("auth_key", key, expires_at=datetime.datetime.now() + datetime.timedelta(days=30))
            st.rerun()
        else:
            st.error(s)
    
    st.markdown("---")
    if st.button("🔐 Admin Login"):
        st.query_params["view"] = "admin"
        st.rerun()
    st.stop()

# VOICES
VOICES = {
    "Sreymom (Khmer)": "km-KH-SreymomNeural",
    "Piseth (Khmer)": "km-KH-PisethNeural",
    "Emma (English)": "en-US-EmmaMultilingualNeural",
    "Xiaoxiao (Chinese)": "zh-CN-XiaoxiaoNeural"
}

# --- SIDEBAR ---
with st.sidebar:
    st.success(f"✅ Active: {st.session_state.days} Days")
    if st.button("Logout"):
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
    
    v_sel = st.selectbox("Voice", list(VOICES.keys()),
                         index=list(VOICES.keys()).index(st.session_state.g_voice))
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
        btn_name = saved_p['name'] if saved_p else f"Slot {i}"
        
        if c1.button(f"📂 {btn_name}", key=f"load_{i}", use_container_width=True):
            if saved_p:
                st.session_state.g_voice = saved_p['voice']
                st.session_state.g_rate = saved_p['rate']
                st.session_state.g_pitch = saved_p['pitch']
                st.rerun()
        
        if c2.button("💾", key=f"save_{i}"):
            data = {"voice": v_sel, "rate": r_sel, "pitch": p_sel}
            save_user_preset(st.session_state.ukey, i, data, preset_name_input)
            st.toast(f"Saved {preset_name_input} to Slot {i}!")
            time.sleep(0.5)
            st.rerun()

# --- TABS ---
tab1, tab2, tab3 = st.tabs(["📝 Text Mode", "🎬 SRT Multi-Speaker", "🤖 SRT Translator"])

# 1. TEXT MODE
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
                    buf.seek(0)
                    st.audio(buf)
                    st.download_button("Download MP3", buf, "audio.mp3", "audio/mp3")
                except Exception as e:
                    st.error(f"Error: {e}")

# 2. SRT MULTI-SPEAKER
with tab2:
    st.info("SRT Mode: Adjust voice for each line. Audio will sync to SRT time.")
    srt_file = st.file_uploader("Upload SRT", type="srt", key="srt_up")
    
    if srt_file:
        # INIT SRT STATE
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
                    "slot": None,   # no preset yet
                })

        # 🎭 SRT DEFAULT PRESET (APPLY TO ALL)
        st.markdown("#### 🎭 SRT Default Preset")

        preset_options = ["-- No Preset --"]
        preset_map = {}
        for i in range(1, 7):
            pd = get_user_preset(st.session_state.ukey, i)
            if pd:
                name = f"Slot {i}: {pd.get('name', f'Slot {i}')}"
                preset_options.append(name)
                preset_map[name] = (i, pd)

        srt_default_preset = st.selectbox(
            "Choose preset to apply to ALL SRT lines (optional)",
            preset_options,
            key="srt_default_preset"
        )

        if st.button("Apply preset to all lines"):
            if srt_default_preset in preset_map:
                slot_id, pd = preset_map[srt_default_preset]
                for idx in range(len(st.session_state.srt_lines)):
                    apply_preset_to_line(st.session_state.ukey, idx, slot_id)
                st.success(f"Applied {srt_default_preset} to all lines ✅")
                st.rerun()
            else:
                st.warning("Please select a valid preset before applying.")

        # SRT LINE EDITOR (per-line preset + color)
        with st.container(height=600):
            for idx, sub in enumerate(st.session_state.srt_lines):
                cur = st.session_state.line_settings[idx]
                slot = cur.get("slot")

                # Border color & label follow "slot"
                slot_class = f" slot-{slot}" if slot else ""
                if slot:
                    pd = get_user_preset(st.session_state.ukey, slot)
                    preset_name = pd['name'] if (pd and pd.get('name')) else f"Slot {slot}"
                    preset_html = f"<span class='preset-tag'>Preset: {preset_name}</span>"
                else:
                    preset_html = ""

                st.markdown(
                    f"""
                    <div class='srt-box{slot_class}'>
                        <b>#{idx+1}</b> 
                        <small>Time: {sub['start']}ms</small>
                        {preset_html}<br>{sub['text']}
                    </div>
                    """,
                    unsafe_allow_html=True
                )

                c_voice, c_rate, c_pitch, c_presets = st.columns([2, 1, 1, 4])

                # Controls — use widget keys v_idx / r_idx / p_idx (state will be
                # overridden by st.session_state[...] when apply_preset_to_line is called)
                new_v = c_voice.selectbox(
                    "V",
                    list(VOICES.keys()),
                    index=list(VOICES.keys()).index(cur['voice']),
                    key=f"v_{idx}",
                    label_visibility="collapsed",
                )
                new_r = c_rate.number_input(
                    "R", -50, 50,
                    value=cur['rate'],
                    key=f"r_{idx}",
                    label_visibility="collapsed",
                )
                new_p = c_pitch.number_input(
                    "P", -50, 50,
                    value=cur['pitch'],
                    key=f"p_{idx}",
                    label_visibility="collapsed",
                )

                # Manual change → update voice/rate/pitch BUT keep slot (color/label not lost)
                st.session_state.line_settings[idx] = {
                    "voice": new_v,
                    "rate": new_r,
                    "pitch": new_p,
                    "slot": slot,
                }

                # Preset Buttons per line
                with c_presets:
                    cols = st.columns(6)
                    for slot_id in range(1, 7):
                        pd = get_user_preset(st.session_state.ukey, slot_id)
                        if pd:
                            full_name = pd.get("name", f"Slot {slot_id}")
                        else:
                            full_name = "-"

                        btn_label = full_name if len(full_name) <= 4 else full_name[:4]
                        b_type = "primary" if slot == slot_id else "secondary"

                        if cols[slot_id-1].button(
                            btn_label,
                            key=f"btn_{idx}_{slot_id}",
                            type=b_type,
                            help=f"Apply: {full_name}"
                        ):
                            if pd:
                                apply_preset_to_line(st.session_state.ukey, idx, slot_id)
                                st.rerun()

        # GENERATE FULL AUDIO
        if st.button("🚀 Generate Full Audio (Strict Sync)", type="primary"):
            progress = st.progress(0)
            status = st.empty()
            
            last_start = st.session_state.srt_lines[-1]['start']
            final_mix = AudioSegment.silent(duration=last_start + 10000)
            
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                for i, sub in enumerate(st.session_state.srt_lines):
                    status.text(f"Processing line {i+1}...")
                    s = st.session_state.line_settings[i]
                    
                    raw_path = loop.run_until_complete(
                        gen_edge(
                            sub['text'], 
                            VOICES[s['voice']], 
                            s['rate'], 
                            s['pitch']
                        )
                    )
                    clip = AudioSegment.from_file(raw_path)
                    final_mix = final_mix.overlay(clip, position=sub['start'])
                    
                    try:
                        os.remove(raw_path)
                    except OSError:
                        pass
                    progress.progress((i+1)/len(st.session_state.srt_lines))
                
                status.success("Done! Audio synced.")
                buf = io.BytesIO()
                final_mix.export(buf, format="mp3")
                buf.seek(0)
                st.audio(buf)
                st.download_button("Download Conversation", buf, "conversation.mp3", "audio/mp3")
            
            except Exception as e:
                st.error(f"Error: {e}")

# TAB 3
with tab3:
    st.subheader("Gemini Translator (SRT)")
    st.info("Coming Soon...")
