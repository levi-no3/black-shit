"""
workspace.py - the agent's hands on the SHARED visible browser ("workspace").

The mirror app launches ONE Chromium with --remote-debugging-port=9222.
This helper attaches to it over CDP, so everything the agent does happens
in the SAME visible window the user watches - never a hidden browser.

Usage:
  python workspace.py tabs                  # list open tabs
  python workspace.py use 1                 # switch active tab
  python workspace.py goto <url> [--new]    # navigate (or open new tab)
  python workspace.py snap [max]            # accessible-ish snapshot for the agent
  python workspace.py text [css]            # read text
  python workspace.py shot [file]           # screenshot to file
  python workspace.py click <css>           # click element
  python workspace.py type <css> <text> [--enter]
  python workspace.py press <key> [css]
  python workspace.py scroll <y>
  python workspace.py back|forward|reload
  python workspace.py eval <js>             # run JS, print result
"""
import json
import sys

CDP = "http://127.0.0.1:9222"
_state = {}


def connect():
    from playwright.sync_api import sync_playwright
    if "pw" in _state:
        return _state
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.connect_over_cdp(CDP, timeout=10000)
    except Exception as e:
        pw.stop()
        print(f"CONNECT FAILED: {e}")
        print("Is browser_mirror_app.py running with the browser started?")
        raise SystemExit(1)
    ctx = browser.contexts[0] if browser.contexts else None
    if not ctx:
        print("No browser contexts found.")
        raise SystemExit(1)
    _state.update(pw=pw, browser=browser, ctx=ctx)
    return _state


def pages():
    s = connect()
    return [p for p in s["ctx"].pages if not p.is_closed()]


def active():
    ps = pages()
    if not ps:
        print("No open tabs.")
        raise SystemExit(1)
    i = _state.get("active", len(ps) - 1)
    i = max(0, min(i, len(ps) - 1))
    return ps[i]


def focus(page):
    try:
        page.bring_to_front()
    except Exception:
        pass


def cmd_tabs():
    for i, p in enumerate(pages()):
        try:
            print(f"[{i}] {p.title()[:60]} | {p.url}")
        except Exception as e:
            print(f"[{i}] <unreadable: {e}>")


def cmd_use(i):
    ps = pages()
    if 0 <= i < len(ps):
        _state["active"] = i
        focus(ps[i])
        print(f"active tab [{i}] {ps[i].url}")
    else:
        print(f"tab {i} out of range (0-{len(ps)-1})")


def cmd_goto(url, new=False):
    s = connect()
    if "://" not in url:
        url = "https://" + url
    if new:
        p = s["ctx"].new_page()
        _state["active"] = len(pages()) - 1
    else:
        p = active()
    focus(p)
    p.goto(url, wait_until="domcontentloaded", timeout=30000)
    print(f"OK {p.title()[:80]} | {p.url}")


SNAP_JS = """() => {
  const els = [];
  const all = document.querySelectorAll('a,button,input,select,textarea,[role=button],[onclick]');
  let n = 0;
  for (const el of all) {
    if (n >= 250) break;
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    let name = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim().replace(/\\s+/g,' ').slice(0,80);
    let sel = el.tagName.toLowerCase();
    if (el.id) sel += '#' + el.id;
    else if (el.name) sel += '[name="' + el.name + '"]';
    else if (el.className && typeof el.className === 'string') {
      const c = el.className.trim().split(/\\s+/).slice(0,2).join('.');
      if (c) sel += '.' + c;
    }
    els.push((n++) + '. <' + sel + '> "' + name + '"');
  }
  return {url: location.href, title: document.title, els};
}"""


def cmd_snap(max_chars=6000):
    p = active()
    try:
        d = p.evaluate(SNAP_JS)
    except Exception as e:
        print(f"SNAP FAILED: {e}")
        return
    out = [f"URL: {d['url']}", f"TITLE: {d['title']}", "ELEMENTS:"]
    out += d["els"]
    text = "\n".join(out)
    print(text[:max_chars])


def cmd_text(css="body", max_chars=4000):
    p = active()
    try:
        t = p.inner_text(css, timeout=10000)
        print(t[:max_chars])
    except Exception as e:
        print(f"TEXT FAILED: {e}")


def cmd_shot(path="workspace_shot.jpg"):
    p = active()
    p.screenshot(path=path, type="jpeg", quality=50)
    print(f"saved {path} | {p.url}")


def cmd_click(css):
    p = active()
    focus(p)
    p.click(css, timeout=15000)
    print(f"clicked {css} | {p.url}")


def cmd_type(css, text, enter=False):
    p = active()
    focus(p)
    p.fill(css, text, timeout=15000)
    if enter:
        p.press(css, "Enter")
    print(f"typed into {css} | {p.url}")


def cmd_press(key, css="body"):
    p = active()
    focus(p)
    p.press(css, key, timeout=10000)
    print(f"pressed {key} | {p.url}")


def cmd_scroll(y=500):
    p = active()
    focus(p)
    p.mouse.wheel(0, int(y))
    print(f"scrolled {y}")


def cmd_nav(kind):
    p = active()
    focus(p)
    if kind == "back":
        p.go_back(wait_until="domcontentloaded", timeout=15000)
    elif kind == "forward":
        p.go_forward(wait_until="domcontentloaded", timeout=15000)
    else:
        p.reload(wait_until="domcontentloaded", timeout=15000)
    print(f"{kind} | {p.url}")


def cmd_eval(js):
    p = active()
    try:
        r = p.evaluate(js)
        s = json.dumps(r, indent=2, default=str)
        print(s[:4000])
    except Exception as e:
        print(f"EVAL FAILED: {e}")


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    op = argv[1].lower()
    try:
        if op == "tabs":
            cmd_tabs()
        elif op == "use" and len(argv) >= 3:
            cmd_use(int(argv[2]))
        elif op == "goto" and len(argv) >= 3:
            cmd_goto(argv[2], new="--new" in argv)
        elif op == "snap":
            cmd_snap(int(argv[2]) if len(argv) >= 3 else 6000)
        elif op == "text":
            cmd_text(argv[2] if len(argv) >= 3 else "body")
        elif op == "shot":
            cmd_shot(argv[2] if len(argv) >= 3 else "workspace_shot.jpg")
        elif op == "click" and len(argv) >= 3:
            cmd_click(argv[2])
        elif op == "type" and len(argv) >= 4:
            cmd_type(argv[2], argv[3], enter="--enter" in argv)
        elif op == "press" and len(argv) >= 3:
            cmd_press(argv[2], argv[3] if len(argv) >= 4 else "body")
        elif op == "scroll":
            cmd_scroll(argv[2] if len(argv) >= 3 else 500)
        elif op in ("back", "forward", "reload"):
            cmd_nav(op)
        elif op == "eval" and len(argv) >= 3:
            cmd_eval(" ".join(argv[2:]))
        else:
            print(__doc__)
            return 1
    finally:
        if "pw" in _state:
            try:
                _state["pw"].stop()
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
