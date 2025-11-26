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
    /* Global App Style */
    .stApp { background: linear-gradient(to right, #0f172a, #1e293b); color: white; }
    section[data-testid="stSidebar"] { background-color: #111827; border-right: 1px solid #374151; }
    
    /* Hide Spinners */
    button[data-testid="stNumberInputStepDown"], button[data-testid="stNumberInputStepUp"] { display: none; }
    div[data-testid="stNumberInput"] input { text-align: center; }
    
    /* --- 🔥 TIGHT BUTTONS (NO GAP) --- */
    [data-testid="stHorizontalBlock"] { gap: 0px !important; }
    [data-testid="column"] { min-width: 0px !important; flex: 1 1 0% !important; padding: 0px !important; }
    
    /* Button Style (for column buttons like preset buttons) */
    div[data-testid="column"] button { 
        padding: 0px !important; 
        font-size: 11px !important; 
        font-weight: bold !important;
        min-height: 38px !important;
        width: 100% !important; 
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        border-radius: 0px !important;
        margin: 0px !important;
        border: 1px solid #334155 !important;
        border-left: none !important;
    }
    
    /* Fix Borders */
    div[data-testid="column"]:first-child button { border-left: 1px solid #334155 !important; border-radius: 4px 0 0 4px !important; }
    div[data-testid="column"]:last-child button { border-radius: 0 4px 4px 0 !important; }

    /* Active Button Color */
    div[data-testid="column"] button[kind="primary"] { 
        background-color: #ef4444 !important; color: white !important; border-color: #ef4444 !important;
    }
    
    /* --- TEXT AREA --- */
    .stTextArea textarea {
        background-color: #0f172a !important; color: #ffffff !important; font-size: 16px !important; border: 1px solid #475569 !important; border-radius: 6px !important;
    }

    /* --- SCROLLABLE LINE CONTAINER --- */
    .srt-container {
        background-color: #1e293b; padding: 10px; border-radius: 8px; border: 1px solid #334155; margin-bottom: 15px;
    }
    
    .status-line {
        font-size: 12px; color: #94a3b8; margin-bottom: 5px; display: flex; justify-content: space-between; align-items: center;
    }
    
    .preset-badge {
        background: #334155; color: #cbd5e1; padding: 2px 6px; border-radius: 4px; font-size: 10px; border: 1px solid #475569;
    }
    
    /* Generate Button Big & Visible */
    .stButton button { width: 100%; font-weight: bold; font-size: 16px; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 1. HELPER FUNCTIONS
# ==========================================
def load_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except:
        pass

def load_active_sessions():
    return load_json(ACTIVE_FILE)

def get_server_token(user_key):
    return load_active_sessions().get(user_key)

def is_key_active(user_key):
    return user_key in load_active_sessions()

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
    user_key = user_key.strip()
    if user_key not in keys_db:
        return "Invalid Key", 0
    k_data = keys_db[user_key]
    if k_data.get("status") != "active":
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

def apply_preset_to_line_callback(user_key, line_index, slot_id):
    pd = get_user_preset(user_key, slot_id)
    if not pd:
        return
    st.session_state.line_settings[line_index]["voice"] = pd["voice"]
    st.session_state.line_settings[line_index]["rate"] = pd["rate"]
    st.session_state.line_settings[line_index]["pitch"] = pd["pitch"]
    st.session_state.line_settings[line_index]["slot"] = slot_id
    st.session_state[f"v{line_index}"] = pd["voice"]
    st.session_state[f"r{line_index}"] = pd["rate"]
    st.session_state[f"p{line_index}"] = pd["pitch"]

def apply_preset_to_line_bulk(user_key, line_index, slot_id):
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
    rate_str = f"{rate:+d}%" if rate != 0 else "+0%"
    pitch_str = f"{pitch:+d}Hz" if pitch != 0 else "+0Hz"
    for attempt in range(3):
        try:
            file_path = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3").name
            communicate = edge_tts.Communicate(text, voice, rate=rate_str, pitch=pitch_str)
            await communicate.save(file_path)
            if os.path.getsize(file_path) > 0:
                return file_path
        except Exception as e:
            print(f"Retry {attempt+1}: {e}")
            time.sleep(1)
    raise Exception("Failed after 3 attempts.")

def process_audio(file_path, pad_ms):
    try:
        seg = AudioSegment.from_file(file_path)
        pad = AudioSegment.silent(duration=pad_ms)
        return pad + effects.normalize(seg) + pad
    except:
        return AudioSegment.from_file(file_path)

def srt_time_to_ms(time_str):
    try:
        start, _ = time_str.split(" --> ")
        h, m, s = start.replace(",", ".").split(":")
        return int(float(h) * 3600000 + float(m) * 60000 + float(s) * 1000)
    except:
        return 0

def parse_srt(content):
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    subs = []
    blocks = content.strip().split("\n\n")
    for b in blocks:
        lines = [l.strip() for l in b.split("\n") if l.strip()]
        if len(lines) < 2:
            continue
        time_idx = -1
        for i, l in enumerate(lines):
            if "-->" in l:
                time_idx = i
                break
        if time_idx != -1 and time_idx + 1 < len(lines):
            text = " ".join(lines[time_idx+1:])
            text = re.sub(r"<[^>]+>", "", text)
            if text:
                subs.append({"start": srt_time_to_ms(lines[time_idx]), "text": text})
    return subs

# ==========================================
# 2. AUTH & ADMIN
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
            k_kick = st.text_input("Kick Key")
            if st.button("Kick"):
                delete_session(k_kick)
                st.success("Kicked")
            if st.button("Reset ALL"):
                save_json(ACTIVE_FILE, {})
                st.success("Reset Done")
        st.write("Active Sessions")
        st.json(load_active_sessions())
    st.stop()

c1, c2, c3 = st.columns([1, 2, 1])
with c2:
    try:
        st.image("logo.png", width=150)
    except:
        pass

st.title("🇰🇭 Khmer AI Voice Pro (Edge)")
cm = stx.CookieManager(key="mgr")

if "auth" not in st.session_state:
    st.session_state.auth = False

# Auto Login
time.sleep(0.5)
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
        st.rerun()

# Login Form
if not st.session_state.auth:
    st.markdown("### 🔐 Login Required")
    with st.form("login"):
        key_input = st.text_input("Access Key", type="password")
        c1, c2 = st.columns(2)
        remember = c1.checkbox("Remember me", value=True)
        force_login = c2.checkbox("Force Login (Kick others)")
        btn = st.form_submit_button("Login", type="primary")

    if btn:
        key_input = key_input.strip()
        status, days = check_access_key(key_input)
        if status != "Valid":
            st.error(status)
            st.stop()
        if is_key_active(key_input) and not force_login:
            st.error("⛔ Key is active on another device.")
            st.warning("Check 'Force Login' to kick.")
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
            with st.spinner("🔐 Saving Login... (Wait 6s)"):
                time.sleep(6.0)
        
        st.success("Success!")
        st.rerun()
    st.stop()

if st.session_state.auth:
    if get_server_token(st.session_state.ukey) != st.session_state.my_token:
        st.error("🚨 Session Expired.")
        st.session_state.clear()
        cm.delete("auth_key")
        cm.delete("session_token")
        time.sleep(2)
        st.rerun()

# ==========================================
# 3. MAIN APP
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
        st.rerun()
        
    st.divider()
    st.subheader("⚙️ Settings")
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
    st.subheader("💾 Presets (Save Here)")
    preset_name_input = st.text_input("Name", placeholder="Ex: Boy")
    for i in range(1, 7):
        c1, c2 = st.columns([3, 1])
        saved_p = get_user_preset(st.session_state.ukey, i)
        btn_name = saved_p["name"] if saved_p else f"Slot {i}"
        with c1:
            if st.button(f"📂 {btn_name}", key=f"l{i}", use_container_width=True):
                if saved_p:
                    st.session_state.g_voice = saved_p["voice"]
                    st.session_state.g_rate = saved_p["rate"]
                    st.session_state.g_pitch = saved_p["pitch"]
                    st.rerun()
        with c2:
            if st.button("💾", key=f"s{i}", use_container_width=True):
                data = {"voice": v_sel, "rate": r_sel, "pitch": p_sel}
                save_user_preset(st.session_state.ukey, i, data, preset_name_input)
                st.toast(f"Saved Slot {i}!")
                time.sleep(0.5)
                st.rerun()

tab1, tab2 = st.tabs(["📝 Text Mode", "🎬 SRT Multi-Speaker"])

# ==========================================
# TAB 1: TEXT MODE
# ==========================================
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
                except Exception as e:
                    st.error(str(e))

# ==========================================
# TAB 2: SRT MULTI-SPEAKER
# ==========================================
with tab2:
    srt_file = st.file_uploader("Upload SRT", type="srt", key="srt_up")
    
    if srt_file is not None:
        if srt_file.size > 150 * 1024:
            st.error("⚠️ File too large! Max limit is 150KB.")
        else:
            if "srt_lines" not in st.session_state or st.session_state.get("last_srt") != srt_file.name:
                content = srt_file.getvalue().decode("utf-8")
                st.session_state.srt_lines = parse_srt(content)
                st.session_state.last_srt = srt_file.name
                st.session_state.line_settings = [
                    {
                        "voice": st.session_state.g_voice,
                        "rate": st.session_state.g_rate,
                        "pitch": st.session_state.g_pitch,
                        "slot": None,
                    }
                    for _ in st.session_state.srt_lines
                ]

            # 🔥 GENERATE BUTTON ON TOP
            gen_clicked = st.button("🚀 Generate Full Audio", type="primary")

            st.markdown("#### 🎭 Apply Preset to All")
            preset_opts = ["-- Select --"] + [
                f"Slot {i}: {get_user_preset(st.session_state.ukey, i).get('name', f'Slot {i}')}"
                for i in range(1, 7)
                if get_user_preset(st.session_state.ukey, i)
            ]
            preset_map = {
                f"Slot {i}: {get_user_preset(st.session_state.ukey, i).get('name', f'Slot {i}')}"
                : i
                for i in range(1, 7)
                if get_user_preset(st.session_state.ukey, i)
            }
            
            c_all_1, c_all_2 = st.columns([3, 1])
            srt_def = c_all_1.selectbox("Choose Preset", preset_opts, label_visibility="collapsed")
            if c_all_2.button("Apply All"):
                if srt_def in preset_map:
                    sid = preset_map[srt_def]
                    for idx in range(len(st.session_state.srt_lines)):
                        apply_preset_to_line_bulk(st.session_state.ukey, idx, sid)
                    st.rerun()

            st.divider()
            st.write("#### ✂️ Line Editor")

            # 🔥 FRAME WITH SCROLL (NO BORDER LINE ON TOP)
            with st.container(height=500):
                for idx, sub in enumerate(st.session_state.srt_lines):
                    cur = st.session_state.line_settings[idx]
                    s = cur["slot"]
                    
                    border_color = (
                        "#f97316" if s == 1 else
                        "#22c55e" if s == 2 else
                        "#3b82f6" if s == 3 else
                        "#e11d48" if s == 4 else
                        "#a855f7" if s == 5 else
                        "#facc15" if s == 6 else
                        "#64748b"
                    )
                    
                    st.markdown(
                        f"<div class='srt-container' style='border-left: 5px solid {border_color};'>",
                        unsafe_allow_html=True
                    )
                    
                    p_name = get_user_preset(st.session_state.ukey, s)['name'] if s else ""
                    st.markdown(
                        f"""<div class='status-line'>
                            <span><b>#{idx+1}</b> &nbsp; {sub['start']}ms</span>
                            <span class='preset-badge'>{p_name}</span>
                        </div>""",
                        unsafe_allow_html=True
                    )
                    
                    new_text = st.text_area(
                        label=f"hidden_{idx}",
                        value=sub['text'],
                        key=f"txt_{idx}",
                        height=70,
                        label_visibility="collapsed"
                    )
                    if new_text != st.session_state.srt_lines[idx]['text']:
                        st.session_state.srt_lines[idx]['text'] = new_text

                    # 🔄 Only Rate & Pitch in each line (Voice via preset)
                    c_rate, c_pitch = st.columns(2)
                    r = c_rate.number_input(
                        "R",
                        -50,
                        50,
                        value=cur["rate"],
                        key=f"r{idx}",
                        label_visibility="collapsed"
                    )
                    p = c_pitch.number_input(
                        "P",
                        -50,
                        50,
                        value=cur["pitch"],
                        key=f"p{idx}",
                        label_visibility="collapsed"
                    )
                    
                    st.session_state.line_settings[idx]["rate"] = r
                    st.session_state.line_settings[idx]["pitch"] = p
                    
                    st.markdown("<div style='margin-top:5px;'></div>", unsafe_allow_html=True)
                    
                    # 🔥 TIGHT PRESET BUTTONS (0 GAP)
                    cols = st.columns(6)
                    for i in range(1, 7):
                        pd = get_user_preset(st.session_state.ukey, i)
                        lbl = pd['name'][:5] if pd else str(i)
                        kind = "primary" if s == i else "secondary"
                        
                        cols[i-1].button(
                            lbl,
                            key=f"b{idx}{i}",
                            type=kind,
                            on_click=apply_preset_to_line_callback,
                            args=(st.session_state.ukey, idx, i)
                        )

                    st.markdown("</div>", unsafe_allow_html=True)

            # 🎧 GENERATE FULL AUDIO (logic)
            if gen_clicked:
                progress = st.progress(0)
                status = st.empty()
                try:
                    last_end = st.session_state.srt_lines[-1]["start"] + 10000
                    final_mix = AudioSegment.silent(duration=last_end)
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    for i, sub in enumerate(st.session_state.srt_lines):
                        status.text(f"Processing {i+1}/{len(st.session_state.srt_lines)}...")
                        sett = st.session_state.line_settings[i]
                        current_text = st.session_state.srt_lines[i]['text']
                        if not current_text.strip():
                            continue
                        raw_path = loop.run_until_complete(
                            gen_edge(current_text, VOICES[sett["voice"]], sett["rate"], sett["pitch"])
                        )
                        clip = AudioSegment.from_file(raw_path)
                        final_mix = final_mix.overlay(clip, position=sub["start"])
                        try:
                            os.remove(raw_path)
                        except:
                            pass
                        progress.progress((i + 1) / len(st.session_state.srt_lines))
                    status.success("Done!")
                    buf = io.BytesIO()
                    final_mix.export(buf, format="mp3")
                    buf.seek(0)
                    st.audio(buf)
                    st.download_button("Download Conversation", buf, "conversation.mp3", "audio/mp3")
                except Exception as e:
                    status.error(f"Error: {e}")
