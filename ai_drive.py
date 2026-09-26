"""
ai_drive.py - let AI (or you) drive the Browser Mirror app from CLI / scripts.

The desktop app (browser_mirror_app.py) watches ai_command.json.
This helper writes a command and waits for ai_result.json, so every
AI action appears LIVE in the desktop mirror window.

Usage:
  python ai_drive.py status
  python ai_drive.py navigate https://example.com
  python ai_drive.py click "a[href='/news']"
  python ai_drive.py type "input[name=q]" "hello world" --enter
  python ai_drive.py scroll 800
  python ai_drive.py back
  python ai_drive.py get_text "body"
  python ai_drive.py screenshot
  python ai_drive.py new_tab https://www.youtube.com
  python ai_drive.py tabs
  python ai_drive.py switch_tab 0

You can also import it:
  from ai_drive import ai_navigate, ai_click, ai_type
"""
import json
import os
import sys
import time
import uuid

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CMD_FILE = os.path.join(BASE_DIR, "ai_command.json")
RESULT_FILE = os.path.join(BASE_DIR, "ai_result.json")
STATUS_FILE = os.path.join(BASE_DIR, "ai_status.json")


def send_command(cmd, timeout=40):
    cmd = dict(cmd)
    cmd["id"] = uuid.uuid4().hex[:8]
    # clear old result
    try:
        if os.path.exists(RESULT_FILE):
            os.remove(RESULT_FILE)
    except Exception:
        pass
    tmp = CMD_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cmd, f, indent=2)
    os.replace(tmp, CMD_FILE)
    print(f"[ai_drive] sent: {cmd}")

    # wait for app to execute (poll ai_result.json)
    start = time.time()
    while time.time() - start < timeout:
        if os.path.exists(RESULT_FILE):
            try:
                with open(RESULT_FILE, "r", encoding="utf-8") as f:
                    res = json.load(f)
                if res.get("ts"):
                    print(f"[ai_drive] result: {res}")
                    return res
            except Exception:
                pass
        time.sleep(0.4)
    print("[ai_drive] TIMEOUT: is browser_mirror_app.py running with browser started?")
    return {"ok": False, "error": "timeout waiting for mirror app"}


def ai_navigate(url):
    return send_command({"action": "navigate", "url": url})


def ai_click(selector):
    return send_command({"action": "click", "selector": selector})


def ai_type(selector, text, enter=False):
    return send_command({"action": "type", "selector": selector, "text": text, "enter": enter})


def ai_status():
    if not os.path.exists(STATUS_FILE):
        print("No status yet - is the mirror app running?")
        return {}
    with open(STATUS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(json.dumps(data, indent=2))
    return data


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    op = argv[1].lower()
    if op == "status":
        ai_status()
    elif op == "navigate" and len(argv) >= 3:
        ai_navigate(argv[2])
    elif op == "click" and len(argv) >= 3:
        ai_click(argv[2])
    elif op == "type" and len(argv) >= 4:
        enter = "--enter" in argv
        ai_type(argv[2], argv[3], enter=enter)
    elif op == "press" and len(argv) >= 4:
        send_command({"action": "press", "selector": argv[2], "key": argv[3]})
    elif op == "scroll":
        y = int(argv[2]) if len(argv) >= 3 else 500
        send_command({"action": "scroll", "y": y})
    elif op == "back":
        send_command({"action": "back"})
    elif op == "forward":
        send_command({"action": "forward"})
    elif op == "get_text":
        sel = argv[2] if len(argv) >= 3 else "body"
        send_command({"action": "get_text", "selector": sel})
    elif op == "screenshot":
        send_command({"action": "screenshot"})
    elif op == "new_tab":
        url = argv[2] if len(argv) >= 3 else "https://www.youtube.com"
        send_command({"action": "new_tab", "url": url})
    elif op == "tabs":
        send_command({"action": "tabs"})
    elif op == "switch_tab":
        idx = int(argv[2]) if len(argv) >= 3 else 0
        send_command({"action": "switch_tab", "index": idx})
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
