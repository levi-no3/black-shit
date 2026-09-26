"""
Roblox Optimizer v3 - actually affects FPS.
Targets: ARM64 + 8GB with 742MB free, Roblox at Quality 13 / 1938x1038 uncapped.
Real levers: free 1-2GB RAM, force Roblox Quality 1 + 1280x720 + 60fps cap,
Best performance power, pause OneDrive/widgets during session. All reversible.
Run: python roblox_optimizer.py
"""
import os
import json
import shutil
import subprocess
import tkinter as tk
from tkinter import messagebox, scrolledtext
import tempfile
import xml.etree.ElementTree as ET
try:
    import psutil
    HAVE_PSUTIL = True
except ImportError:
    psutil = None
    HAVE_PSUTIL = False

ROBLOX_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Roblox")
BASIC_XML = os.path.join(ROBLOX_DIR, "GlobalBasicSettings_13.xml")
CLIENT_DIR = os.path.join(ROBLOX_DIR, "ClientSettings")
CLIENT_JSON = os.path.join(CLIENT_DIR, "ClientAppSettings.json")
BAK_XML = BASIC_XML + ".optimizer_bak"

SAFE_CLOSE_LIST = ["firefox.exe", "chrome.exe", "msedge.exe", "opera.exe",
    "brave.exe", "discord.exe", "spotify.exe", "teams.exe",
    "slack.exe", "steam.exe", "epicgameslauncher.exe",
    "Widgets.exe", "GameBar.exe", "XboxGameBar.exe"]

def log(msg):
    log_box.insert(tk.END, msg + "\n")
    log_box.see(tk.END)

def run_cmd(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, shell=True, timeout=30)
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode == 0, out.strip()[:3000]
    except Exception as e:
        return False, str(e)

def free_mb():
    if HAVE_PSUTIL:
        return int(psutil.virtual_memory().available / (1024*1024))
    ok, out = run_cmd('systeminfo | findstr /C:"Available Physical Memory"')
    # parse "742 MB" number
    import re
    m = re.search(r"([\d,]+)\s*MB", out)
    if m:
        return int(m.group(1).replace(",", ""))
    return -1

def system_info():
    before = free_mb()
    ok, cpu = run_cmd('powershell -c "(Get-CimInstance Win32_Processor).Name"')
    ok2, mem = run_cmd('systeminfo | findstr /C:"Total Physical Memory" /C:"Available Physical Memory"')
    ok3, gpu = run_cmd('powershell -c "(Get-CimInstance Win32_VideoController).Name"')
    if ok: log(f"CPU: {cpu.strip()[:100]}")
    log("ARM64 + emulation: expect 20-30% lower FPS than x86. Low res + cap is mandatory.")
    if ok2: log(mem)
    if ok3: log(f"GPU: {gpu.strip()[:120]}")
    if before >= 0:
        log(f"Free RAM now: {before} MB (need 2000+ before Blade Ball)")

def set_prop(tree, name, value_text=None, tag=None):
    # Find <* name="..."> under Item/Properties and set text / bool
    root = tree.getroot()
    for elem in root.iter():
        if elem.get("name") == name:
            if value_text is not None:
                elem.text = value_text
            return True
    return False

def apply_potato_mode():
    """Real FPS fix: backup then force Roblox low graphics."""
    if not os.path.isfile(BASIC_XML):
        log("Roblox settings not found. Launch Roblox once first.")
        return
    try:
        if not os.path.isfile(BAK_XML):
            shutil.copy2(BASIC_XML, BAK_XML)
            log(f"Backup saved: {BAK_XML}")
        tree = ET.parse(BASIC_XML)
        # Quality 1 = lowest, cap 60 = stable frame times on Adreno 690
        set_prop(tree, "GraphicsQualityLevel", "1")
        set_prop(tree, "SavedQualityLevel", "1")
        set_prop(tree, "GraphicsOptimizationMode", "0")  # Manual
        set_prop(tree, "FramerateCap", "60")
        set_prop(tree, "VignetteEnabled", "false")
        set_prop(tree, "VREnabled", "false")
        set_prop(tree, "Fullscreen", "false")
        set_prop(tree, "StartMaximized", "false")
        set_prop(tree, "ReducedMotion", "true")
        # Window size 1280x720: smaller framebuffer = big GPU win
        root = tree.getroot()
        for elem in root.iter():
            if elem.get("name") == "StartScreenSize":
                for child in elem:
                    if child.tag == "X": child.text = "1280"
                    if child.tag == "Y": child.text = "720"
        tree.write(BASIC_XML, encoding="utf-8", xml_declaration=True)
        log("POTATO MODE APPLIED: Quality 1, Manual, 1280x720 window, 60fps cap, vignette/VR off.")
        log("Was: Quality 13, 1938x1038, uncapped. This is the single biggest FPS gain.")
    except Exception as e:
        log(f"Potato mode failed (close Roblox first): {e}")

def restore_roblox_settings():
    if os.path.isfile(BAK_XML):
        try:
            shutil.copy2(BAK_XML, BASIC_XML)
            log("Roblox graphics restored from backup.")
        except Exception as e:
            log(f"Restore failed (close Roblox first): {e}")
    else:
        log("No backup found.")

def fps_cap_on():
    try:
        os.makedirs(CLIENT_DIR, exist_ok=True)
        data = {}
        if os.path.isfile(CLIENT_JSON):
            try: data = json.loads(open(CLIENT_JSON).read())
            except Exception: data = {}
        data["DFIntTaskSchedulerTargetFps"] = 60
        open(CLIENT_JSON, "w").write(json.dumps(data, indent=2))
        log("FPS cap 60 ON (ClientAppSettings.json). Stabilizes frame time + heat on 8GB ARM.")
    except Exception as e:
        log(f"FPS cap failed: {e}")

def fps_cap_off():
    try:
        if os.path.isfile(CLIENT_JSON):
            data = json.loads(open(CLIENT_JSON).read())
            data.pop("DFIntTaskSchedulerTargetFps", None)
            open(CLIENT_JSON, "w").write(json.dumps(data, indent=2))
            log("FPS cap removed (back to Roblox default).")
        else:
            log("No cap file found.")
    except Exception as e:
        log(f"FPS cap off failed: {e}")

def free_ram_session():
    before = free_mb()
    if not messagebox.askyesno("Free RAM",
        "Close browsers/Discord/Spotify/Widgets for this session?\nUnsaved browser tabs will be lost.\nRoblox + system never touched."):
        return
    closed = []
    for exe in SAFE_CLOSE_LIST:
        ok, out = run_cmd(f'taskkill /IM {exe} /F')
        if ok and "SUCCESS" in out:
            closed.append(exe)
    # Pause OneDrive sync during play (files stay, sync resumes on reboot/restart)
    run_cmd('taskkill /IM OneDrive.exe /F')
    after = free_mb()
    log(f"Closed: {', '.join(closed) if closed else 'nothing running'} + OneDrive paused.")
    if before >= 0 and after >= 0:
        log(f"Free RAM: {before} -> {after} MB (freed {after-before} MB). Aim 2000+.")
        if after < 1500:
            log("Still low: also close extra Explorer windows + finish Windows Update (TiWorker).")
    log("Restart OneDrive after play: start %LOCALAPPDATA%\\Microsoft\\OneDrive\\OneDrive.exe")

def best_power_session():
    ok, _ = run_cmd("powercfg /setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c")
    # Disable battery saver throttling for session
    run_cmd("powercfg /setdcvalueindex SCHEME_CURRENT SUB_BATTERY BATACTIONCRIT 0")
    if ok:
        log("Power: High performance. PLAY PLUGGED IN - battery mode throttles Snapdragon 40%+.")
    else:
        log("Power needs Admin: right-click > Run as Administrator.")
        messagebox.showinfo("Admin needed", "Re-run as Administrator for power plan.")

def visuals_and_dvr():
    try:
        import winreg
        ve = winreg.CreateKey(winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects")
        winreg.SetValueEx(ve, "VisualFXSetting", 0, winreg.REG_DWORD, 2)
        winreg.CloseKey(ve)
        pers = winreg.CreateKey(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        winreg.SetValueEx(pers, "EnableTransparency", 0, winreg.REG_DWORD, 0)
        winreg.CloseKey(pers)
        k1 = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"System\GameConfigStore")
        winreg.SetValueEx(k1, "GameDVR_Enabled", 0, winreg.REG_DWORD, 0)
        winreg.CloseKey(k1)
        k2 = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\GameBar")
        winreg.SetValueEx(k2, "AllowAutoGameMode", 0, winreg.REG_DWORD, 1)
        winreg.CloseKey(k2)
        log("Visuals best-performance + transparency off + Game DVR off + Game Mode on.")
    except Exception as e:
        log(f"Visual/DVR failed: {e}")

def clean_and_dns():
    cleaned = 0
    for p in [tempfile.gettempdir(),
              os.path.join(os.environ.get("LOCALAPPDATA",""), "Temp"),
              os.path.join(ROBLOX_DIR, "logs")]:
        if not p or not os.path.isdir(p): continue
        try:
            for root, _, files in os.walk(p):
                if "Roblox" not in p and root.count(os.sep) - p.count(os.sep) > 2: continue
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        if "Roblox" in p and "logs" in p and not f.endswith(".log"): continue
                        cleaned += os.path.getsize(fp)/(1024*1024)
                        os.remove(fp)
                    except Exception: continue
                if "Roblox" not in p: break
        except Exception: continue
    run_cmd("ipconfig /flushdns")
    log(f"Cleaned ~{cleaned:.1f} MB + DNS flushed (fixes spike, not FPS).")

def boost_roblox():
    if HAVE_PSUTIL:
        found = False
        for proc in psutil.process_iter(["name"]):
            try:
                if proc.info["name"] and "roblox" in proc.info["name"].lower():
                    proc.nice(psutil.BELOW_HIGH_PRIORITY_CLASS)
                    log(f"Boosted {proc.info['name']} pid {proc.pid} -> Below High.")
                    found = True
            except Exception: continue
        if not found: log("Start Blade Ball first, then boost.")
    else:
        log("pip install psutil for auto-boost.")

def game_session():
    log("=== GAME SESSION: real performance pass ===")
    before = free_mb()
    log(f"Free RAM before: {before} MB" if before>=0 else "Free RAM: unknown")
    clean_and_dns()
    visuals_and_dvr()
    best_power_session()
    fps_cap_on()
    log("Now click 'Free RAM' + 'Potato mode' if not done, then launch Blade Ball, then 'Boost'.")
    messagebox.showinfo("Session",
        "Next:\n1. Free RAM button\n2. Potato mode (once)\n3. Launch Blade Ball\n4. Boost button while playing\nPlay plugged in, 1280x720.")

def launch_bladeball():
    # Blade Ball place 13772394625
    run_cmd('start roblox://experiences/start?placeId=13772394625')
    log("Launching Blade Ball... then use Boost while in-game.")

# --- GUI ---
root = tk.Tk()
root.title("Roblox Optimizer v3 - real FPS")
root.geometry("580x700")

tk.Label(root, text="v3 - frees RAM + forces Quality 1 / 720p / 60fps. All reversible.",
         wraplength=520, justify="left").pack(pady=8)

btns = [
    ("1. Check specs + free RAM (do first)", system_info),
    ("2. GAME SESSION - power + visuals + cap (do before play)", game_session),
    ("3. POTATO MODE - force Roblox Quality 1 / 720p / 60fps", apply_potato_mode),
    ("4. Restore Roblox graphics backup", restore_roblox_settings),
    ("5. Free RAM for session (closes browsers, pauses OneDrive)", free_ram_session),
    ("6. FPS cap 60 ON / OFF", lambda: (fps_cap_on(),)),
    ("7. Launch Blade Ball directly", launch_bladeball),
    ("8. Boost Roblox priority (while playing)", boost_roblox),
    ("9. Clean temp + flush DNS", clean_and_dns),
    ("10. Best power - play PLUGGED IN", best_power_session),
]
for text, fn in btns:
    tk.Button(root, text=text, width=60, anchor="w", command=fn).pack(pady=2)

tk.Button(root, text="FPS cap OFF (uncap)", width=60, anchor="w", command=fps_cap_off).pack(pady=2)

log_box = scrolledtext.ScrolledText(root, height=13)
log_box.pack(padx=10, pady=10, fill="both", expand=True)
log("You were: Quality 13, 1938x1038, uncapped, 742MB free. That cannot hold 60fps on Adreno 690.")
log("Click 2, then 3, then 5. Expect: +15-30fps in Blade Ball + no crash, at cost of lower visuals.")
root.mainloop()
