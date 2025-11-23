# User_app.py (Fixed WinError 32 - Final Robust Version)
# UI compacted. SALT matched. Term expanded. Telegram link.
# FIX: Added try-except blocks around os.remove() to prevent crashes on locked files.

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import tkinter.font as tkfont
import threading, os, re, tempfile, asyncio, importlib.util, json, hmac, hashlib, sys
import datetime, uuid, platform
import subprocess 
import webbrowser

# ==== Core Libraries ====
try:
    from gtts import gTTS
    from pydub import AudioSegment, effects
    import certifi
    import srt
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except ImportError as e:
    print(f"Error: Missing required library -> {e}. Please run: pip install gtts pydub certifi srt")
    sys.exit(1)

# ---- Hide ALL subprocess consoles on Windows ----
if os.name == "nt":
    _orig_popen = subprocess.Popen
    def _no_console_popen(*args, **kwargs):
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | 0x08000000
        return _orig_popen(*args, **kwargs)
    subprocess.Popen = _no_console_popen

# ---------- Bundle-aware resource resolver ----------
def _bundle_dir():
    if getattr(sys, 'frozen', False): return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.argv[0])))
    return os.path.dirname(os.path.abspath(__file__))

def _res(*paths):
    return os.path.join(_bundle_dir(), *paths)

# ---------- ffmpeg discovery ----------
_ffmpeg_candidate = _res("ffmpeg.exe")
if os.path.exists(_ffmpeg_candidate): AudioSegment.converter = _ffmpeg_candidate; os.environ["PATH"] = os.path.dirname(_ffmpeg_candidate) + os.pathsep + os.environ.get("PATH", "")

# ---------- Hide ffmpeg console windows ----------
try:
    import pydub.utils as _pu
    if os.name == "nt":
        _orig_popen = _pu.Popen
        def _silent_popen(*args, **kwargs):
            kwargs["creationflags"] = kwargs.get("creationflags", 0x08000000)
            if args and isinstance(args[0], (list, tuple)) and "ffmpeg" in str(args[0][0]).lower():
                cmd = list(args[0]) + ["-hide_banner", "-loglevel", "error"]; args = (cmd,) + args[1:]
            return _orig_popen(*args, **kwargs)
        _pu.Popen = _silent_popen
except Exception: pass

# -------- Optional preview backends --------
PREVIEW_BACKEND = "simpleaudio" if importlib.util.find_spec("simpleaudio") else "winsound" if importlib.util.find_spec("winsound") else None
if PREVIEW_BACKEND == "simpleaudio": import simpleaudio as sa
elif PREVIEW_BACKEND == "winsound": import winsound

EDGE_AVAILABLE = importlib.util.find_spec("edge_tts") is not None

# ======================================================================
#                             LICENSE & CORE LOGIC
# ======================================================================
SALT = b"CHANGE_THIS_TO_A_LONG_RANDOM_SECRET_32B_OR_MORE_AND_KEEP_IT_SECURE"
TERM_CHOICES = (30, 60, 90, 180, 365, 730, 9999)

def _app_dir():
    base = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "AiVoice")
    os.makedirs(base, exist_ok=True); return base

APP_DIR = _app_dir()
SETTINGS_PATH, LICENSE_FILE, PRESETS_PATH, BLACKLIST_PATH, USED_KEYS_PATH = (os.path.join(APP_DIR, f) for f in ["settings.json", "license.json", "presets.json", "blacklist.json", "used_keys.json"])

# ==================================
# === ROBUST get_hwid FUNCTION ===
# ==================================
def get_hwid() -> str:
    hwid_str = ""
    try:
        if os.name == 'nt':
            output = subprocess.check_output("wmic csproduct get uuid", shell=True, text=True, stderr=subprocess.DEVNULL)
            uuid_val = output.split("\n")[1].strip()
            if uuid_val and uuid_val != "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF":
                hwid_str = uuid_val
        if not hwid_str:
            hwid_str = f"MAC-{uuid.getnode():012X}|{platform.machine()}|{platform.node()}"
    except Exception:
        hwid_str = f"MAC-{uuid.getnode():012X}|{platform.machine()}|{platform.node()}"
    return hashlib.sha256(hwid_str.encode()).hexdigest()[:16].upper()

def copy_machine_id(root):
    hwid = get_hwid()
    try:
        root.clipboard_clear(); root.clipboard_append(hwid); root.update()
        messagebox.showinfo("Hardware ID Copied", f"Your HWID has been copied:\n\n{hwid}", parent=root)
    except:
        messagebox.showwarning("Copy Failed", "Could not copy to clipboard.", parent=root)

def derive_key(name: str, hwid: str, term_days: int) -> str:
    payload = f"{(name or '').strip().upper()}|{(hwid or '').strip().upper()}|{int(term_days)}"
    h = hmac.new(SALT, payload.encode(), hashlib.sha256).hexdigest().upper()[:16]
    return f"{h[:4]}-{h[4:8]}-{h[8:12]}-{h[12:16]}"

def sign_license(d: dict) -> str:
    p = f"{d.get('name','')}|{d.get('key','')}|{d.get('hwid','')}|{d.get('expires_on','')}"
    return hmac.new(SALT, p.encode(), hashlib.sha256).hexdigest()

def save_license(data: dict):
    with open(LICENSE_FILE, "w", encoding="utf-8") as f: json.dump(data, f, indent=2)

def load_license() -> dict | None:
    try:
        with open(LICENSE_FILE, "r", encoding="utf-8") as f: return json.load(f)
    except Exception: return None

def _key_fingerprint(k: str) -> str: return hmac.new(SALT, k.encode(), hashlib.sha256).hexdigest()
def _load_json_set(path: str) -> set:
    try:
        with open(path, "r", encoding="utf-8") as f: data = json.load(f)
        return set(data) if isinstance(data, list) else set()
    except Exception: return set()
def _save_json_set(s: set, path: str):
    with open(path, "w", encoding="utf-8") as f: json.dump(sorted(list(s)), f)

def is_key_blacklisted(k: str) -> bool: return _key_fingerprint(k) in _load_json_set(BLACKLIST_PATH)
def add_key_to_blacklist(k: str): s = _load_json_set(BLACKLIST_PATH); s.add(_key_fingerprint(k)); _save_json_set(s, BLACKLIST_PATH)
def is_key_used(k: str) -> bool: return _key_fingerprint(k) in _load_json_set(USED_KEYS_PATH)
def mark_key_used(k: str): s = _load_json_set(USED_KEYS_PATH); s.add(_key_fingerprint(k)); _save_json_set(s, USED_KEYS_PATH)

def validate_license(data: dict) -> bool:
    if not data: return False
    try:
        required = ("name", "key", "hwid", "expires_on", "term_days", "hash")
        if not all(k in data for k in required): return False
        if data["hwid"].upper() != get_hwid(): return False
        key = re.sub(r'\s+', '', data["key"] or '').upper()
        if key != derive_key(data["name"], data["hwid"], data["term_days"]): return False
        if datetime.date.fromisoformat(data["expires_on"]) < datetime.date.today(): return False
        if not hmac.compare_digest(sign_license(data), data["hash"]): return False
        if is_key_blacklisted(key): return False
        return True
    except Exception: return False

def days_left(data: dict) -> int:
    try: return max((datetime.date.fromisoformat(data["expires_on"]) - datetime.date.today()).days, 0)
    except Exception: return 0

def _read_presets():
    try:
        with open(PRESETS_PATH, "r", encoding="utf-8") as f: d = json.load(f)
        return d if isinstance(d, dict) else {}
    except: return {}
def _write_presets(d):
    with open(PRESETS_PATH, "w", encoding="utf-8") as f: json.dump(d, f, indent=2)
def save_custom_slot(s, snap): d = _read_presets(); d[f"Custom{s}"] = snap; _write_presets(d)
def load_custom_slot(s): return _read_presets().get(f"Custom{s}")
def run_thread(fn, *a, **kw): threading.Thread(target=fn, args=a, kwargs=kw, daemon=True).start()
def post_status(ui, text): ui["status"].after(0, lambda: ui["status"].config(text=text))
def post_info(t, txt, r): r.after(0, lambda: messagebox.showinfo(t, txt))
def post_warn(t, txt, r): r.after(0, lambda: messagebox.showwarning(t, txt))
def post_error(t, txt, r): r.after(0, lambda: messagebox.showerror(t, txt))
def _enable_widgets(w, e=True):
    for i in w: i.configure(state=("normal" if e else "disabled"))

def clean_text(text: str) -> str:
    t = re.sub(r'<[^>]+>', ' ', text); t = re.sub(r'\s+', ' ', t).strip()
    return re.sub(r'([។!?…])(\S)', r'\1 \2', t)
def srt_time_to_ms(ts):
    h, m, s, ms = re.split(r'[:,]', ts); return (int(h)*3600 + int(m)*60 + int(s))*1000 + int(ms)
def parse_srt_manual(p):
    with open(p, 'r', encoding='utf-8-sig') as f: c = f.read()
    subs = []
    for block in re.split(r'\n\s*\n', c.strip()):
        lines = block.strip().split('\n')
        if len(lines) < 2 or '-->' not in lines[1]: continue
        start_str, end_str = [s.strip() for s in lines[1].split(' --> ')]
        text = clean_text(' '.join(lines[2:]))
        subs.append((srt_time_to_ms(start_str), srt_time_to_ms(end_str), text))
    return subs

# ==== FIX: Added try-except block for os.remove ====
def gtts_to_segment(text, lang='km', speed=1.0):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as fp:
        gTTS(text=text, lang=lang).write_to_fp(fp); tmp_path = fp.name
    try:
        seg = AudioSegment.from_file(tmp_path)
        if speed != 1.0: seg = seg.speedup(playback_speed=speed)
        return effects.normalize(seg).fade_in(15).fade_out(20)
    finally: 
        try: os.remove(tmp_path)
        except: pass # Ignore deletion errors

async def edge_tts_to_file(text, voice, rate_pct, pitch_hz, style, out_path):
    import edge_tts
    kwargs = {"voice": voice, "rate": f"{rate_pct:+d}%", "pitch": f"{pitch_hz:+d}Hz"}
    if style and style.lower() != "neutral": kwargs["style"] = style.lower()
    await edge_tts.Communicate(text=text, **kwargs).save(out_path)

# ==== FIX: Added try-except block for os.remove ====
def edge_to_segment(text, voice, rate_pct, pitch_hz, style):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as fp: tmp = fp.name
    try:
        asyncio.run(edge_tts_to_file(text, voice, rate_pct, pitch_hz, style, tmp))
        return effects.normalize(AudioSegment.from_file(tmp)).fade_in(15).fade_out(20)
    finally: 
        try: os.remove(tmp)
        except: pass # Ignore deletion errors

def build_segment(text, engine, voice, rate, pitch, style, gtts_speed):
    if not text.strip(): return AudioSegment.silent(0)
    text = re.sub(r'([៖។!?…])', r'\1 ', text)
    if engine == "Edge-TTS" and EDGE_AVAILABLE:
        try: return edge_to_segment(text, voice, rate, pitch, style)
        except Exception as e: print(f"Edge TTS failed: {e}"); return gtts_to_segment(text, 'km', gtts_speed)
    return gtts_to_segment(text, 'km', gtts_speed)

def generate_audio_thread(srt_path, output_path, ui, root):
    lic = load_license();
    if not (lic and validate_license(lic) and days_left(lic) > 0): post_warn("License", "Valid license required.", root); return
    try:
        subs = parse_srt_manual(srt_path)
        if not subs: raise ValueError("No subtitles found.")
        final_audio = AudioSegment.silent(subs[-1][1] + 1200)
        for idx, (start_ms, end_ms, text) in enumerate(subs, 1):
            post_status(ui, f"Processing {idx}/{len(subs)} ({int(idx/len(subs)*100)}%)")
            if not text: continue
            pad = max(0, int(ui["pad_var"].get()))
            seg = build_segment(text, ui["engine_var"].get(), ui["voice_var"].get(), int(ui["rate_scale"].get()), int(ui["pitch_scale"].get()), ui["style_var"].get(), float(ui["speed_combo"].get()))
            final_audio = final_audio.overlay(AudioSegment.silent(pad) + seg + AudioSegment.silent(pad), position=start_ms)
        final_audio.apply_gain(-1.0).export(output_path, format="mp3")
        post_status(ui, f"✅ Success! Saved to {os.path.basename(output_path)}")
        post_info("Done", "Audio generation complete!", root)
    except Exception as e: post_error("Error", str(e), root); post_status(ui, "Error occurred.")
    finally: root.after(0, lambda: ui["btn"].config(state='normal'))

def start_thread_generate(srt_entry, out_entry, ui, root):
    if not os.path.isfile(srt_entry.get()): post_warn("Warning", "Please select a valid SRT file.", root); return
    if not out_entry.get().strip(): post_warn("Warning", "Please choose output location.", root); return
    ui["btn"].config(state='disabled'); run_thread(generate_audio_thread, srt_entry.get(), out_entry.get(), ui, root)

_preview = None; _preview_tmp = None
def _preview_backend_play(tmp_path):
    global _preview
    if PREVIEW_BACKEND == "simpleaudio": _preview = sa.WaveObject.from_wave_file(tmp_path).play()
    elif PREVIEW_BACKEND == "winsound": winsound.PlaySound(tmp_path, winsound.SND_FILENAME | winsound.SND_ASYNC)

def preview_play_thread(text, ui, root):
    if not (load_license() and validate_license(load_license()) and days_left(load_license()) > 0): post_warn("License", "Valid license required.", root); return
    global _preview_tmp;
    if not text.strip(): return
    try:
        seg = build_segment(text, ui["engine_var"].get(), ui["voice_var"].get(), int(ui["rate_scale"].get()), int(ui["pitch_scale"].get()), ui["style_var"].get(), float(ui["speed_combo"].get()))
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as fp: tmp = fp.name
        seg.set_frame_rate(44100).set_channels(1).set_sample_width(2).export(tmp, format="wav")
        _preview_tmp = tmp
        if PREVIEW_BACKEND: _preview_backend_play(tmp); post_status(ui, "Preview playing…")
        else: post_warn("Preview unavailable", "Install: pip install simpleaudio", root); os.remove(tmp); _preview_tmp = None
    except Exception as e: post_error("Preview Error", str(e), root)

# ==== FIX: Added try-except block for os.remove ====
def preview_stop_thread(ui, root):
    global _preview, _preview_tmp
    try:
        if PREVIEW_BACKEND == "simpleaudio" and _preview: _preview.stop()
        elif PREVIEW_BACKEND == "winsound": winsound.PlaySound(None, winsound.SND_PURGE)
    finally:
        _preview = None
        if _preview_tmp and os.path.exists(_preview_tmp):
            try: os.remove(_preview_tmp)
            except: pass # Ignore deletion errors
        _preview_tmp = None; post_status(ui, "Preview stopped")

def generate_text_to_mp3_thread(text, root, ui):
    if not (load_license() and validate_license(load_license()) and days_left(load_license()) > 0): post_warn("License", "Valid license required.", root); return
    text = (text or "").strip()
    if not text: post_info("Export", "Type text in the preview box first.", root); return
    out_path = filedialog.asksaveasfilename(defaultextension=".mp3", filetypes=[("MP3 files","*.mp3")])
    if not out_path: return
    try:
        pad = max(0, int(ui["pad_var"].get()))
        seg = build_segment(text, ui["engine_var"].get(), ui["voice_var"].get(), int(ui["rate_scale"].get()), int(ui["pitch_scale"].get()), ui["style_var"].get(), float(ui["speed_combo"].get()))
        (AudioSegment.silent(pad) + seg + AudioSegment.silent(pad)).apply_gain(-1.0).export(out_path, format="mp3")
        post_status(ui, f"✅ Saved MP3: {os.path.basename(out_path)}")
        post_info("Done", "Exported MP3 from text.", root)
    except Exception as e: post_error("Export Error", str(e), root)

def collect_settings(ui, srt_entry, out_entry):
    return {"engine": ui["engine_var"].get(), "voice": ui["voice_var"].get(), "style": ui["style_var"].get(), "rate": int(ui["rate_scale"].get()), "pitch": int(ui["pitch_scale"].get()), "gtts_speed": float(ui["speed_combo"].get()), "padding": ui["pad_var"].get(), "srt": srt_entry.get(), "output": out_entry.get()}
def apply_settings(st: dict, ui: dict, srt_entry: tk.Entry, out_entry: tk.Entry):
    try:
        ui["engine_var"].set(st.get("engine")); ui["voice_var"].set(st.get("voice"))
        ui["style_var"].set(st.get("style")); ui["rate_scale"].set(int(st.get("rate",0)))
        ui["pitch_scale"].set(int(st.get("pitch",0))); ui["speed_combo"].set(float(st.get("gtts_speed",1.0)))
        ui["pad_var"].set(str(st.get("padding","80"))); srt_entry.delete(0, tk.END); srt_entry.insert(0, st.get("srt",""))
        out_entry.delete(0, tk.END); out_entry.insert(0, st.get("output","")); ui["status"].config(text="Settings loaded.")
    except Exception as e: ui["status"].config(text=f"Settings apply error: {e}")
def save_settings_thread(ui, srt_entry, out_entry, root):
    if not (load_license() and validate_license(load_license())): post_warn("License", "Valid license required.", root); return
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f: json.dump(collect_settings(ui, srt_entry, out_entry), f, indent=2)
        post_status(ui, f"Settings saved.")
    except Exception as e: post_error("Settings", str(e), root)
def load_settings_thread(ui, srt_entry, out_entry, root):
    try:
        if not os.path.exists(SETTINGS_PATH): return
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f: st = json.load(f)
        root.after(0, lambda: apply_settings(st, ui, srt_entry, out_entry))
    except Exception as e: post_error("Settings", str(e), root)

def menu_import_license(root, status_label, gate_widgets, license_menu, import_index, disable_index):
    if load_license() and validate_license(load_license()): messagebox.showinfo("License", "This machine is already activated."); return
    p = filedialog.askopenfilename(title="Select license.json", filetypes=[("License JSON","*.json *.key")])
    if not p: return
    try:
        with open(p, "r", encoding="utf-8") as f: lic_in = json.load(f)
        name, key, term_days = (lic_in.get("name") or "").strip(), re.sub(r'\s+','',lic_in.get("key") or '').upper(), int(lic_in.get("term_days") or 30)
        if term_days not in TERM_CHOICES: raise ValueError(f"term_days {term_days} is invalid")
        if not (name and key and re.match(r'^[A-Z0-9]{4}(?:-[A-Z0-9]{4}){3}$', key)): raise ValueError("license.json invalid")
        if is_key_used(key): raise ValueError("This license key was already activated on this machine.")
        if is_key_blacklisted(key): raise ValueError("This license key has been disabled on this machine.")
        hwid = get_hwid()
        if key != derive_key(name, hwid, term_days): raise ValueError("Key not valid for this machine.")
        today = datetime.date.today()
        data = {"name": name, "key": key, "hwid": hwid, "activated_on": today.isoformat(), "expires_on": (today + datetime.timedelta(days=term_days)).isoformat(), "term_days": term_days}
        data["hash"] = sign_license(data); save_license(data); mark_key_used(key)
        messagebox.showinfo("License", "Imported & activated successfully.")
    except Exception as e: messagebox.showerror("Import", f"Failed to import license: {e}")
    _refresh_license_ui_simple(status_label, gate_widgets, license_menu, import_index, disable_index)

def _refresh_license_ui_simple(status_label, gate_widgets, m_license, import_index, disable_index):
    lic = load_license()
    if lic and validate_license(lic):
        days = days_left(lic)
        status_label.config(text=f"{lic.get('name','')} · {days} days left", fg="#4ade80") # Bright Green
        _enable_widgets(gate_widgets, True)
        m_license.entryconfig(import_index, state="disabled"); m_license.entryconfig(disable_index, state="normal")
    else:
        status_label.config(text="License: INVALID or MISSING", fg="#f87171") # Bright Red
        _enable_widgets(gate_widgets, False)
        m_license.entryconfig(import_index, state="normal"); m_license.entryconfig(disable_index, state="disabled")

def disable_license_irreversible(root, status_label, gate_widgets, m_license, import_index, disable_index):
    lic = load_license();
    if not (lic and validate_license(lic)): messagebox.showinfo("Disable", "No valid license to disable."); return
    norm_key = re.sub(r'\s+','',lic.get("key", '')).upper()
    if not messagebox.askyesno("Disable License (Irreversible)", "តើអ្នកបញ្ជាក់ថាចង់ Disable key នេះអចិន្ត្រៃយ៍លើម៉ាស៊ីននេះឬ?\nKey នេះមិនអាច Import ឡើងវិញបានទៀតឡើយ។"): return
    add_key_to_blacklist(norm_key)
    if os.path.exists(LICENSE_FILE): os.remove(LICENSE_FILE)
    messagebox.showinfo("Disable", "✅ Disabled successfully.")
    _refresh_license_ui_simple(status_label, gate_widgets, m_license, import_index, disable_index)

# ======================================================================
#                           MAIN UI
# ======================================================================
def main():
    THEME_DARK = { "bg": "#1e293b", "panel": "#334155", "border": "#475569", "text": "#e2e8f0", "text_muted": "#94a3b8", "primary": "#818cf8", "success": "#4ade80", "danger": "#f87171", "bar_bg": "#0f172a", "header_bg": "#4f46e5", "entry_bg": "#475569", "entry_fg": "#e2e8f0", "btn_fg": "#e2e8f0" }
    THEME = THEME_DARK

    root = tk.Tk()
    root.title("SRT → Khmer Speech (AI Voice Generator)")
    root.geometry("900x690")
    root.configure(bg=THEME["bg"])
    root.resizable(False, False)
    
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.windll.user32.GetParent(root.winfo_id()), 20, ctypes.byref(ctypes.c_int(2)), ctypes.sizeof(ctypes.c_int))
        except: pass

    default_font = tkfont.nametofont("TkDefaultFont"); default_font.configure(family="Segoe UI", size=9)
    root.option_add("*Font", default_font)
    
    style = ttk.Style(); style.theme_use('clam')
    style.configure("TCombobox", selectbackground=THEME["primary"], fieldbackground=THEME["entry_bg"], background=THEME["panel"], foreground=THEME["entry_fg"], bordercolor=THEME["border"], lightcolor=THEME["panel"], darkcolor=THEME["panel"], arrowcolor=THEME["text_muted"])
    style.map("TCombobox", fieldbackground=[("readonly", THEME["entry_bg"])], foreground=[("readonly", THEME["entry_fg"])])
    root.option_add('*TCombobox*Listbox.background', THEME["entry_bg"]); root.option_add('*TCombobox*Listbox.foreground', THEME["entry_fg"]); root.option_add('*TCombobox*Listbox.selectBackground', THEME["primary"])
    
    def header_bar(parent, text, bg, fg="white"):
        bar = tk.Frame(parent, bg=bg, height=28); bar.pack_propagate(False)
        lbl = tk.Label(bar, text=" " + text, bg=bg, fg=fg, font=("Segoe UI", 10, "bold"), anchor="w"); lbl.pack(side="left", fill="x", expand=True, padx=8)
        return bar

    menubar = tk.Menu(root, bg=THEME["bar_bg"], fg=THEME["text"], relief="flat", bd=0, activebackground=THEME["primary"], activeforeground="white")
    m_license = tk.Menu(menubar, tearoff=0, bg=THEME["panel"], fg=THEME["text"], relief="flat", activebackground=THEME["primary"], activeforeground="white")
    menubar.add_cascade(label="License", menu=m_license); root.config(menu=menubar)

    top_frame = tk.Frame(root, bg=THEME["panel"], highlightbackground=THEME["border"], highlightthickness=1); top_frame.pack(fill="x", padx=10, pady=(10, 3))
    main_panel = tk.Frame(root, bg=THEME["panel"], highlightbackground=THEME["border"], highlightthickness=1); main_panel.pack(fill="both", expand=True, padx=10, pady=3)
    actions = tk.Frame(root, bg=THEME["bar_bg"], height=50); actions.pack(fill="x", padx=10, pady=3); actions.pack_propagate(False)
    bottom_bar = tk.Frame(root, bg=THEME["bg"], height=34); bottom_bar.pack(fill="x", padx=10, pady=(0, 10)); bottom_bar.pack_propagate(False)
    
    top_inner = tk.Frame(top_frame, bg=THEME["panel"]); top_inner.pack(fill="x", expand=True, padx=8, pady=6)
    r1 = tk.Frame(top_inner, bg=THEME["panel"]); r1.pack(fill="x", pady=(0, 6))
    tk.Label(r1, text="Subtitle (.srt):", font=("Segoe UI", 10, "bold"), bg=THEME["panel"], fg=THEME["text"], width=13, anchor="w").pack(side="left")
    srt_entry = tk.Entry(r1, bd=1, relief="solid", bg=THEME["entry_bg"], fg=THEME["entry_fg"], insertbackground="white", highlightthickness=1, highlightcolor=THEME["border"]); srt_entry.pack(side="left", fill="x", expand=True, padx=8, ipady=1)
    tk.Button(r1, text="Browse...", command=lambda: (srt_entry.delete(0, tk.END), srt_entry.insert(0, filedialog.askopenfilename(filetypes=[("SRT files","*.srt")]))), bg=THEME["bg"], fg=THEME["btn_fg"], relief="flat", bd=1, highlightbackground=THEME["border"]).pack(side="left", padx=(0, 4))
    r2 = tk.Frame(top_inner, bg=THEME["panel"]); r2.pack(fill="x")
    tk.Label(r2, text="Output (.mp3):", font=("Segoe UI", 10, "bold"), bg=THEME["panel"], fg=THEME["text"], width=13, anchor="w").pack(side="left")
    out_entry = tk.Entry(r2, bd=1, relief="solid", bg=THEME["entry_bg"], fg=THEME["entry_fg"], insertbackground="white", highlightthickness=1, highlightcolor=THEME["border"]); out_entry.pack(side="left", fill="x", expand=True, padx=8, ipady=1)
    tk.Button(r2, text="Choose…", command=lambda: (out_entry.delete(0, tk.END), out_entry.insert(0, filedialog.asksaveasfilename(defaultextension=".mp3", filetypes=[("MP3 files","*.mp3")]))), bg=THEME["bg"], fg=THEME["btn_fg"], relief="flat", bd=1, highlightbackground=THEME["border"]).pack(side="left", padx=(0, 4))
    
    hb = header_bar(main_panel, "AI Voice Generator", THEME["header_bg"]); hb.pack(fill="x")
    inner = tk.Frame(main_panel, bg=THEME["panel"]); inner.pack(fill="both", expand=True, padx=10, pady=4)
    preview = tk.Text(inner, height=4, bd=1, relief="solid", bg=THEME["entry_bg"], fg=THEME["entry_fg"], insertbackground="white", highlightthickness=1, highlightcolor=THEME["border"]); preview.pack(fill='x', pady=(0, 6))
    row = tk.Frame(inner, bg=THEME["panel"]); row.pack(fill='x', pady=1)
    tk.Label(row, text="Engine", bg=THEME["panel"], fg=THEME["text"]).pack(side='left')
    engine_var = tk.StringVar(value="Edge-TTS" if EDGE_AVAILABLE else "gTTS")
    engine_cmb = ttk.Combobox(row, values=["Edge-TTS","gTTS"] if EDGE_AVAILABLE else ["gTTS"], textvariable=engine_var, width=12, state="readonly"); engine_cmb.pack(side='left', padx=(6, 12))
    tk.Label(row, text="Voice", bg=THEME["panel"], fg=THEME["text"]).pack(side='left')
    voice_var = tk.StringVar(value="km-KH-PisethNeural")
    voice_combo = ttk.Combobox(row, textvariable=voice_var, width=32); voice_combo.pack(side='left', padx=6)
    btn_load_voices = tk.Button(row, text="Load Voices", bg=THEME["bg"], fg=THEME["btn_fg"], relief="flat", bd=1, highlightbackground=THEME["border"]); btn_load_voices.pack(side='left', padx=(6,0))
    status_inline = tk.Label(row, text="", fg=THEME["text_muted"], bg=THEME["panel"], anchor="w"); status_inline.pack(side='left', padx=8, fill="x", expand=True)
    if not EDGE_AVAILABLE: status_inline.config(text="Edge-TTS not found", fg=THEME["danger"])
    row2 = tk.Frame(inner, bg=THEME["panel"]); row2.pack(fill='x', pady=(4, 4))
    tk.Label(row2, text="Emotion", bg=THEME["panel"], fg=THEME["text"]).pack(side='left')
    style_var = tk.StringVar(value="Neutral")
    style_combo = ttk.Combobox(row2, values=["Neutral","Cheerful","Sad","Angry","Excited","Friendly","Hopeful","Shouting"], textvariable=style_var, width=12, state="readonly"); style_combo.pack(side='left', padx=6)
    tk.Label(row2, text="gTTS Speed", bg=THEME["panel"], fg=THEME["text"]).pack(side='left', padx=(18, 0))
    speed_combo = ttk.Combobox(row2, values=[1.0,1.2,1.4,1.6,1.8,2.0], width=6, state="readonly"); speed_combo.set(1.0); speed_combo.pack(side='left', padx=6)
    tk.Label(row2, text="Padding (ms)", bg=THEME["panel"], fg=THEME["text"]).pack(side='left', padx=(18, 0))
    pad_var = tk.StringVar(value="80")
    tk.Entry(row2, textvariable=pad_var, width=6, bd=1, relief="solid", bg=THEME["entry_bg"], fg=THEME["entry_fg"], insertbackground="white", highlightthickness=1, highlightcolor=THEME["border"]).pack(side='left', padx=6)
    sp_block = tk.Frame(inner, bg=THEME["panel"]); sp_block.pack(fill='x', pady=(4, 2))
    def create_scale_group(parent, label_text, from_, to, step, header_bg):
        grp = tk.Frame(parent, bg=THEME["panel"], highlightbackground=THEME["border"], highlightthickness=1); grp.pack(side='left', expand=True, fill='x')
        header = header_bar(grp, label_text, header_bg); header.pack(fill="x")
        content = tk.Frame(grp, bg=THEME["panel"]); content.pack(fill="x", padx=6, pady=4)
        top = tk.Frame(content, bg=THEME["panel"]); top.pack(fill="x")
        val_label = tk.Label(top, text="0", bg=THEME["panel"], fg=THEME["text"], width=4, anchor="e"); val_label.pack(side='right')
        tk.Label(top, text="Value:", bg=THEME["panel"], fg=THEME["text"]).pack(side='right')
        scale = tk.Scale(content, from_=from_, to=to, resolution=1, orient='horizontal', showvalue=0, bg=THEME["panel"], fg=THEME["text"], troughcolor=THEME["entry_bg"], highlightthickness=0, bd=0, activebackground=THEME["primary"])
        scale.set(0); scale.pack(fill="x", pady=(0, 4)); scale.config(command=lambda v, lbl=val_label: lbl.config(text=str(int(float(v)))))
        def nudge_val(direction): val = int(scale.get()) + (direction * step); val = max(from_, min(to, val)); scale.set(val)
        btn_frame = tk.Frame(content, bg=THEME["panel"]); btn_frame.pack()
        tk.Button(btn_frame, text=f"-{step}", command=lambda: nudge_val(-1), width=6, bg=THEME["bg"], fg=THEME["btn_fg"], relief="flat", bd=1, highlightbackground=THEME["border"]).pack(side="left", padx=2)
        tk.Button(btn_frame, text="Reset", command=lambda: scale.set(0), width=6, bg=THEME["bg"], fg=THEME["btn_fg"], relief="flat", bd=1, highlightbackground=THEME["border"]).pack(side="left", padx=2)
        tk.Button(btn_frame, text=f"+{step}", command=lambda: nudge_val(1), width=6, bg=THEME["bg"], fg=THEME["btn_fg"], relief="flat", bd=1, highlightbackground=THEME["border"]).pack(side="left", padx=2)
        return scale
    rate_scale = create_scale_group(sp_block, "Voice Speed (%)", -50, 50, 5, "#16a34a"); sp_block.pack_slaves()[0].pack_configure(padx=(0, 4))
    pitch_scale = create_scale_group(sp_block, "Pitch Adjustment (Hz)", -100, 100, 5, "#f59e0b"); sp_block.pack_slaves()[1].pack_configure(padx=(4, 0))
    custom_card = tk.Frame(inner, bg=THEME["panel"], highlightbackground=THEME["border"], highlightthickness=1); custom_card.pack(fill='x', pady=(6, 4))
    ch = header_bar(custom_card, "Custom Presets & Quick Voice", THEME["text_muted"]); ch.pack(fill="x")
    custom_in = tk.Frame(custom_card, bg=THEME["panel"]); custom_in.pack(fill='x', padx=8, pady=4)
    left_custom = tk.Frame(custom_in, bg=THEME["panel"]); left_custom.pack(side="left", anchor='n')
    custom_msg = tk.Label(left_custom, text="", fg=THEME["primary"], bg=THEME["panel"]); custom_msg.pack(anchor='w', pady=(0, 4))
    def snapshot_current(): return {"engine": engine_var.get(), "voice": voice_var.get(), "style": style_var.get(), "rate": int(rate_scale.get()), "pitch": int(pitch_scale.get()), "gtts_speed": float(speed_combo.get())}
    def apply_snapshot(snap, label):
        if not snap: custom_msg.config(text=f"No data in {label}"); return
        engine_var.set(snap.get("engine")); voice_var.set(snap.get("voice")); style_var.set(snap.get("style"))
        rate_scale.set(int(snap.get("rate",0))); pitch_scale.set(int(snap.get("pitch",0))); speed_combo.set(float(snap.get("gtts_speed",1.0)))
        custom_msg.config(text=f"Loaded {label}")
    load_buttons = {}
    def update_load_button_text(slot_num, button):
        preset = load_custom_slot(slot_num)
        if preset:
            voice = preset.get("voice", "N/A").split("-")[-1].replace("Neural", "")
            style = preset.get("style", "N")
            rate = preset.get("rate", 0)
            button.config(text=f"{voice} / {style} / R:{rate}", state="normal", width=20)
        else:
            button.config(text="...", state="disabled", width=20)
    for i in range(1, 5):
        rowf = tk.Frame(left_custom, bg=THEME["panel"]); rowf.pack(anchor='w', pady=1)
        tk.Label(rowf, text=f"C{i}", width=3, bg=THEME["panel"], fg=THEME["text"]).pack(side='left')
        save_btn = tk.Button(rowf, text="Save", width=6, bg=THEME["bg"], fg=THEME["btn_fg"], relief="flat", bd=1, highlightbackground=THEME["border"])
        load_btn = tk.Button(rowf, command=lambda i=i: apply_snapshot(load_custom_slot(i), f"C{i}"), width=20, bg=THEME["bg"], fg=THEME["btn_fg"], relief="flat", bd=1, highlightbackground=THEME["border"])
        save_btn.config(command=lambda i=i, b=load_btn: (save_custom_slot(i, snapshot_current()), custom_msg.config(text=f"Saved C{i}"), update_load_button_text(i, b)))
        load_buttons[i] = load_btn
        save_btn.pack(side='left', padx=2); load_btn.pack(side='left', padx=2)
    def update_all_load_buttons():
        for i, btn in load_buttons.items(): update_load_button_text(i, btn)
    quick_right = tk.Frame(custom_in, bg=THEME["panel"]); quick_right.pack(side='right', anchor='n', padx=(10, 0))
    def quick_set_voice(voice_code, label):
        if not EDGE_AVAILABLE: return
        engine_var.set("Edge-TTS"); vals = list(voice_combo['values']) if voice_combo['values'] else []
        if voice_code not in vals: vals.append(voice_code); voice_combo['values'] = vals
        voice_var.set(voice_code); custom_msg.config(text=f"Voice: {label}")
    qr_grid = tk.Frame(quick_right, bg=THEME["panel"]); qr_grid.pack()
    q_voices = [("Piseth (km-KH)", "km-KH-PisethNeural"), ("Sreymom (km-KH)", "km-KH-SreymomNeural"),("Speech-B1", "en-US-EmmaMultilingualNeural"), ("Speech-B2", "en-US-BrianMultilingualNeural"),("Speech-B3", "en-US-AndrewMultilingualNeural"),("Speech-B4", "en-AU-WilliamMultilingualNeural"),("Speech-S1", "en-US-AriaNeural"),("Speech-S2", "en-US-AvaMultilingualNeural")]
    for i, (label, code) in enumerate(q_voices):
        r, c = divmod(i, 2)
        tk.Button(qr_grid, text=label, width=22, command=lambda c=code, l=label: quick_set_voice(c, l), bg=THEME["bg"], fg=THEME["btn_fg"], relief="flat", bd=1, highlightbackground=THEME["border"]).grid(row=r, column=c, padx=2, pady=2)
    
    btn_generate = tk.Button(actions, text="Generate Speech", font=("Segoe UI", 11, "bold"), bg=THEME["success"], fg=THEME["bg"], relief="flat"); btn_generate.pack(side='left', padx=(10, 6), pady=8)
    def create_action_btn(text, **kwargs): return tk.Button(actions, text=text, bg=THEME["bg"], fg=THEME["btn_fg"], relief="flat", bd=1, highlightbackground=THEME["border"], **kwargs)
    btn_text_to_mp3, btn_play, btn_stop, btn_clear = create_action_btn("Text → MP3"), create_action_btn("Play"), create_action_btn("Stop"), create_action_btn("Clear Preview", command=lambda: preview.delete("1.0","end"))
    btn_text_to_mp3.pack(side='left', padx=4, pady=8); btn_play.pack(side='left', padx=4, pady=8); btn_stop.pack(side='left', padx=4, pady=8); btn_clear.pack(side='left', padx=4, pady=8)
    btn_load = create_action_btn("Load Settings"); btn_load.pack(side='right', padx=4, pady=8)
    btn_save = create_action_btn("Save Settings"); btn_save.pack(side='right', padx=4, pady=8)
    status2 = tk.Label(bottom_bar, text="Ready", fg=THEME["primary"], bg=THEME["bg"], anchor="w"); status2.pack(side="left", pady=5)
    
    # --- LICENSE STATUS ---
    license_status = tk.Label(bottom_bar, text="", bg=THEME["bg"], anchor="e"); license_status.pack(side="right", padx=(10, 0), pady=5)
    
    # --- TELEGRAM BUTTON ---
    def open_telegram(e):
        webbrowser.open("https://t.me/menghakmc")
        
    contact_label = tk.Label(bottom_bar, text="Contact Admin: @menghakmc", fg="#3b82f6", bg=THEME["bg"], cursor="hand2", font=("Segoe UI", 9, "underline"))
    contact_label.pack(side="right", padx=10, pady=5)
    contact_label.bind("<Button-1>", open_telegram)
    # ----------------------

    ui = dict(btn=btn_generate, status=status2, preview=preview, engine_var=engine_var, voice_var=voice_var, style_var=style_var, rate_scale=rate_scale, pitch_scale=pitch_scale, speed_combo=speed_combo, pad_var=pad_var)
    gate_widgets = [btn_generate, btn_text_to_mp3, btn_play, btn_stop, btn_save, btn_load, btn_load_voices]
    IMPORT_INDEX, COPY_INDEX, DISABLE_INDEX = 0, 1, 3
    m_license.add_command(label="Import license.json…", command=lambda: menu_import_license(root, license_status, gate_widgets, m_license, IMPORT_INDEX, DISABLE_INDEX))
    m_license.add_command(label="Copy HWID", command=lambda: copy_machine_id(root))
    m_license.add_separator()
    m_license.add_command(label="Disable License (Irreversible)", command=lambda: disable_license_irreversible(root, license_status, gate_widgets, m_license, IMPORT_INDEX, DISABLE_INDEX))
    def load_voices_thread(combo, status_label, root):
        if not EDGE_AVAILABLE: return
        try:
            status_label.config(text="Loading...")
            import edge_tts
            async def _fetch():
                vs = await edge_tts.list_voices()
                km, en = sorted([v["ShortName"] for v in vs if v["Locale"].startswith("km")]), sorted([v["ShortName"] for v in vs if v["Locale"].startswith("en")])
                return km + en
            names = asyncio.run(_fetch())
            def apply(): combo['values'] = names; cur = voice_var.get(); (cur not in names) and combo.set(names[0]); status_label.config(text="")
            root.after(0, apply)
        except Exception as e: status_label.config(text="Failed"); post_warn("Voices", f"Cannot load voices.\n{e}", root)
    btn_load_voices.configure(command=lambda: run_thread(load_voices_thread, voice_combo, status_inline, root))
    btn_generate.configure(command=lambda: start_thread_generate(srt_entry, out_entry, ui, root))
    btn_text_to_mp3.configure(command=lambda: run_thread(generate_text_to_mp3_thread, ui["preview"].get("1.0","end").strip(), root, ui))
    btn_play.configure(command=lambda: run_thread(preview_play_thread, ui["preview"].get("1.0","end").strip(), ui, root))
    btn_stop.configure(command=lambda: run_thread(preview_stop_thread, ui, root))
    btn_save.configure(command=lambda: run_thread(save_settings_thread, ui, srt_entry, out_entry, root))
    btn_load.configure(command=lambda: run_thread(load_settings_thread, ui, srt_entry, out_entry, root))
    
    update_all_load_buttons()
    _refresh_license_ui_simple(license_status, gate_widgets, m_license, IMPORT_INDEX, DISABLE_INDEX)
    lic = load_license()
    if lic and validate_license(lic):
        if os.path.exists(SETTINGS_PATH): run_thread(load_settings_thread, ui, srt_entry, out_entry, root)
    else:
        root.after(400, lambda: messagebox.showinfo("License", "សូម Import license.json មុនពេលប្រើកម្មវិធី។\nMenu: License → Import license.json…"))
    root.mainloop()

if __name__ == "__main__":
    main()
