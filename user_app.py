import streamlit as st
import asyncio
import edge_tts
from gtts import gTTS
from pydub import AudioSegment, effects
import tempfile
import os
import re
import io
import json
import datetime
import uuid
import time
import extra_streamlit_components as stx 

st.set_page_config(page_title="Khmer AI Voice Pro", page_icon="🎙️", layout="wide")

# ==========================================
# 🎨 CUSTOM CSS (FIXED COLORS & STYLES)
# ==========================================
st.markdown("""
<style>
    .stApp { background: linear-gradient(to right, #0f172a, #1e293b); color: white; }
    section[data-testid="stSidebar"] { background-color: #111827; border-right: 1px solid #374151; }
    
    /* Global Buttons */
    .stButton > button {
        border-radius: 6px; font-size: 13px;
        padding: 4px 10px; transition: 0.2s;
    }
    
    /* SRT Preset Buttons (Default: Dark Gray) */
    div[data-testid="column"] button[kind="secondary"] {
        background-color: #334155 !important; 
        border: 1px solid #475569 !important; 
        color: #cbd5e1 !important; 
        font-size: 11px !important;
        min-height: 32px; width: 100%;
        padding: 0px 2px !important;
    }
    div[data-testid="column"] button[kind="secondary"]:hover {
        background-color: #475569 !important; color: white !important;
    }

    /* Active Preset Buttons (Purple/Pink - When Selected) */
    div[data-testid="column"] button[kind="primary"] {
        background: linear-gradient(135deg, #ec4899, #8b5cf6) !important; 
        border: 1px solid #f472b6 !important;
        color: white !important;
        font-weight: bold !important;
        box-shadow: 0 0 8px rgba(236, 72, 153, 0.6);
    }

    /* Input Fields */
    .stTextInput>div>div>input, .stSelectbox>div>div>div, .stNumberInput>div>div>input, .stTextArea>div>div>textarea {
        background-color: #1f2937; color: white; border-radius: 4px; border: 1px solid #374151; min-height: 35px;
    }
    
    /* SRT Box Styling */
    .srt-box {
        background: #1e293b; border: 1px solid #334155; border-radius: 6px; 
        padding: 8px; margin-bottom: 2px; border-left: 3px solid #8b5cf6;
        font-size: 14px;
    }
    .srt-row-container {
        padding-bottom: 10px; border-bottom: 1px solid #334155; margin-bottom: 10px;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 1. DATA & CONFIG
# ==========================================
KEYS_FILE = "web_keys.json"
PRESETS_FILE = "user_presets.json"

def load_json(path):
    if not os.path.exists(path): return {}
    try:
        with open(path, "r") as f: return json.load(f)
    except: return {}

def save_json(path, data):
    try:
        with open(path, "w") as f: json.dump(data, f, indent=2)
    except: pass

# --- Presets ---
def save_user_preset(user_key, slot, settings, name):
    data = load_json(PRESETS_FILE)
    if user_key not in data: data[user_key] = {}
    settings['name'] = name if name else f"S{slot}"
    data[user_key][str(slot)] = settings
    save_json(PRESETS_FILE, data)

def get_user_preset(user_key, slot):
    data = load_json(PRESETS_FILE)
    return data.get(user_key, {}).get(str(slot), None)

# --- Access Control ---
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

def check_access_key(user_key, device_id):
    keys_db = load_json(KEYS_FILE)
    if user_key not in keys_db: return "Invalid Key", 0
    k_data = keys_db[user_key]
    if k_data["status"] != "active": return "Key is disabled.", 0

    if not k_data.get("bound_device"):
        k_data["bound_device"] = device_id
        k_data["activated_date"] = str(datetime.date.today())
        save_json(KEYS_FILE, keys_db)
        return "Valid", k_data["duration_days"]
    
    if k_data["bound_device"] != device_id: return "Device Mismatch", 0

    start = datetime.date.fromisoformat(k_data["activated_date"])
    exp = start + datetime.timedelta(days=k_data["duration_days"])
    left = (exp - datetime.date.today()).days
    return ("Expired", 0) if left < 0 else ("Valid", left)

def unbind_device(user_key):
    keys_db = load_json(KEYS_FILE)
    if user_key in keys_db:
        keys_db[user_key]["bound_device"] = None
        save_json(KEYS_FILE, keys_db)

# ==========================================
# 2. AUDIO ENGINE (ASYNC WITH PROGRESS)
# ==========================================
def clean_text(t): return re.sub(r'<[^>]+>', ' ', t).strip()
def srt_ms(ts): 
    try: h,m,s,ms=re.split(r'[:,]',ts); return (int(h)*3600+int(m)*60+int(s))*1000+int(ms)
    except: return 0
def parse_srt(c):
    subs=[]; blocks=re.split(r'\n\s*\n',c.strip())
    for b in blocks:
        l=b.strip().split('\n'); 
        if len(l)<2: continue
        idx=-1
        for i,ln in enumerate(l): 
            if '-->' in ln: idx=i; break
        if idx==-1: continue
        s,e=[x.strip() for x in l[idx].split('-->')]
        t=clean_text(" ".join(l[idx+1:]))
        if t: subs.append({'start': srt_ms(s), 'end': srt_ms(e), 'text': t})
    return subs

async def edge_gen_memory_indexed(index, text, voice, rate, pitch, style="Neutral"):
    kw={"voice":voice,"rate":f"{rate:+d}%","pitch":f"{pitch:+d}Hz"}
    if style and style!="Neutral": kw["style"]=style.lower()
    
    audio = b""
    try:
        async for chunk in edge_tts.Communicate(text, **kw).stream():
            if chunk["type"]=="audio": audio+=chunk["data"]
    except: pass
    return index, audio

async def process_srt_with_progress(subs, line_configs, v_opts, pad_ms, progress_bar, status_text):
    tasks = []
    
    # Reverse lookup to find voice code
    name_to_code = v_opts
    
    for i, sub in enumerate(subs):
        cfg = line_configs[i]
        
        # Handle Preset Names in Voice Config
        voice_selection = cfg['voice']
        
        # If it's a Preset Name (e.g., "Preset: WE"), we need to map it to real voice code
        # But 'cfg["voice"]' here stores the display label from selectbox.
        # The selectbox handles mapping back to code via v_opts.
        
        # However, if we injected a custom string like "Preset: WE", it's not in v_opts.
        # So we must store the REAL voice label in a hidden field or parse it.
        # SIMPLER FIX: The session state 'line_configs' stores the DISPLAY LABEL.
        # If label starts with "Preset:", we need to find the real voice label it represents?
        # NO: When applying preset, we set the REAL voice label (e.g. "Sreymom (Khmer)").
        # So cfg['voice'] is always valid key in v_opts.
        
        # Wait, user requested to SHOW preset name in dropdown.
        # If we do that, the key won't match v_opts.
        # SOLUTION: We will use the `format_func` of selectbox later, 
        # but for generation, we need the real voice code.
        
        # Since we can't easily change selectbox options dynamically per row without reset,
        # We will just ensure the config has valid voice label.
        
        if voice_selection not in v_opts:
            # Fallback if something is wrong
            vc_code = list(v_opts.values())[0]
        else:
            vc_code = v_opts[voice_selection]
            
        tasks.append(edge_gen_memory_indexed(i, sub['text'], vc_code, cfg['rate'], 0, "Neutral"))
    
    results_dict = {}
    total = len(tasks)
    
    # Run tasks with progress update
    for i, future in enumerate(asyncio.as_completed(tasks)):
        idx, audio_bytes = await future
        results_dict[idx] = audio_bytes
        
        # Update Progress Bar
        pct = int((i + 1) / total * 100)
        progress_bar.progress(pct)
        status_text.text(f"Processing Audio: {pct}% ({i+1}/{total})")
    
    full = AudioSegment.silent(duration=subs[-1]['end'] + 2000)
    pad = AudioSegment.silent(duration=pad_ms)
    
    for i in range(len(subs)):
        raw = results_dict.get(i)
        if raw:
            seg = AudioSegment.from_file(io.BytesIO(raw))
            seg = pad + effects.normalize(seg) + pad
            full = full.overlay(seg, position=subs[i]['start'])
            
    return full

def gen_audio_simple(t, eng, v, r, p, sty, gs, pad):
    with tempfile.NamedTemporaryFile(delete=False,suffix=".mp3") as f: tmp=f.name
    try:
        if eng=="Edge-TTS": 
            asyncio.run(edge_tts.Communicate(t, voice=v, rate=f"{r:+d}%", pitch=f"{p:+d}Hz").save(tmp))
            seg=AudioSegment.from_file(tmp)
        else: 
            gTTS(t,lang='km').write_to_fp(f)
            seg=AudioSegment.from_file(tmp)
            if gs!=1.0: seg=seg.speedup(gs)
        try: os.remove(tmp)
        except: pass
        pd=AudioSegment.silent(pad)
        return pd+effects.normalize(seg)+pd
    except: return AudioSegment.silent(0)

# ==========================================
# 3. UI & LOGIC
# ==========================================
st.title("🇰🇭 Khmer AI Voice Pro")

cm = get_cookie_manager()
if not cm: st.stop() 
did = get_device_id(cm)

# --- AUTO LOGIN ---
if 'auth' not in st.session_state:
    st.session_state.auth = False
    st.session_state.days = 0
    cookie_key = cm.get("auth_key")
    param_key = st.query_params.get("key", None)
    key_to_try = cookie_key if cookie_key else param_key
    if key_to_try:
        s, d = check_access_key(key_to_try, did)
        if s == "Valid":
            st.session_state.auth = True
            st.session_state.days = d
            st.session_state.ukey = key_to_try

# --- LOGIN SCREEN ---
if not st.session_state.auth:
    st.markdown("<br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.info("សូមវាយបញ្ចូល Key ដើម្បីប្រើប្រាស់")
        k_input = st.text_input("🔑 Access Key", type="password")
        rem = st.checkbox("ចងចាំខ្ញុំ (Remember Me)", value=True)
        if st.button("ចូលប្រើ (Login)", use_container_width=True):
            s, d = check_access_key(k_input, did)
            if s == "Valid":
                st.session_state.auth = True
                st.session_state.days = d
                st.session_state.ukey = k_input
                if rem: cm.set("auth_key", k_input, key="set_auth_key", expires_at=datetime.datetime.now() + datetime.timedelta(days=30))
                st.rerun()
            else: st.error(s)
    st.stop()

# ++++++++++++++++++++++++++++++++++++++++++++++++++++++
# APP INTERFACE (LOGGED IN)
# ++++++++++++++++++++++++++++++++++++++++++++++++++++++
with st.sidebar:
    st.success(f"✅ Active: {st.session_state.days} Days Left")
    if st.button("Sign Out"):
        unbind_device(st.session_state.ukey)
        cm.delete("auth_key"); st.query_params.clear()
        st.session_state.clear(); st.rerun()
    
    st.divider()
    
    # --- SETTINGS ---
    st.subheader("⚙️ Global Settings")
    defaults = {"s_eng":"Edge-TTS", "s_vc_lbl":"Sreymom (Khmer)", "s_rate":0, "s_pitch":0, "s_pad":80}
    for k,v in defaults.items():
        if k not in st.session_state: st.session_state[k]=v

    eng = st.selectbox("Engine", ["Edge-TTS", "gTTS"], key="s_eng")
    v_opts = {"Sreymom (Khmer)":"km-KH-SreymomNeural", "Piseth (Khmer)":"km-KH-PisethNeural", "Emma (English)":"en-US-EmmaMultilingualNeural"}
    
    if eng=="Edge-TTS":
        v_lbl = st.selectbox("Voice", list(v_opts.keys()), key="s_vc_lbl")
        rt = st.slider("Speed", -50, 50, key="s_rate")
        pt = st.slider("Pitch", -50, 50, key="s_pitch")
    else:
        gs = st.selectbox("Speed", [1.0, 1.2, 1.5])
    pad = st.number_input("Padding (ms)", key="s_pad")

    st.divider()
    
    # --- PRESETS (Sidebar) ---
    st.subheader("💾 Saved Presets")
    preset_note = st.text_input("Preset Name (Short)")
    
    def load_global_preset(slot_id):
        p = get_user_preset(st.session_state.ukey, slot_id)
        if p:
            st.session_state.s_eng = p.get("eng")
            st.session_state.s_vc_lbl = p.get("vc_lbl")
            st.session_state.s_rate = p.get("rate")
            st.session_state.s_pitch = p.get("pitch")
            st.session_state.s_pad = p.get("pad")
            st.toast(f"Loaded: {p.get('name')}")
        else:
            st.toast("Empty Slot", icon="⚠️")

    for i in range(1, 7):
        p = get_user_preset(st.session_state.ukey, i)
        p_name = p.get('name', f"S{i}") if p else f"S{i}"
        
        with st.expander(f"{i}. {p_name}"):
            c1, c2 = st.columns(2)
            c1.button("📥 Load", key=f"l{i}", use_container_width=True, on_click=load_global_preset, args=(i,))
            
            if c2.button("💾 Save", key=f"s{i}", use_container_width=True):
                name_to_save = preset_note if preset_note else f"S{i}"
                d = {"eng":st.session_state.s_eng, "vc_lbl":st.session_state.s_vc_lbl, 
                     "rate":st.session_state.s_rate, "pitch":st.session_state.s_pitch, 
                     "pad":st.session_state.s_pad}
                save_user_preset(st.session_state.ukey, i, d, name_to_save)
                st.toast(f"Saved: {name_to_save}")
                time.sleep(0.5); st.rerun()

# --- MAIN TABS ---
tab1, tab2 = st.tabs(["📝 Text Mode", "🎬 SRT Multi-Speaker"])

# >>> TEXT MODE <<<
with tab1:
    st.subheader("Text to Speech")
    txt = st.text_area("បញ្ចូលអត្ថបទ...", height=100)
    if st.button("Generate Audio 🎵", type="primary", use_container_width=True):
        with st.spinner("Generating..."):
            vc_code = v_opts[v_lbl] if eng=="Edge-TTS" else "km"
            gs_val = gs if eng=="gTTS" else 1.0
            fin = gen_audio_simple(txt, eng, vc_code, rt, pt, "Neutral", gs_val, pad)
            buf = io.BytesIO(); fin.export(buf, format="mp3")
            st.success("Done!"); st.audio(buf); st.download_button("Download MP3", buf, "audio.mp3", "audio/mp3", use_container_width=True)

# >>> SRT MODE <<<
with tab2:
    st.subheader("SRT Editor")
    upl = st.file_uploader("Upload SRT", type="srt")
    
    if upl:
        if 'srt_subs' not in st.session_state or st.session_state.get('last_file') != upl.name:
            raw = io.StringIO(upl.getvalue().decode("utf-8")).read()
            st.session_state.srt_subs = parse_srt(raw)
            st.session_state.last_file = upl.name
            # Init config lists
            st.session_state.line_configs = [{"voice": "Sreymom (Khmer)", "rate": 0} for _ in st.session_state.srt_subs]
            st.session_state.line_active_presets = [None] * len(st.session_state.srt_subs)
            # Store custom display names for voices to show "Preset: WE"
            st.session_state.line_display_names = [None] * len(st.session_state.srt_subs)

        subs = st.session_state.srt_subs
        
        def apply_preset_to_line(idx, slot_id):
            p = get_user_preset(st.session_state.ukey, slot_id)
            if p:
                # Save real config
                st.session_state.line_configs[idx]["voice"] = p.get("vc_lbl")
                st.session_state.line_configs[idx]["rate"] = p.get("rate")
                
                # Update UI Widgets (using keys)
                st.session_state[f"v_{idx}"] = p.get("vc_lbl")
                st.session_state[f"r_{idx}"] = p.get("rate")
                
                # Set Active State & Custom Name
                st.session_state.line_active_presets[idx] = slot_id
                
                # Note: We cannot easily change the dropdown TEXT to "Preset: Name" 
                # without breaking the mapping to v_opts. 
                # Instead, we use the Active Button Color to indicate the preset is active.
                
                st.toast(f"#{idx+1}: Applied {p.get('name')}")

        with st.container(height=600):
            for i, sub in enumerate(subs):
                st.markdown(f"<div class='srt-row-container'>", unsafe_allow_html=True)
                st.markdown(f"<div class='srt-box'><b>#{i+1}</b> <small>{sub['start']}ms</small><br>{sub['text']}</div>", unsafe_allow_html=True)
                
                c1, c2, c3 = st.columns([3, 1, 6])
                k_v, k_r = f"v_{i}", f"r_{i}"
                
                with c1: 
                    curr_v = st.session_state.line_configs[i]["voice"]
                    if curr_v not in v_opts: curr_v = list(v_opts.keys())[0]
                    
                    sel_vc = st.selectbox("Voice", list(v_opts.keys()), key=k_v, 
                                          index=list(v_opts.keys()).index(curr_v), 
                                          label_visibility="collapsed")
                
                with c2: 
                    sel_rt = st.number_input("Speed", -50, 50, value=st.session_state.line_configs[i]["rate"], key=k_r, label_visibility="collapsed")
                
                with c3: # 6 Presets Row
                    cols = st.columns(6)
                    active_slot = st.session_state.line_active_presets[i]
                    
                    for slot_num in range(1, 7):
                        p_data = get_user_preset(st.session_state.ukey, slot_num)
                        # SHOW NAME IN BUTTON
                        btn_label = p_data.get('name', str(slot_num)) if p_data else str(slot_num)
                        # ACTIVE COLOR LOGIC
                        b_type = "primary" if active_slot == slot_num else "secondary"
                        
                        with cols[slot_num-1]:
                            st.button(btn_label, key=f"p{slot_num}_{i}", type=b_type, on_click=apply_preset_to_line, args=(i, slot_num))

                st.markdown("</div>", unsafe_allow_html=True)
                
                # Reset active preset if user manually changes widgets
                if sel_vc != st.session_state.line_configs[i]["voice"] or sel_rt != st.session_state.line_configs[i]["rate"]:
                     st.session_state.line_active_presets[i] = None 
                
                st.session_state.line_configs[i] = {"voice": sel_vc, "rate": sel_rt}

        if st.button("🚀 Generate Conversation (Fast)", type="primary", use_container_width=True):
            # --- PROGRESS BAR DISPLAY ---
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            final = asyncio.run(process_srt_with_progress(
                subs, st.session_state.line_configs, v_opts, pad, progress_bar, status_text
            ))
            
            status_text.success("✅ Generation Complete!")
            progress_bar.progress(100)
            
            buf = io.BytesIO(); final.export(buf, format="mp3")
            st.audio(buf); st.download_button("Download", buf, "conversation.mp3", "audio/mp3", use_container_width=True)

st.markdown("---")
st.caption("Contact Admin: [Telegram @menghakmc](https://t.me/menghakmc)")
