"""
Auto-delete Discord bot - deletes messages in configured channels after N minutes.

Setup:
  1. pip install -r requirements.txt
  2. Copy .env.example to .env and put your bot token in it
  3. python bot.py

Commands (need Manage Messages permission):
  /autodelete-set <channel> <minutes> - auto-delete messages in channel after minutes
  /autodelete-remove <channel> - disable auto-delete for channel
  /autodelete-list - list all configured channels
"""
import asyncio
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

import provoc
import tos

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
CONFIG_FILE = Path(__file__).parent / "autodelete_config.json"

# config format: { "guild_id": { "channel_id": {"minutes": float, "batch": int, "stop_at": iso|None, "mode": "all"|"violations", "start_from": iso|None} } }
# filters stored separately: { "guild_id": ["word1", "phrase2"] }
# old float format still supported
FILTER_FILE = Path(__file__).parent / "filters.json"
FLAGLIST_FILE = Path(__file__).parent / "flaglist.json"
HITS_FILE = Path(__file__).parent / "hits.jsonl"
CURSOR_FILE = Path(__file__).parent / "purge_cursor.json"

def load_filters() -> dict:
    if FILTER_FILE.exists():
        try:
            d = json.loads(FILTER_FILE.read_text())
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}
    return {}

def save_filters(f: dict):
    FILTER_FILE.write_text(json.dumps(f, indent=2))

def load_flaglist() -> dict:
    try:
        if FLAGLIST_FILE.exists():
            d = json.loads(FLAGLIST_FILE.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
    except Exception:
        pass
    return {}

def save_flaglist(f: dict):
    try:
        FLAGLIST_FILE.write_text(json.dumps(f, indent=2), encoding="utf-8")
    except Exception:
        pass

def load_cursors() -> dict:
    try:
        if CURSOR_FILE.exists():
            d = json.loads(CURSOR_FILE.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
    except Exception:
        pass
    return {}

def save_cursors(c: dict):
    try:
        CURSOR_FILE.write_text(json.dumps(c, indent=2), encoding="utf-8")
    except Exception:
        pass

flaglist = load_flaglist()

def flag_add(guild_id: int, channel_id: int, msg_id: int, reason: str):
    """Persist a flagged-but-undeleted message. Cap 20000/guild, overflow archived, never silently dropped."""
    try:
        g = flaglist.setdefault(str(guild_id), [])
        for e in g:
            try:
                if int(e.get("msg")) == int(msg_id):
                    e["reason"] = str(reason)[:80]
                    e["ts"] = datetime.now(timezone.utc).isoformat()
                    return
            except Exception:
                continue
        g.append({
            "ch": int(channel_id), "msg": int(msg_id),
            "reason": str(reason)[:80],
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        if len(g) > 20000:
            try:
                overflow = g[:-20000]
                with open(Path(__file__).parent / "flaglist_archive.jsonl", "a", encoding="utf-8") as f:
                    for e in overflow:
                        f.write(json.dumps({"g": str(guild_id), **e}) + "\n")
                del g[:-20000]
            except Exception:
                del g[:-20000]
    except Exception:
        pass

def journal_hit(guild_id: int, channel_id: int, msg_id: int, user_id: int, text: str = ""):
    """Append one violation sighting (cheap regex hits only) with folded snippet for keyword search."""
    try:
        try:
            folded = tos.fold(text or "")[:200]
        except Exception:
            folded = (text or "")[:200]
        line = json.dumps({"g": int(guild_id), "ch": int(channel_id), "msg": int(msg_id),
                           "u": int(user_id), "t": folded,
                           "ts": datetime.now(timezone.utc).isoformat()})
        with open(HITS_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def journal_search(guild_id: int, keyword: str, user_id: int | None = None) -> list:
    """Return [{ch, msg}] journal hits whose snippet matches keyword (evasion-aware)."""
    out = []
    try:
        lines = HITS_FILE.read_text(encoding="utf-8").splitlines()
    except Exception:
        return out
    if len(lines) > 200000:
        try:
            HITS_FILE.write_text("\n".join(lines[-100000:]) + "\n", encoding="utf-8")
            lines = lines[-100000:]
        except Exception:
            pass
    for ln in lines:
        try:
            e = json.loads(ln)
        except Exception:
            continue
        try:
            if int(e.get("g", 0)) != int(guild_id):
                continue
            if user_id is not None and int(e.get("u", 0)) != int(user_id):
                continue
            if not watch_matches(str(e.get("t", "")), [keyword]):
                continue
        except Exception:
            continue
        try:
            out.append({"ch": int(e["ch"]), "msg": int(e["msg"])})
        except Exception:
            continue
    return out

async def smart_delete(container, message_or_id) -> str | None:
    """Delete one message by object or ID. Unarchives threads first, prefers direct-ID
    calls (1 request, no fetch). Returns None on success, short error string on failure."""
    try:
        cid = int(getattr(container, "id", 0))
    except Exception:
        cid = 0
    try:
        th = container if isinstance(container, discord.Thread) else None
        if th is not None and getattr(th, "archived", False):
            try:
                await th.edit(archived=False, locked=False)
            except Exception:
                pass
    except Exception:
        pass
    try:
        http = container._state.http
    except Exception:
        http = None
    if isinstance(message_or_id, int):
        mid = message_or_id
        if http is not None:
            try:
                await http.delete_message(cid, mid)
                return None
            except discord.NotFound:
                return "already gone (404)"
            except discord.Forbidden:
                return "no delete permission (403)"
            except Exception:
                pass
        try:
            m = await container.fetch_message(mid)
        except discord.NotFound:
            return "already gone (404)"
        except discord.Forbidden:
            return "no read access (403)"
        except Exception as e:
            return f"fetch failed ({e})"[:80]
    else:
        m = message_or_id
    try:
        await m.delete()
        return None
    except discord.Forbidden:
        return "no delete permission (403)"
    except discord.NotFound:
        return "already gone (404)"
    except Exception as e:
        return str(e)[:80]

filters = load_filters()

SMART_FILE = Path(__file__).parent / "smart.json"
STRIKES_FILE = Path(__file__).parent / "strikes.json"

def _load_json(p: Path) -> dict:
    if p.exists():
        try:
            d = json.loads(p.read_text())
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}
    return {}

def _save_json(p: Path, d: dict):
    p.write_text(json.dumps(d, indent=2))

smart_cfg = _load_json(SMART_FILE)
strikes = _load_json(STRIKES_FILE)

WATCH_FILE = Path(__file__).parent / "watch.json"
watches = _load_json(WATCH_FILE)

def get_watch(guild_id: int, user_id: int) -> dict | None:
    raw = watches.get(str(guild_id), {}).get(str(user_id))
    if not isinstance(raw, dict):
        return None
    try:
        words = [str(w).lower() for w in raw.get("words", []) if str(w).strip()]
    except Exception:
        words = []
    try:
        minutes = float(raw.get("minutes", 1.0))
    except Exception:
        minutes = 1.0
    try:
        batch = max(5, min(600, int(raw.get("batch", 50))))
    except Exception:
        batch = 50
    return {"words": words[:100], "minutes": minutes, "batch": batch, "smart": bool(raw.get("smart", False))}

def watch_matches(text: str | None, words: list) -> str | None:
    """Return matched keyword or None. Checks raw + normalized (catches shiiit/n1gger evasions)."""
    if not text or not words:
        return None
    import re as _re
    lows = [text.lower()]
    try:
        lows.append(tos._normalize(text))
    except Exception:
        pass
    for w in words:
        if not w:
            continue
        pat = r"\b" + _re.escape(w) + r"\b" if len(w) >= 3 else _re.escape(w)
        try:
            if any(_re.search(pat, t) for t in lows):
                return w
        except Exception:
            continue
    return None

def get_smart(guild_id: int) -> dict:
    raw = smart_cfg.get(str(guild_id), {})
    if not isinstance(raw, dict):
        raw = {}
    return {
        "threshold": float(raw.get("threshold", 0.75)),
        "strikes_to_act": max(1, int(raw.get("strikes_to_act", 3))),
        "enabled": bool(raw.get("enabled", True)),
        "live_slur_delete": bool(raw.get("live_slur_delete", True)),
        "auto_timeout_strikes": max(0, int(raw.get("auto_timeout_strikes", 0))),
        "auto_timeout_minutes": max(1, min(40320, int(raw.get("auto_timeout_minutes", 10)))),
        "modlog_channel": raw.get("modlog_channel"),
        "exempt_roles": list(raw.get("exempt_roles", [])) if isinstance(raw.get("exempt_roles", []), list) else [],
    }

_score_cache: dict = {}

def cached_score(guild_id: int, msg_id: int, text: str) -> tuple[float, str]:
    key = f"{guild_id}:{msg_id}"
    if key in _score_cache:
        return _score_cache[key]
    try:
        score, src = provoc.score_text(text or "")
    except Exception:
        score, src = 0.0, "error"
    # cap cache
    if len(_score_cache) > 2000:
        _score_cache.clear()
    _score_cache[key] = (score, src)
    return score, src

def bump_strikes(guild_id: int, user_id: int) -> int:
    g = strikes.setdefault(str(guild_id), {})
    e = g.get(str(user_id), {"count": 0})
    try:
        c = int(e.get("count", 0)) + 1
    except Exception:
        c = 1
    g[str(user_id)] = {"count": c, "last": datetime.now(timezone.utc).isoformat()}
    try:
        _save_json(STRIKES_FILE, strikes)
    except Exception:
        pass
    return c

def reset_strikes(guild_id: int, user_id: int):
    try:
        g = strikes.get(str(guild_id), {})
        if str(user_id) in g:
            del g[str(user_id)]
            _save_json(STRIKES_FILE, strikes)
    except Exception:
        pass

def is_exempt(member, sm: dict) -> bool:
    """Staff/bot-exempt roles skip smart enforcement."""
    try:
        if getattr(member, "bot", False):
            return True
        exempt = set(str(x) for x in (sm.get("exempt_roles") or []))
        if not exempt:
            return False
        for r in (getattr(member, "roles", []) or []):
            try:
                if str(getattr(r, "id", "")) in exempt:
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False

async def maybe_enforce(guild, member, reason: str = "repeated violations") -> bool:
    """Timeout ladder: threshold reached -> timeout, strikes reset (re-arms). Returns True if timed out."""
    try:
        sm = get_smart(int(guild.id))
        need = int(sm.get("auto_timeout_strikes", 0) or 0)
        if need <= 0:
            return False
        try:
            c = int(strikes.get(str(guild.id), {}).get(str(member.id), {}).get("count", 0))
        except Exception:
            c = 0
        if c < need:
            return False
        mins = int(sm.get("auto_timeout_minutes", 10) or 10)
        try:
            await member.timeout(timedelta(minutes=mins), reason=f"Auto-mod: {reason} ({c} strikes)")
        except discord.Forbidden:
            try:
                with open(Path(__file__).parent / "deletes.log", "a", encoding="utf-8") as f:
                    f.write(f"{datetime.now(timezone.utc).isoformat()} enforce-fail guild={guild.id} user={member.id}: missing Moderate Members perm\n")
            except Exception:
                pass
            return False
        except Exception as e:
            print(f"Enforce failed: {e}", flush=True)
            return False
        reset_strikes(int(guild.id), int(member.id))
        try:
            with open(Path(__file__).parent / "deletes.log", "a", encoding="utf-8") as f:
                f.write(f"{datetime.now(timezone.utc).isoformat()} enforce-timeout guild={guild.id} user={member.id} strikes={c} mins={mins} reason={reason}\n")
        except Exception:
            pass
        try:
            await modlog_send(guild, f"Timed out <@{member.id}> for {mins} min: {reason} ({c} strikes).")
        except Exception:
            pass
        return True
    except Exception:
        return False

async def modlog_send(guild, text: str):
    """Post to configured staff mod-log channel. Silent if unset."""
    try:
        sm = get_smart(int(guild.id))
        cid = sm.get("modlog_channel")
        if not cid:
            return
        ch = guild.get_channel(int(cid))
        if ch is None:
            try:
                ch = await guild.fetch_channel(int(cid))
            except Exception:
                ch = None
        if ch is None:
            return
        await ch.send(text[:1800])
    except Exception:
        pass

def get_filter_words(guild_id: int) -> list:
    raw = filters.get(str(guild_id), [])
    return raw if isinstance(raw, list) else []

def matches_violation(content: str | None, guild_id: int) -> bool:
    if not content:
        return False
    words = get_filter_words(guild_id)
    if not words:
        return False
    low = content.lower()
    for w in words:
        try:
            if w and str(w).lower() in low:
                return True
        except Exception:
            continue
    return False

def parse_start_from(s) -> datetime | None:
    if not s:
        return None
    s = str(s).strip()
    # accept "YYYY-MM-DD HH:MM", "YYYY-MM-DD", or ISO
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            continue
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None
def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            return {}
    return {}

def save_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))

def get_entry(guild_id: int, channel_id: int) -> dict | None:
    raw = config.get(str(guild_id), {}).get(str(channel_id))
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return {"minutes": float(raw), "batch": 50, "stop_at": None, "mode": "all", "start_from": None}
    if isinstance(raw, dict):
        try:
            mode = str(raw.get("mode", "all")).lower()
            if mode not in ("all", "violations", "smart"):
                mode = "all"
            return {
                "minutes": float(raw.get("minutes", 1.0)),
                "batch": max(5, min(600, int(raw.get("batch", 50)))),
                "stop_at": raw.get("stop_at"),
                "mode": mode,
                "start_from": raw.get("start_from"),
            }
        except Exception:
            return None
    return None

def get_entry_resolved(guild_id: int, channel) -> dict | None:
    """Channel config lookup that follows forum threads to their parent channel.
    Without this, every message inside a forum post is invisible to live mode."""
    try:
        e = get_entry(guild_id, int(getattr(channel, "id", 0) or 0))
        if e is not None:
            return e
        parent_id = getattr(channel, "parent_id", None)
        if parent_id is not None:
            return get_entry(guild_id, int(parent_id))
    except Exception:
        pass
    return None

def msg_text(m) -> str:
    """Full checkable text: message content + any forwarded snapshot contents.
    Forwards carry their text in snapshots, leaving .content empty."""
    try:
        parts = [getattr(m, "content", None) or ""]
        for s in (getattr(m, "message_snapshots", None) or []):
            try:
                c = getattr(s, "content", None)
                if c:
                    parts.append(c)
            except Exception:
                continue
        return "\n".join([p for p in parts if p])
    except Exception:
        try:
            return getattr(m, "content", None) or ""
        except Exception:
            return ""

def parse_stop_at(stop_at) -> datetime | None:
    if not stop_at:
        return None
    try:
        dt = datetime.fromisoformat(str(stop_at))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None

config = load_config()

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    import traceback
    # Unknown interaction = user saw "no response" because we took >3s (LLM first load). Already deferred now, just log.
    err_str = str(error)
    if "10062" in err_str or "Unknown interaction" in err_str:
        try:
            tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
            Path(__file__).parent.joinpath("error.log").open("a", encoding="utf-8").write(
                f"[{datetime.now(timezone.utc)}] expired interaction (slow LLM first run) cmd={interaction.command.name if interaction.command else 'unknown'}\n{tb}\n"
            )
        except Exception:
            pass
        return
    msg = "Something went wrong with that command."
    if isinstance(error, app_commands.MissingPermissions):
        msg = f"You need Manage Messages permission to use this. Missing: {', '.join(error.missing_permissions)}"
    elif isinstance(error, app_commands.CheckFailure):
        msg = "You don't have permission to use this command (need Manage Messages)."
    else:
        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        log_line = f"[{datetime.now(timezone.utc)}] guild={interaction.guild_id} user={interaction.user} cmd={interaction.command.name if interaction.command else 'unknown'} error={error}\n{tb}\n"
        print(log_line, flush=True)
        try:
            Path(__file__).parent.joinpath("error.log").open("a", encoding="utf-8").write(log_line)
        except Exception:
            pass
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception as e:
        print(f"Failed to send error message: {e}")

async def delete_after(message_id: int, channel_id: int, delay_seconds: float):
    await asyncio.sleep(delay_seconds)
    try:
        channel = bot.get_channel(channel_id)
        if channel is None:
            channel = await bot.fetch_channel(channel_id)
        msg = None
        try:
            # try cached / fetch
            msg = await channel.fetch_message(message_id)
        except discord.NotFound:
            return
        # log actual age vs expected for timing debug
        try:
            age = (datetime.now(timezone.utc) - msg.created_at).total_seconds()
            with open(Path(__file__).parent / "deletes.log", "a", encoding="utf-8") as f:
                f.write(f"{datetime.now(timezone.utc).isoformat()} timer-delete ch={channel_id} msg={message_id} age={age:.1f}s expected={delay_seconds:.1f}s\n")
        except Exception:
            pass
        await msg.delete()
    except discord.Forbidden:
        print(f"No permission to delete {message_id} in {channel_id}")
    except discord.NotFound:
        pass
    except Exception as e:
        print(f"Delete failed {message_id}: {e}")

def get_minutes(guild_id: int, channel_id: int):
    e = get_entry(guild_id, channel_id)
    return e["minutes"] if e else None

@tasks.loop(seconds=15)
async def sweep_loop():
    """Fast sweeper - bulk deletes expired messages within ~15s of expiry."""
    now = datetime.now(timezone.utc)
    changed = False
    for guild_id_str, channels in list(config.items()):
        for channel_id_str, raw in list(channels.items()):
            try:
                entry = get_entry(int(guild_id_str), int(channel_id_str))
                if entry is None:
                    continue
                # auto-stop check
                stop_dt = parse_stop_at(entry["stop_at"])
                if stop_dt is not None and now >= stop_dt:
                    try:
                        del config[guild_id_str][channel_id_str]
                        if not config[guild_id_str]:
                            del config[guild_id_str]
                        changed = True
                        print(f"Auto-stop expired for {channel_id_str}, disabled", flush=True)
                    except Exception:
                        pass
                    continue
                mins = entry["minutes"]
                batch = max(5, min(600, entry["batch"]))
                # Discord bulk-delete caps at 100 per call: chunk big batches (600 = 6x100)
                per_call = min(batch, 100)
                rounds = min(6, max(1, (batch + 99) // 100))
                mode = entry.get("mode", "all")
                start_dt = parse_start_from(entry.get("start_from"))
                guild_id_int = int(guild_id_str)
                channel = bot.get_channel(int(channel_id_str))
                if channel is None:
                    continue
                expiry_seconds = mins * 60
                sm = get_smart(guild_id_int)
                thresh = sm["threshold"]

                try:
                    # fetch then score then bulk-delete; loop rounds so deep backlog doesn't leave violations
                    for _round in range(rounds):
                        try:
                            msgs = [m async for m in channel.history(limit=per_call, oldest_first=False)]
                        except Exception:
                            break
                        to_delete = set()
                        for m in msgs:
                            try:
                                if m.pinned:
                                    continue
                                if start_dt is not None and m.created_at < start_dt:
                                    continue
                                age = (now - m.created_at).total_seconds()
                                try:
                                    instant_m = tos.is_instant(msg_text(m))
                                except Exception:
                                    instant_m = False
                                if age < expiry_seconds and not instant_m:
                                    continue
                                if mode == "all":
                                    to_delete.add(m.id)
                                elif mode in ("violations", "smart"):
                                    try:
                                        try:
                                            if is_exempt(getattr(m, "author", None), sm):
                                                continue
                                        except Exception:
                                            pass
                                        # mild allowlist never deleted in batch
                                        try:
                                            if tos.is_benign_mild(msg_text(m)):
                                                continue
                                        except Exception:
                                            pass
                                        # severe (incl. misspellings) goes live unless slurs are purge-only
                                        try:
                                            if tos.live_severe(msg_text(m), sm.get("live_slur_delete", True)):
                                                to_delete.add(m.id)
                                                continue
                                        except Exception:
                                            pass
                                        # purge-only slur mode: slurs stay live here
                                        try:
                                            if not sm.get("live_slur_delete", True) and tos.is_slur(msg_text(m)):
                                                continue
                                        except Exception:
                                            pass
                                        if mode == "violations" and matches_violation(msg_text(m), guild_id_int):
                                            to_delete.add(m.id)
                                            continue
                                        mh = len(getattr(m, "mentions", []) or []) > 0
                                        s, _ = cached_score(guild_id_int, m.id, msg_text(m))
                                        if s < thresh:
                                            continue
                                        try:
                                            directed = tos.is_horrible_directed(msg_text(m), mh, slurs=sm.get("live_slur_delete", True))
                                        except Exception:
                                            directed = False
                                        if directed:
                                            to_delete.add(m.id)
                                    except Exception:
                                        continue
                            except Exception:
                                continue
                        if not to_delete:
                            break
                        try:
                            deleted = await channel.purge(limit=per_call, check=lambda mm, _td=to_delete: mm.id in _td, oldest_first=False)
                        except Exception:
                            break
                        if deleted:
                            try:
                                with open(Path(__file__).parent / "deletes.log", "a", encoding="utf-8") as f:
                                    for d in deleted:
                                        try:
                                            age = (datetime.now(timezone.utc) - d.created_at).total_seconds()
                                        except Exception:
                                            age = -1
                                        f.write(f"{datetime.now(timezone.utc).isoformat()} sweep-delete ch={channel_id_str} msg={d.id} age={age:.1f}s expected={expiry_seconds:.1f}s batch={batch} mode={mode}\n")
                            except Exception:
                                pass
                        # keep looping while we deleted a full window (deeper violations remain).
                        # only stop when a round deletes nothing - every violation in batch goes, not 1 or 3.
                        try:
                            if not deleted:
                                break
                        except Exception:
                            break
                        await asyncio.sleep(1)
                    continue
                except discord.Forbidden:
                    print(f"No permission to purge in {channel.id}", flush=True)
                except discord.HTTPException:
                    # rate limited or messages >14 days old cant be bulk-deleted - skip this round
                    pass
                except Exception as e:
                    print(f"Sweep failed {channel_id_str}: {e}", flush=True)
            except Exception as e:
                print(f"Sweep config error: {e}", flush=True)
    # per-user watches: scan recent messages in guild text channels (bounded)
    try:
        for guild_id_str, users in list(watches.items()):
            if not isinstance(users, dict) or not users:
                continue
            try:
                guild = bot.get_guild(int(guild_id_str))
            except Exception:
                continue
            if guild is None:
                continue
            try:
                text_channels = ([c for c in guild.text_channels] + [c for c in guild.voice_channels])[:12]
            except Exception:
                continue
            smw = get_smart(int(guild_id_str))
            for user_id_str, wraw in list(users.items()):
                try:
                    w = get_watch(int(guild_id_str), int(user_id_str))
                    if w is None:
                        continue
                    wmins, wbatch = w["minutes"], max(5, min(600, w["batch"]))
                    wexpiry = wmins * 60
                    for ch in text_channels:
                        try:
                            msgs = [m async for m in ch.history(limit=min(30, wbatch), oldest_first=False)]
                        except Exception:
                            continue
                        wdel = set()
                        for m in msgs:
                            try:
                                if m.pinned or m.author.bot:
                                    continue
                                try:
                                    if int(m.author.id) != int(user_id_str):
                                        continue
                                except Exception:
                                    continue
                                try:
                                    _iw = tos.is_instant(msg_text(m))
                                except Exception:
                                    _iw = False
                                if (now - m.created_at).total_seconds() < wexpiry and not _iw:
                                    continue
                                matched = watch_matches(msg_text(m), w["words"])
                                if matched:
                                    wdel.add(m.id)
                                    continue
                                if w["smart"]:
                                    try:
                                        if tos.is_benign_mild(msg_text(m)):
                                            continue
                                    except Exception:
                                        pass
                                    try:
                                        if tos.live_severe(msg_text(m), smw.get("live_slur_delete", True)):
                                            wdel.add(m.id)
                                            continue
                                    except Exception:
                                        pass
                                    try:
                                        if not smw.get("live_slur_delete", True) and tos.is_slur(msg_text(m)):
                                            continue
                                    except Exception:
                                        pass
                                    if matches_violation(msg_text(m), int(guild_id_str)):
                                        wdel.add(m.id)
                                        continue
                                    s, _ = cached_score(int(guild_id_str), m.id, msg_text(m))
                                    if s < smw["threshold"]:
                                        continue
                                    try:
                                        mh = len(getattr(m, "mentions", []) or []) > 0
                                        if tos.is_horrible_directed(msg_text(m), mh, slurs=smw.get("live_slur_delete", True)):
                                            wdel.add(m.id)
                                    except Exception:
                                        pass
                            except Exception:
                                continue
                        if wdel:
                            try:
                                await ch.purge(limit=100, check=lambda mm, _td=wdel: mm.id in _td, oldest_first=False)
                            except Exception:
                                pass
                    await asyncio.sleep(1)
                except Exception:
                    continue
    except Exception as e:
        print(f"Watch sweep failed: {e}", flush=True)
    if changed:
        save_config(config)

@sweep_loop.before_loop
async def before_sweep():
    await bot.wait_until_ready()

BOT_BUILD = "2026-09-19-slur-live-purge-split"

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}", flush=True)
    try:
        with open(Path(__file__).parent / "deletes.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} BOOT build={BOT_BUILD}\n")
    except Exception:
        pass
    # any purge.lock at boot is orphaned (tasks don't survive restart) - log + clear it
    try:
        lp = Path(__file__).parent / "purge.lock"
        if lp.exists():
            try:
                with open(Path(__file__).parent / "deletes.log", "a", encoding="utf-8") as f:
                    f.write(f"{datetime.now(timezone.utc).isoformat()} purge-killed (restart during run): {lp.read_text(encoding='utf-8')[:200]}\n")
            except Exception:
                pass
            lp.unlink(missing_ok=True)
    except Exception:
        pass
    # warm LLM in background so first /smart-test doesn't time out
    try:
        status = await asyncio.to_thread(provoc.load_status)
        print(f"LLM warmup: {status}", flush=True)
    except Exception as e:
        print(f"LLM warmup failed: {e}", flush=True)
    print("Syncing slash commands...", flush=True)
    try:
        synced = await asyncio.wait_for(bot.tree.sync(), timeout=30)
        print(f"Slash commands synced: {len(synced)} commands", flush=True)
        for c in synced:
            print(f" - /{c.name}", flush=True)
    except asyncio.TimeoutError:
        print("Sync timed out after 30s - rate limited, will retry next restart", flush=True)
    except Exception as e:
        print(f"Sync failed: {e}", flush=True)
    # guild-scoped sync: instant (<seconds) so option changes show up without the 1h global wait
    try:
        guild_ids = set()
        for src in (config, smart_cfg, watches, filters, strikes):
            try:
                for gid in list(src.keys()):
                    guild_ids.add(str(gid))
            except Exception:
                continue
        for gid in guild_ids:
            try:
                gs = await asyncio.wait_for(
                    bot.tree.sync(guild=discord.Object(id=int(gid))), timeout=20
                )
                print(f"Guild {gid} synced: {len(gs)} commands", flush=True)
            except Exception as e:
                print(f"Guild {gid} sync skipped: {e}", flush=True)
    except Exception as e:
        print(f"Guild sync failed: {e}", flush=True)

    if not sweep_loop.is_running():
        sweep_loop.start()
        print("Fast sweeper started (15s bulk interval)", flush=True)

    # On restart: one bulk purge of expired backlog, sweeper handles the rest
    for guild_id_str, channels in config.items():
        for channel_id_str, raw in list(channels.items()):
            try:
                entry = get_entry(int(guild_id_str), int(channel_id_str))
                if entry is None:
                    continue
                if parse_stop_at(entry["stop_at"]) is not None and datetime.now(timezone.utc) >= parse_stop_at(entry["stop_at"]):
                    continue  # sweeper will clean it up
                mins = entry["minutes"]
                batch = max(5, min(100, entry["batch"]))
                mode = entry.get("mode", "all")
                start_dt = parse_start_from(entry.get("start_from"))
                gid = int(guild_id_str)
                channel = bot.get_channel(int(channel_id_str))
                if channel is None:
                    continue
                now2 = datetime.now(timezone.utc)
                def is_old(m: discord.Message, _mins=mins, _now=now2, _mode=mode, _gid=gid, _start=start_dt):
                    if m.pinned:
                        return False
                    if _start is not None and m.created_at < _start:
                        return False
                    # startup: skip LLM scoring for speed (sweeper will catch smart). Handle all + filter only.
                    if _mode == "smart":
                        return False
                    if _mode == "violations" and not matches_violation(msg_text(m), _gid):
                        return False
                    return (_now - m.created_at).total_seconds() >= _mins * 60
                try:
                    await channel.purge(limit=min(100, batch), check=is_old, oldest_first=False)
                except Exception as e:
                    print(f"Startup purge failed for {channel_id_str}: {e}", flush=True)
            except Exception:
                continue

@bot.event
async def on_message(message: discord.Message):
    # ignore bots and DMs
    if message.author.bot or not message.guild:
        await bot.process_commands(message)
        return

    # violation journal: cheap regex hits logged for instant future keyword-purges
    try:
        _jc = msg_text(message)
        if _jc and (tos.contains_severe(_jc) or tos.contains_swear(_jc)):
            journal_hit(message.guild.id, message.channel.id, message.id, message.author.id, _jc[:200])
    except Exception:
        pass

    # exempt roles (trusted staff): skip all auto paths
    try:
        if is_exempt(message.author, get_smart(int(message.guild.id))):
            await bot.process_commands(message)
            return
    except Exception:
        pass

    entry = get_entry_resolved(message.guild.id, message.channel)
    if entry is not None and not message.pinned:
        try:
            # respect start-from date
            start_dt = parse_start_from(entry.get("start_from"))
            if start_dt is not None and message.created_at < start_dt:
                await bot.process_commands(message)
                return
            mode = entry.get("mode", "all")
            sm = get_smart(message.guild.id)
            thresh = sm["threshold"]
            strikes_to_act = sm["strikes_to_act"]
            should_delete = False
            score = 0.0
            src = "none"
            tos_reason = ""
            has_mention = len(getattr(message, "mentions", []) or []) > 0
            # instant class: rape mentions delete immediately, no delay (explicit exception
            # to the never-instant rule). Applies in every mode including purge-only-slur.
            try:
                if tos.is_instant(msg_text(message)):
                    try:
                        c0 = bump_strikes(message.guild.id, message.author.id)
                    except Exception:
                        c0 = -1
                    try:
                        with open(Path(__file__).parent / "deletes.log", "a", encoding="utf-8") as f:
                            f.write(f"{datetime.now(timezone.utc).isoformat()} instant-delete guild={message.guild.id} user={message.author.id} strikes={c0} msg={message.id} text={msg_text(message)[:120]!r}\n")
                    except Exception:
                        pass
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    await bot.process_commands(message)
                    return
            except Exception:
                pass
            if mode == "all":
                should_delete = True
            elif mode in ("violations", "smart"):
                # CORROBORATED deletes only: severe slur/threat/scam, explicit filter,
                # or directed insult + high LLM score. LLM-alone never deletes (stops random-text FPs).
                # mild allowlist (tf/wtf/lol/shit-only): never deleted, skip everything
                try:
                    if tos.is_benign_mild(msg_text(message)):
                        await bot.process_commands(message)
                        return
                except Exception:
                    pass
                # explicit filter list = hard block
                if mode == "violations" and matches_violation(msg_text(message), message.guild.id):
                    should_delete = True
                    src = "filter"
                    try:
                        _, tos_reason = tos.classify_tos(msg_text(message), 1.0)
                    except Exception:
                        pass
                elif tos.live_severe(msg_text(message), sm.get("live_slur_delete", True)):
                    should_delete = True
                    src = "tos-severe"
                    try:
                        _, tos_reason = tos.classify_tos(msg_text(message), 1.0)
                    except Exception:
                        pass
                elif not sm.get("live_slur_delete", True) and tos.is_slur(msg_text(message)):
                    # purge-only slur mode: live chat keeps it, full-server purge removes it
                    await bot.process_commands(message)
                    return
                else:
                    # gather light context for directed check (reply parent fetched, recent not needed for gate)
                    try:
                        is_p, score, src = await asyncio.to_thread(
                            provoc.is_provocative, msg_text(message), thresh
                        )
                    except Exception:
                        is_p, score, src = False, 0.0, "error"
                    try:
                        directed = tos.is_horrible_directed(msg_text(message), has_mention, slurs=sm.get("live_slur_delete", True))
                    except Exception:
                        directed = False
                    if directed and is_p:
                        should_delete = True
                        tos_reason = f"directed + toxicity {score:.2f}"
                    else:
                        # LLM-only high score with no severe/filter/directed -> allow (random benign)
                        should_delete = False
            if not should_delete:
                await bot.process_commands(message)
                return
            # strike counting (count only - every delete still waits full delay, never instant)
            try:
                if mode in ("violations", "smart"):
                    c = bump_strikes(message.guild.id, message.author.id)
                    # TOS reference label
                    try:
                        tos_cat, tos_reason = tos.classify_tos(msg_text(message), score)
                    except Exception:
                        tos_cat, tos_reason = None, ""
                    # log detection
                    try:
                        with open(Path(__file__).parent / "deletes.log", "a", encoding="utf-8") as f:
                            f.write(f"{datetime.now(timezone.utc).isoformat()} provoc-flag guild={message.guild.id} user={message.author.id} strikes={c}/{strikes_to_act} score={score:.2f} src={src} tos={tos_cat or 'none'} reason={tos_reason} msg={message.id} text={msg_text(message)[:120]!r}\n")
                    except Exception:
                        pass
                    try:
                        await maybe_enforce(message.guild, message.author, tos_reason or "repeated violations")
                    except Exception:
                        pass
                    try:
                        await modlog_send(message.guild, f"Flagged <@{message.author.id}> in <#{message.channel.id}> ({tos_cat or 'check'}): {msg_text(message)[:200]}")
                    except Exception:
                        pass
            except Exception:
                pass
            delay = float(entry["minutes"]) * 60
            if delay <= 0:
                await bot.process_commands(message)
                return
            asyncio.create_task(delete_after(message.id, message.channel.id, delay))
        except Exception as e:
            print(f"Schedule failed: {e}")

    # per-user keyword watch (independent of channel config)
    # instant class applies here too (watch or not)
    try:
        if tos.is_instant(msg_text(message)) and not message.pinned:
            try:
                with open(Path(__file__).parent / "deletes.log", "a", encoding="utf-8") as f:
                    f.write(f"{datetime.now(timezone.utc).isoformat()} instant-delete guild={message.guild.id} user={message.author.id} msg={message.id} text={msg_text(message)[:120]!r}\n")
            except Exception:
                pass
            try:
                await message.delete()
            except Exception:
                pass
            await bot.process_commands(message)
            return
    except Exception:
        pass
    try:
        w = get_watch(message.guild.id, message.author.id)
        if w is not None and not message.pinned:
            wflag, wsrc, wscore = False, "none", 0.0
            matched = watch_matches(msg_text(message), w["words"])
            if matched:
                wflag, wsrc = True, f"watch-keyword:{matched}"
            elif w["smart"]:
                # smart on watch: violation-level words in general (severe/filter/directed+LLM), milds pass
                try:
                    if tos.is_benign_mild(msg_text(message)):
                        pass
                    elif tos.live_severe(msg_text(message), get_smart(message.guild.id).get("live_slur_delete", True)):
                        wflag, wsrc = True, "watch-tos-severe"
                    elif matches_violation(msg_text(message), message.guild.id):
                        wflag, wsrc = True, "watch-filter"
                    else:
                        try:
                            sm2 = get_smart(message.guild.id)
                            is_p2, score2, src2 = await asyncio.to_thread(
                                provoc.is_provocative, msg_text(message), sm2["threshold"]
                            )
                            wscore = score2
                            mh2 = len(getattr(message, "mentions", []) or []) > 0
                            try:
                                directed2 = tos.is_horrible_directed(msg_text(message), mh2, slurs=sm2.get("live_slur_delete", True))
                            except Exception:
                                directed2 = False
                            if directed2 and is_p2:
                                wflag, wsrc = True, f"watch-smart:{src2}"
                        except Exception:
                            pass
                except Exception:
                    pass
            if wflag:
                try:
                    c2 = bump_strikes(message.guild.id, message.author.id)
                except Exception:
                    c2 = -1
                try:
                    await maybe_enforce(message.guild, message.author, f"watch: {wsrc}")
                except Exception:
                    pass
                try:
                    await modlog_send(message.guild, f"Watch-flagged <@{message.author.id}> ({wsrc}): {msg_text(message)[:200]}")
                except Exception:
                    pass
                try:
                    with open(Path(__file__).parent / "deletes.log", "a", encoding="utf-8") as f:
                        f.write(f"{datetime.now(timezone.utc).isoformat()} watch-flag guild={message.guild.id} user={message.author.id} strikes={c2} src={wsrc} score={wscore:.2f} msg={message.id} text={msg_text(message)[:120]!r}\n")
                except Exception:
                    pass
                try:
                    wdelay = float(w["minutes"]) * 60
                    if wdelay > 0:
                        asyncio.create_task(delete_after(message.id, message.channel.id, wdelay))
                except Exception:
                    pass
    except Exception as e:
        print(f"Watch failed: {e}")

    await bot.process_commands(message)

@bot.tree.command(name="autodelete-set", description="Auto-delete messages in a channel after N minutes")
@app_commands.describe(
    channel="Channel to auto-delete in",
    minutes="How long to wait before deletion in minutes (e.g. 5, 0.5 = 30s)",
    batch_size="How many messages to check per sweep 5-600 (default 50, over 100 runs multiple 100-bulk calls)",
    active_for_minutes="Optional: auto-stop after this many minutes. Empty = forever",
    mode="all=everything, violations=filter+LLM, smart=LLM only",
    start_from="Optional: only delete messages sent from this date onwards, e.g. 2026-09-16 18:00. Empty = all history",
)
@app_commands.checks.has_permissions(manage_messages=True)
async def autodelete_set(
    interaction: discord.Interaction,
    channel: discord.TextChannel | discord.VoiceChannel,
    minutes: float,
    batch_size: int = 50,
    active_for_minutes: float | None = None,
    mode: str = "all",
    start_from: str | None = None,
):
    if minutes <= 0 or minutes > 10080:  # max 7 days
        await interaction.response.send_message("Minutes must be between 0 and 10080 (7 days).", ephemeral=True)
        return
    if batch_size < 5 or batch_size > 600:
        await interaction.response.send_message("batch_size must be 5-600.", ephemeral=True)
        return
    mode = mode.lower()
    if mode not in ("all", "violations", "smart"):
        await interaction.response.send_message("mode must be 'all', 'violations' or 'smart'.", ephemeral=True)
        return
    if mode == "violations" and not get_filter_words(interaction.guild_id):
        # allow violations with LLM only (filter empty) but warn - LLM still works
        pass
    stop_at = None
    stop_msg = "forever"
    if active_for_minutes is not None:
        if active_for_minutes <= 0 or active_for_minutes > 43200:
            await interaction.response.send_message("active_for_minutes must be 0-43200 (30 days).", ephemeral=True)
            return
        stop_at = (datetime.now(timezone.utc) + timedelta(minutes=active_for_minutes)).isoformat()
        stop_msg = f"for {active_for_minutes} min"
    start_iso = None
    start_msg = ""
    if start_from:
        dt = parse_start_from(start_from)
        if dt is None:
            await interaction.response.send_message(
                "start_from not understood. Use YYYY-MM-DD HH:MM e.g. 2026-09-16 18:00 (UTC).", ephemeral=True
            )
            return
        start_iso = dt.isoformat()
        start_msg = f", from {dt.strftime('%Y-%m-%d %H:%M UTC')} onwards"
    g = config.setdefault(str(interaction.guild_id), {})
    g[str(channel.id)] = {"minutes": minutes, "batch": batch_size, "stop_at": stop_at, "mode": mode, "start_from": start_iso}
    save_config(config)
    await interaction.response.send_message(
        f"Auto-delete enabled in {channel.mention}: wait {minutes} min then delete, mode={mode}, batch {batch_size}, {stop_msg}{start_msg}.",
        ephemeral=True,
    )

@bot.tree.command(name="autodelete-remove", description="Disable auto-delete for a channel")
@app_commands.checks.has_permissions(manage_messages=True)
async def autodelete_remove(interaction: discord.Interaction, channel: discord.TextChannel | discord.VoiceChannel):
    g = config.get(str(interaction.guild_id), {})
    if str(channel.id) in g:
        del g[str(channel.id)]
        save_config(config)
        await interaction.response.send_message(f"Auto-delete disabled in {channel.mention}.", ephemeral=True)
    else:
        await interaction.response.send_message(f"{channel.mention} was not configured.", ephemeral=True)

@bot.tree.command(name="autodelete-list", description="List auto-delete channels")
async def autodelete_list(interaction: discord.Interaction):
    g = config.get(str(interaction.guild_id), {})
    if not g:
        await interaction.response.send_message("No auto-delete channels configured.", ephemeral=True)
        return
    lines = []
    for cid, raw in g.items():
        e = get_entry(int(interaction.guild_id), int(cid))
        if e is None:
            lines.append(f"<#{cid}>: invalid config")
            continue
        stop_txt = ""
        if e.get("stop_at"):
            dt = parse_stop_at(e["stop_at"])
            if dt:
                remaining = (dt - datetime.now(timezone.utc)).total_seconds() / 60
                stop_txt = f", stops in {remaining:.1f} min"
            else:
                stop_txt = ", auto-stop set"
        start_txt = ""
        if e.get("start_from"):
            dt2 = parse_start_from(e["start_from"])
            if dt2:
                start_txt = f", from {dt2.strftime('%Y-%m-%d %H:%M UTC')}"
        lines.append(f"<#{cid}>: wait {e['minutes']} min, mode={e.get('mode','all')}, batch {e['batch']}{start_txt}{stop_txt}")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)

@bot.tree.command(name="filter-add", description="Add a word/phrase to the violation filter")
@app_commands.describe(word="Word or phrase to auto-delete (case-insensitive). E.g. slur, spam link, etc.")
@app_commands.checks.has_permissions(manage_messages=True)
async def filter_add(interaction: discord.Interaction, word: str):
    word = word.strip()
    if len(word) < 2 or len(word) > 100:
        await interaction.response.send_message("Word must be 2-100 chars.", ephemeral=True)
        return
    lst = filters.setdefault(str(interaction.guild_id), [])
    if word.lower() in [w.lower() for w in lst]:
        await interaction.response.send_message(f"'{word}' already in filter.", ephemeral=True)
        return
    if len(lst) >= 200:
        await interaction.response.send_message("Filter list full (200 max). Remove some first.", ephemeral=True)
        return
    lst.append(word)
    save_filters(filters)
    await interaction.response.send_message(f"Added '{word}' to violation filter ({len(lst)} total). Use mode=violations in /autodelete-set to enforce.", ephemeral=True)

@bot.tree.command(name="filter-remove", description="Remove a word from the violation filter")
@app_commands.checks.has_permissions(manage_messages=True)
async def filter_remove(interaction: discord.Interaction, word: str):
    lst = filters.get(str(interaction.guild_id), [])
    for i, w in enumerate(lst):
        if w.lower() == word.strip().lower():
            del lst[i]
            save_filters(filters)
            await interaction.response.send_message(f"Removed '{word}'.", ephemeral=True)
            return
    await interaction.response.send_message(f"'{word}' not found. Use /filter-list to see list.", ephemeral=True)

@bot.tree.command(name="filter-list", description="Show violation filter words")
async def filter_list(interaction: discord.Interaction):
    lst = get_filter_words(interaction.guild_id)
    if not lst:
        await interaction.response.send_message("Filter empty. Add with /filter-add.", ephemeral=True)
        return
    await interaction.response.send_message("Filtered: " + ", ".join(f"'{w}'" for w in lst[:50]), ephemeral=True)

@bot.tree.command(name="filter-clear", description="Clear all filter words")
@app_commands.checks.has_permissions(manage_messages=True)
async def filter_clear(interaction: discord.Interaction):
    filters[str(interaction.guild_id)] = []
    save_filters(filters)
    await interaction.response.send_message("Filter cleared.", ephemeral=True)

@bot.tree.command(name="smart-set", description="Configure tiny-LLM provocative detection + strikes")
@app_commands.describe(
    threshold="0-1, lower = stricter. Default 0.75. e.g. 0.6 catches more, 0.85 only obvious",
    strikes_to_act="Strike counter only (1-10). Every delete still waits full channel delay, never instant.",
    enabled="Turn LLM detection on/off",
    live_slur_delete="ON = slurs deleted live. OFF = slurs stay live, only full-server purge removes them (threats/scams still die live)",
    auto_timeout_strikes="0 = off. N = auto-timeout member at N strikes (then strikes reset)",
    auto_timeout_minutes="Timeout length in minutes (default 10)",
)
@app_commands.checks.has_permissions(manage_messages=True)
async def smart_set(
    interaction: discord.Interaction,
    threshold: float = 0.75,
    strikes_to_act: int = 3,
    enabled: bool = True,
    live_slur_delete: bool = True,
    auto_timeout_strikes: int = 0,
    auto_timeout_minutes: int = 10,
):
    if threshold <= 0 or threshold >= 1:
        await interaction.response.send_message("threshold must be 0-1, e.g. 0.75.", ephemeral=True)
        return
    if strikes_to_act < 1 or strikes_to_act > 10:
        await interaction.response.send_message("strikes_to_act must be 1-10.", ephemeral=True)
        return
    if auto_timeout_strikes < 0 or auto_timeout_strikes > 20:
        await interaction.response.send_message("auto_timeout_strikes must be 0-20.", ephemeral=True)
        return
    if auto_timeout_minutes < 1 or auto_timeout_minutes > 40320:
        await interaction.response.send_message("auto_timeout_minutes must be 1-40320.", ephemeral=True)
        return
    prev = get_smart(interaction.guild_id)
    smart_cfg[str(interaction.guild_id)] = {
        "threshold": threshold,
        "strikes_to_act": strikes_to_act,
        "enabled": enabled,
        "live_slur_delete": bool(live_slur_delete),
        "auto_timeout_strikes": int(auto_timeout_strikes),
        "auto_timeout_minutes": int(auto_timeout_minutes),
        "modlog_channel": prev.get("modlog_channel"),
        "exempt_roles": prev.get("exempt_roles", []),
    }
    _save_json(SMART_FILE, smart_cfg)
    await interaction.response.send_message(
        f"Smart set: threshold={threshold}, strikes_to_act={strikes_to_act} (counter only), enabled={enabled}, live_slur_delete={bool(live_slur_delete)}, auto_timeout={int(auto_timeout_strikes)} strikes -> {int(auto_timeout_minutes)}m. Status: {provoc.load_status()}",
        ephemeral=True,
    )

@bot.tree.command(name="modlog-set", description="Set the staff channel for flag/timeout logs")
@app_commands.describe(channel="Channel for mod logs (empty = disable)")
@app_commands.checks.has_permissions(manage_messages=True)
async def modlog_set(interaction: discord.Interaction, channel: discord.TextChannel | None = None):
    prev = get_smart(interaction.guild_id)
    smart_cfg[str(interaction.guild_id)] = {
        "threshold": prev["threshold"], "strikes_to_act": prev["strikes_to_act"],
        "enabled": prev["enabled"], "live_slur_delete": prev.get("live_slur_delete", True),
        "auto_timeout_strikes": prev.get("auto_timeout_strikes", 0),
        "auto_timeout_minutes": prev.get("auto_timeout_minutes", 10),
        "modlog_channel": str(channel.id) if channel is not None else None,
        "exempt_roles": prev.get("exempt_roles", []),
    }
    _save_json(SMART_FILE, smart_cfg)
    await interaction.response.send_message(
        f"Mod-log {'set to ' + channel.mention if channel else 'disabled'}.", ephemeral=True)

@bot.tree.command(name="exempt-add", description="Exempt a role from smart enforcement")
@app_commands.checks.has_permissions(manage_messages=True)
async def exempt_add(interaction: discord.Interaction, role: discord.Role):
    prev = get_smart(interaction.guild_id)
    lst = [str(x) for x in prev.get("exempt_roles", [])]
    if str(role.id) not in lst:
        lst.append(str(role.id))
    smart_cfg[str(interaction.guild_id)] = {
        "threshold": prev["threshold"], "strikes_to_act": prev["strikes_to_act"],
        "enabled": prev["enabled"], "live_slur_delete": prev.get("live_slur_delete", True),
        "auto_timeout_strikes": prev.get("auto_timeout_strikes", 0),
        "auto_timeout_minutes": prev.get("auto_timeout_minutes", 10),
        "modlog_channel": prev.get("modlog_channel"), "exempt_roles": lst,
    }
    _save_json(SMART_FILE, smart_cfg)
    await interaction.response.send_message(f"{role.mention} exempt from smart enforcement.", ephemeral=True)

@bot.tree.command(name="exempt-remove", description="Remove a role's exemption")
@app_commands.checks.has_permissions(manage_messages=True)
async def exempt_remove(interaction: discord.Interaction, role: discord.Role):
    prev = get_smart(interaction.guild_id)
    lst = [str(x) for x in prev.get("exempt_roles", []) if str(x) != str(role.id)]
    smart_cfg[str(interaction.guild_id)] = {
        "threshold": prev["threshold"], "strikes_to_act": prev["strikes_to_act"],
        "enabled": prev["enabled"], "live_slur_delete": prev.get("live_slur_delete", True),
        "auto_timeout_strikes": prev.get("auto_timeout_strikes", 0),
        "auto_timeout_minutes": prev.get("auto_timeout_minutes", 10),
        "modlog_channel": prev.get("modlog_channel"), "exempt_roles": lst,
    }
    _save_json(SMART_FILE, smart_cfg)
    await interaction.response.send_message(f"{role.mention} exemption removed.", ephemeral=True)

@bot.tree.command(name="exempt-list", description="Show exempt roles")
async def exempt_list(interaction: discord.Interaction):
    lst = get_smart(interaction.guild_id).get("exempt_roles", [])
    if not lst:
        await interaction.response.send_message("No exempt roles.", ephemeral=True)
        return
    await interaction.response.send_message("Exempt: " + ", ".join(f"<@&{r}>" for r in lst[:20]), ephemeral=True)

@bot.tree.command(name="smart-test", description="Test if text looks provocative (no delete)")
@app_commands.describe(text="Text to score")
async def smart_test(interaction: discord.Interaction, text: str):
    # defer first - LLM can take >3s on first load, otherwise Discord shows "no response"
    try:
        await interaction.response.defer(ephemeral=True)
    except Exception:
        pass
    sm = get_smart(interaction.guild_id)
    try:
        is_p, score, src = await asyncio.to_thread(provoc.is_provocative, text, sm["threshold"])
        tos_cat, tos_reason = tos.classify_tos(text, score)
    except Exception as e:
        try:
            await interaction.followup.send(f"Test failed: {e}", ephemeral=True)
        except Exception:
            pass
        return
    try:
        await interaction.followup.send(
            f"score={score:.2f} threshold={sm['threshold']} src={src} tos={tos_cat or 'none'}\n{tos_reason}\n-> {'PROVOCATIVE (would delete)' if is_p else 'clean'}",
            ephemeral=True,
        )
    except Exception:
        pass

@bot.tree.command(name="tos-check", description="Check text against Discord Guidelines reference (no delete)")
@app_commands.describe(text="Text to check")
async def tos_check(interaction: discord.Interaction, text: str):
    try:
        await interaction.response.defer(ephemeral=True)
    except Exception:
        pass
    sm = get_smart(interaction.guild_id)
    try:
        is_p, score, src = await asyncio.to_thread(provoc.is_provocative, text, sm["threshold"])
        tos_cat, tos_reason = tos.classify_tos(text, score)
    except Exception as e:
        try:
            await interaction.followup.send(f"Check failed: {e}", ephemeral=True)
        except Exception:
            pass
        return
    try:
        await interaction.followup.send(
            f"TOS ref (summarized, official: https://discord.com/guidelines):\nCategory: {tos_cat or 'none - no keyword/TOS match'}\n{tos_reason}\nToxicity score: {score:.2f} ({src})\n-> {'Would delete in violations/smart mode' if (is_p or tos_cat) else 'Clean'}",
            ephemeral=True,
        )
    except Exception:
        pass

@bot.tree.command(name="tos-list", description="Show Discord Guidelines reference categories")
async def tos_list(interaction: discord.Interaction):
    await interaction.response.send_message(tos.tos_list_text(), ephemeral=True)

@bot.tree.command(name="smart-status", description="Show LLM status + strikes config")
async def smart_status(interaction: discord.Interaction):
    try:
        await interaction.response.defer(ephemeral=True)
    except Exception:
        pass
    sm = get_smart(interaction.guild_id)
    try:
        status = await asyncio.to_thread(provoc.load_status)
    except Exception as e:
        status = f"status failed: {e}"
    try:
        await interaction.followup.send(
            f"{status}\nthreshold={sm['threshold']}, strikes_to_act={sm['strikes_to_act']}, enabled={sm['enabled']}, live_slur_delete={sm.get('live_slur_delete', True)}, auto_timeout={sm.get('auto_timeout_strikes', 0)}x->{sm.get('auto_timeout_minutes', 10)}m, modlog={sm.get('modlog_channel')}, exempt={len(sm.get('exempt_roles', []))}",
            ephemeral=True,
        )
    except Exception:
        pass

@bot.tree.command(name="strikes-check", description="Check a user's provocative strikes")
@app_commands.describe(user="User to check")
async def strikes_check(interaction: discord.Interaction, user: discord.User):
    g = strikes.get(str(interaction.guild_id), {})
    e = g.get(str(user.id), {"count": 0})
    await interaction.response.send_message(f"{user.mention} strikes: {e.get('count',0)}", ephemeral=True)

@bot.tree.command(name="strikes-reset", description="Reset a user's strikes")
@app_commands.checks.has_permissions(manage_messages=True)
async def strikes_reset(interaction: discord.Interaction, user: discord.User):
    g = strikes.get(str(interaction.guild_id), {})
    if str(user.id) in g:
        del g[str(user.id)]
        _save_json(STRIKES_FILE, strikes)
    await interaction.response.send_message(f"Strikes reset for {user.mention}.", ephemeral=True)

@bot.tree.command(name="userwatch-set", description="Watch a specific user: set delay, batch, smart mode")
@app_commands.describe(
    user="User to watch",
    minutes="How long to wait before deleting their flagged messages (default 1.0)",
    batch_size="How many messages to scan per sweep 5-600 (default 50)",
    smart="ON = also delete their violation-level words in general (LLM+TOS), OFF = only your keywords",
)
@app_commands.checks.has_permissions(manage_messages=True)
async def userwatch_set(
    interaction: discord.Interaction,
    user: discord.User,
    minutes: float = 1.0,
    batch_size: int = 50,
    smart: bool = False,
):
    if minutes <= 0 or minutes > 10080:
        await interaction.response.send_message("Minutes must be 0-10080.", ephemeral=True)
        return
    if batch_size < 5 or batch_size > 600:
        await interaction.response.send_message("batch_size must be 5-600.", ephemeral=True)
        return
    g = watches.setdefault(str(interaction.guild_id), {})
    e = g.get(str(user.id), {})
    if not isinstance(e, dict):
        e = {}
    e["minutes"] = minutes
    e["batch"] = batch_size
    e["smart"] = bool(smart)
    e.setdefault("words", [])
    g[str(user.id)] = e
    _save_json(WATCH_FILE, watches)
    await interaction.response.send_message(
        f"Watching {user.mention}: wait {minutes} min, batch {batch_size}, smart={bool(smart)}, keywords={len(e.get('words', []))}. Add words with /userwatch-addword.",
        ephemeral=True,
    )

@bot.tree.command(name="userwatch-addword", description="Add a keyword to delete from a watched user")
@app_commands.describe(user="Watched user", word="Keyword (case-insensitive, evasion-aware)")
@app_commands.checks.has_permissions(manage_messages=True)
async def userwatch_addword(interaction: discord.Interaction, user: discord.User, word: str):
    word = word.strip().lower()
    if len(word) < 2 or len(word) > 50:
        await interaction.response.send_message("Word must be 2-50 chars.", ephemeral=True)
        return
    g = watches.setdefault(str(interaction.guild_id), {})
    e = g.setdefault(str(user.id), {"words": [], "minutes": 1.0, "batch": 50, "smart": False})
    lst = e.setdefault("words", [])
    if word in lst:
        await interaction.response.send_message(f"'{word}' already watched for {user.mention}.", ephemeral=True)
        return
    if len(lst) >= 100:
        await interaction.response.send_message("Word list full (100).", ephemeral=True)
        return
    lst.append(word)
    _save_json(WATCH_FILE, watches)
    await interaction.response.send_message(f"Added '{word}' for {user.mention} ({len(lst)} total).", ephemeral=True)

@bot.tree.command(name="userwatch-removeword", description="Remove a keyword from a watched user")
@app_commands.checks.has_permissions(manage_messages=True)
async def userwatch_removeword(interaction: discord.Interaction, user: discord.User, word: str):
    g = watches.get(str(interaction.guild_id), {})
    e = g.get(str(user.id))
    if not e or word.strip().lower() not in [w.lower() for w in e.get("words", [])]:
        await interaction.response.send_message("Not found. See /userwatch-list.", ephemeral=True)
        return
    e["words"] = [w for w in e["words"] if w.lower() != word.strip().lower()]
    _save_json(WATCH_FILE, watches)
    await interaction.response.send_message(f"Removed '{word}' for {user.mention}.", ephemeral=True)

@bot.tree.command(name="userwatch-list", description="Show watched users + keywords")
async def userwatch_list(interaction: discord.Interaction):
    g = watches.get(str(interaction.guild_id), {})
    if not g:
        await interaction.response.send_message("No users watched.", ephemeral=True)
        return
    lines = []
    for uid, e in g.items():
        if not isinstance(e, dict):
            continue
        lines.append(f"<@{uid}>: wait {e.get('minutes',1.0)} min, batch {e.get('batch',50)}, smart={e.get('smart',False)}, words={', '.join(repr(w) for w in e.get('words',[])[:20]) or 'none'}")
    await interaction.response.send_message("\n".join(lines)[:1800], ephemeral=True)

@bot.tree.command(name="userwatch-clear", description="Stop watching a user")
@app_commands.checks.has_permissions(manage_messages=True)
async def userwatch_clear(interaction: discord.Interaction, user: discord.User):
    g = watches.get(str(interaction.guild_id), {})
    if str(user.id) in g:
        del g[str(user.id)]
        _save_json(WATCH_FILE, watches)
    await interaction.response.send_message(f"Stopped watching {user.mention}.", ephemeral=True)

@bot.tree.command(name="user-purge", description="Delete TOS-violating messages: one user or whole server")
@app_commands.describe(
    user="Whose violating messages to delete (empty = WHOLE SERVER, everyone)",
    scope="serverwide = all text channels, channel = one channel only",
    channel="Only used when scope=channel (empty = current channel)",
    limit="Messages to scan per channel 100-20000 (default 1000, ignored when full=True)",
    smart="ON = LLM judges TOS violations too (slower). OFF = only slurs/threats/filter words (fast, no model FPs)",
    full="ON = scan EVERY message ever (slow, can take hours on big servers). OFF = recent limit only",
    order="newest = recent first (default). oldest = channel creation forward - kills deep history first",
    report_only="ON = just report what WOULD be deleted (same as /user-report), delete nothing",
)
@app_commands.choices(
    scope=[
        app_commands.Choice(name="serverwide (all channels)", value="server"),
        app_commands.Choice(name="this channel only", value="channel"),
    ],
    order=[
        app_commands.Choice(name="newest first", value="newest"),
        app_commands.Choice(name="oldest first (deep history)", value="oldest"),
    ],
)
@app_commands.checks.has_permissions(manage_messages=True)
async def user_purge(
    interaction: discord.Interaction,
    scope: str = "server",
    channel: discord.TextChannel | discord.VoiceChannel | None = None,
    limit: int = 1000,
    smart: bool = True,
    full: bool = False,
    user: discord.User | None = None,
    order: str = "newest",
    report_only: bool = False,
):
    try:
        await interaction.response.defer(ephemeral=True)
    except Exception:
        pass
    if limit < 100 or limit > 20000:
        if not full:
            try:
                await interaction.followup.send("limit must be 100-20000.", ephemeral=True)
            except Exception:
                pass
            return
    guild = interaction.guild
    if guild is None:
        try:
            await interaction.followup.send("Guild only.", ephemeral=True)
        except Exception:
            pass
        return
    targets: list
    if scope == "channel":
        ch = channel
        if ch is None:
            try:
                ch = interaction.channel
            except Exception:
                ch = None
        if ch is None or not hasattr(ch, "history"):
            try:
                await interaction.followup.send("Pick a text channel for scope=channel.", ephemeral=True)
            except Exception:
                pass
            return
        targets = [ch]
    else:
        # every message ever = every channel, no cap (full mode is explicitly slow)
        targets = list(getattr(guild, "text_channels", [])) + list(getattr(guild, "voice_channels", []))
    lock_path = Path(__file__).parent / "purge.lock"
    uid = int(user.id) if user is not None else None
    tlabel = user.mention if user is not None else "the whole server"
    report_samples: list = []
    try:
        lock_path.write_text(json.dumps({
            "guild": str(guild.id), "target": str(uid) if uid is not None else "ALL",
            "by": str(interaction.user.id), "started": datetime.now(timezone.utc).isoformat(),
            "scope": scope, "full": full, "kind": "user-report" if report_only else "user-purge",
        }), encoding="utf-8")
    except Exception:
        pass
    # pause the 15s auto-sweeper during purges: it fights the purge for rate limits and halves speed.
    # report-only runs delete nothing, so live protection stays on.
    sweep_was_running = False
    if not report_only:
        try:
            if sweep_loop.is_running():
                sweep_loop.stop()
                sweep_was_running = True
        except Exception:
            pass
    last_progress_dm = [0.0]
    try:
        await interaction.user.send(
            f"Purge started ({'whole server' if uid is None else 'one user'}, {'entire history' if full else 'recent messages'}). I'll message you every minute and ping you when it's finished."
        )
        last_progress_dm[0] = datetime.now(timezone.utc).timestamp()
    except Exception:
        pass

    async def _purge_progress():
        try:
            lock_path.write_text(json.dumps({
            "guild": str(guild.id), "target": str(uid) if uid is not None else "ALL",
            "by": str(interaction.user.id), "started": datetime.now(timezone.utc).isoformat(),
            "scope": scope, "full": full, "kind": "user-report" if report_only else "user-purge",
            "channels_done": channels_done,
            "total": grand_total[0], "current": list(current_names)[:3],
            "scanned": total_scanned, "mine": total_mine, "matched": total_matched, "deleted": total_deleted,
        }), encoding="utf-8")
        except Exception:
            pass
        try:
            save_flaglist(flaglist)
        except Exception:
            pass
        try:
            now_ts = datetime.now(timezone.utc).timestamp()
            if now_ts - last_progress_dm[0] >= 60:
                last_progress_dm[0] = now_ts
                pct = ""
                try:
                    if grand_total[0]:
                        pct = f" ({round(100 * channels_done / grand_total[0])}% - {channels_done}/{grand_total[0]} chats)"
                except Exception:
                    pass
                await interaction.user.send(
                    f"Still working{pct}: read {total_scanned} messages"
                    + (f", {total_mine} from them" if uid is not None else "")
                    + (
                        f", found {total_matched} rule-breaking so far (report only, deleting nothing)."
                        if report_only else
                        f", removed {total_deleted} rule-breaking so far."
                    )
                )
        except Exception:
            pass
    now = datetime.now(timezone.utc)
    smp = get_smart(int(guild.id))
    try:
        me = guild.me
    except Exception:
        me = None
    total_scanned, total_checked, total_matched, total_deleted, total_old_single, channels_done = 0, 0, 0, 0, 0, 0
    total_mine = 0
    failed_refs: list = []
    current_names: list = []
    grand_total = [0]
    cursors = load_cursors()
    gcur = cursors.setdefault(str(guild.id), {})
    current_names: list = []
    grand_total = [0]
    skipped_no_perm: list = []
    channel_errors: list = []
    capped_old_skipped = [0]
    old_cap_each = 1000 if full else 100

    async def _bulk_del(container, buf):
        """Delete a batch in 100s (Discord's bulk cap). Returns count deleted; failures go to retry list."""
        n = 0
        for k in range(0, len(buf), 100):
            chunk = buf[k : k + 100]
            try:
                if len(chunk) == 1:
                    await chunk[0].delete()
                elif chunk:
                    await container.delete_messages(chunk)
                n += len(chunk)
            except discord.Forbidden as e:
                channel_errors.append(f"#{getattr(container, 'name', getattr(container, 'id', '?'))}: no delete permission ({e.status})")
                for m in chunk:
                    try:
                        await m.delete()
                        n += 1
                        await asyncio.sleep(0.5)
                    except Exception:
                        failed_refs.append((container, int(m.id)))
                        flag_add(int(guild.id), int(getattr(container, "id", 0)), int(m.id), "no delete permission")
            except discord.HTTPException as e:
                channel_errors.append(f"#{getattr(container, 'name', getattr(container, 'id', '?'))}: bulk failed ({e.status}), retrying singly")
                for m in chunk:
                    try:
                        await m.delete()
                        n += 1
                        await asyncio.sleep(0.5)
                    except Exception:
                        failed_refs.append((container, int(m.id)))
                        flag_add(int(guild.id), int(getattr(container, "id", 0)), int(m.id), f"bulk failed {e.status}")
            except Exception as e:
                channel_errors.append(f"#{getattr(container, 'name', getattr(container, 'id', '?'))}: {e}")
                for m in chunk:
                    try:
                        failed_refs.append((container, int(m.id)))
                        flag_add(int(guild.id), int(getattr(container, "id", 0)), int(m.id), "delete error")
                    except Exception:
                        pass
            await asyncio.sleep(0.4)
        return n

    async def _matches(m) -> bool:
        """TOS-only decision shared by channel + thread scans."""
        nonlocal total_checked
        try:
            content = msg_text(m)
            if tos.contains_severe(content):
                return True
            if tos.contains_swear(content):
                return True
            if matches_violation(content, int(guild.id)):
                return True
            # full-scale purge takes milds too (tf/wtf/lol-only etc.) - live modes still spare them
            if full:
                try:
                    if tos.is_benign_mild(content):
                        return True
                except Exception:
                    pass
            if not smart:
                return False
            s, _ = await asyncio.to_thread(provoc.score_text, content)
            total_checked += 1
            return s >= smp["threshold"]
        except Exception:
            return False

    def _age_split(m, fresh, old):
        try:
            age_days = (now - m.created_at).days
        except Exception:
            age_days = 0
        if age_days >= 14:
            old.append(m)
        else:
            fresh.append(m)

    rev = (order == "oldest")
    if rev and not full:
        try:
            await interaction.followup.send("order=oldest needs full=True - forcing full scan.", ephemeral=True)
        except Exception:
            pass
        full = True

    async def _scan_container(container, hist_limit, resume_before=None, oldest_first=False):
        """Stream a channel/thread history, deleting matches incrementally. Returns True on completion."""
        nonlocal total_mine, total_scanned, total_checked, total_matched, total_deleted, total_old_single
        oldies = 0
        fresh: list = []
        old: list = []
        reasons: dict = {}
        ckey = f"{getattr(container, 'id', '?')}:rev" if oldest_first else str(getattr(container, "id", "?"))
        natural_end = [False]
        try:
            # threads inherit parent channel perms (Thread.permissions_for is unreliable)
            perm_source = getattr(container, "parent", None) or container
            try:
                perms = perm_source.permissions_for(me) if me is not None else None
            except Exception:
                perms = None
            if perms is not None and (not perms.read_message_history or not perms.manage_messages):
                skipped_no_perm.append(getattr(container, "name", str(getattr(container, "id", "?"))))
                return True
        except Exception:
            pass
        try:
            # pass 1: stream history; matches delete INCREMENTALLY so big channels show progress
            pending: list = []

            async def _flush_fresh():
                nonlocal total_deleted
                if fresh:
                    if report_only:
                        try:
                            for m in fresh[:30 - len(report_samples)] if len(report_samples) < 30 else []:
                                report_samples.append((int(getattr(container, "id", 0)), int(m.id), reasons.get(int(m.id), "?")))
                        except Exception:
                            pass
                        fresh.clear()
                        await _purge_progress()
                        return
                    total_deleted += await _bulk_del(container, fresh)
                    fresh.clear()
                    await _purge_progress()

            async def _flush_old():
                nonlocal oldies, total_deleted, total_old_single
                n = 0
                while old:
                    m0 = old.pop(0)
                    if report_only:
                        try:
                            if len(report_samples) < 30:
                                report_samples.append((int(getattr(container, "id", 0)), int(m0.id), reasons.get(int(m0.id), "?")))
                        except Exception:
                            pass
                        continue
                    if not full and oldies >= old_cap_each:
                        capped_old_skipped[0] += 1
                        flag_add(int(guild.id), int(getattr(container, "id", 0)), int(m0.id), "over per-run singles cap")
                        continue
                    try:
                        err = await smart_delete(container, m0)
                        if err is None:
                            oldies += 1
                            total_old_single += 1
                            total_deleted += 1
                        elif "already gone" in err:
                            pass
                        else:
                            failed_refs.append((container, int(m0.id)))
                            flag_add(int(guild.id), int(getattr(container, "id", 0)), int(m0.id), err)
                        n += 1
                        await asyncio.sleep(0.5)
                    except Exception:
                        try:
                            failed_refs.append((container, int(m0.id)))
                            flag_add(int(guild.id), int(getattr(container, "id", 0)), int(m0.id), "single delete failed")
                        except Exception:
                            pass
                    if n % 10 == 0:
                        await _purge_progress()
            if resume_before:
                try:
                    _rk = {"before": discord.Object(id=int(resume_before))} if not oldest_first else {"after": discord.Object(id=int(resume_before))}
                except Exception:
                    _rk = {}
            else:
                _rk = {}
            async for m in container.history(limit=hist_limit, oldest_first=oldest_first, **_rk):
                total_scanned += 1
                if total_scanned % 2000 == 0:
                    try:
                        gcur[ckey] = str(m.id)
                        save_cursors(cursors)
                    except Exception:
                        pass
                    await _purge_progress()
                try:
                    if m.pinned or m.author.bot:
                        continue
                    if uid is not None and int(m.author.id) != uid:
                        continue
                    total_mine += 1
                except Exception:
                    continue
                try:
                    content = msg_text(m)
                    if tos.contains_severe(content) or tos.contains_swear(content):
                        total_matched += 1
                        try:
                            _cat0, _rsn0 = tos.classify_tos(content, 1.0)
                            reasons[int(m.id)] = _rsn0 or "severe match"
                        except Exception:
                            pass
                        _age_split(m, fresh, old)
                    elif matches_violation(content, int(guild.id)):
                        total_matched += 1
                        try:
                            reasons[int(m.id)] = "filter word"
                        except Exception:
                            pass
                        _age_split(m, fresh, old)
                    elif smart:
                        pending.append(m)
                except Exception:
                    continue
                if len(fresh) >= 100:
                    await _flush_fresh()
                if len(old) >= 10:
                    await _flush_old()
            natural_end[0] = True
            try:
                # fully read: no resume point needed anymore
                if ckey in gcur:
                    del gcur[ckey]
                    save_cursors(cursors)
            except Exception:
                pass
            # pass 2: one batched LLM forward pass per 32 candidates (~5-10x faster than one-by-one)
            if pending:
                try:
                    batch_scores = await asyncio.to_thread(
                        provoc.score_batch, [msg_text(p) for p in pending], 32
                    )
                except Exception:
                    batch_scores = [(0.0, "error")] * len(pending)
                total_checked += len(pending)
                for m, (s, _src) in zip(pending, batch_scores):
                    try:
                        if s >= smp["threshold"]:
                            total_matched += 1
                            try:
                                _cat1, _rsn1 = tos.classify_tos(msg_text(m), s)
                                reasons[int(m.id)] = f"toxicity {s:.2f}" + (f" ({_rsn1})" if _rsn1 else "")
                            except Exception:
                                pass
                            _age_split(m, fresh, old)
                    except Exception:
                        continue
            # delete phase: drain leftovers (bulk fresh, singles for old - no cap in full mode)
            await _flush_fresh()
            await _flush_old()
        except Exception as e:
            channel_errors.append(f"#{getattr(container, 'name', getattr(container, 'id', '?'))}: scan failed ({e})")
        finally:
            # anything matched-but-undeleted (timeout abort etc.) routes to the flag list.
            # pending is deliberately excluded: unscored, never flagged, must not be listed.
            # in report mode they ALSO join the samples so the report never says "found N" with zero links.
            try:
                leftovers = 0
                for m in list(fresh) + list(old):
                    try:
                        flag_add(int(guild.id), int(getattr(container, "id", 0)), int(m.id), "interrupted mid-channel")
                        leftovers += 1
                        if report_only and len(report_samples) < 30:
                            try:
                                report_samples.append((int(getattr(container, "id", 0)), int(m.id), reasons.get(int(m.id), "interrupted")))
                            except Exception:
                                pass
                    except Exception:
                        pass
                if leftovers:
                    channel_errors.append(f"#{getattr(container, 'name', getattr(container, 'id', '?'))}: {leftovers} matched but interrupted, sent to flag list")
            except Exception:
                pass
        return True

    # collect thread targets when full=True (active threads + best-effort archived)
    thread_targets: list = []
    if full:
        try:
            for t in list(getattr(guild, "threads", []) or []):
                try:
                    parent = getattr(t, "parent", None)
                    if scope == "channel" and parent is not None and channel is not None and int(parent.id) != int(channel.id):
                        continue
                    thread_targets.append(t)
                except Exception:
                    continue
        except Exception:
            pass
        for ch in targets:
            try:
                async def _arch():
                    async for t in ch.archived_threads(limit=25):
                        thread_targets.append(t)
                        await asyncio.sleep(0.2)
                await asyncio.wait_for(_arch(), timeout=120)
            except Exception:
                pass

    if full:
        try:
            await interaction.followup.send(
                f"Deep purge started ({len(targets)} chats + {len(thread_targets)} threads, entire history). This takes a while - I'll keep you posted here and by DM.",
                ephemeral=True,
            )
        except Exception:
            pass
    # 3 chats at once normally; 2 in full mode (less 429 contention on giant histories)
    group_size = 2 if full else 3

    async def _scan_guarded(container, hist_limit):
        try:
            # 20-min watchdog per chat: a hung page/fetch can't freeze the whole run.
            # resume cursor lets the next run continue deeper instead of restarting at newest.
            resume = None
            try:
                if hist_limit is None:
                    key = f"{getattr(container, 'id', '?')}:rev" if rev else str(getattr(container, "id", "?"))
                    resume = gcur.get(key)
            except Exception:
                resume = None
            try:
                await asyncio.wait_for(_scan_container(container, hist_limit, resume, rev), timeout=1200)
            except asyncio.TimeoutError:
                channel_errors.append(f"#{getattr(container, 'name', getattr(container, 'id', '?'))}: timed out after 20m, skipped (re-run to resume it)")
            return True
        except Exception as e:
            try:
                print(f"Purge failed #{getattr(container, 'id', '?')}: {e}", flush=True)
            except Exception:
                pass
            return False

    all_targets = [(ch, None if full else limit) for ch in targets] + [(t, None) for t in thread_targets]
    grand_total[0] = len(all_targets)
    await _purge_progress()
    for i in range(0, len(all_targets), group_size):
        group = all_targets[i : i + group_size]
        try:
            current_names[:] = [str(getattr(c, "name", getattr(c, "id", "?"))) for c, _h in group]
        except Exception:
            pass
        try:
            results = await asyncio.gather(*[_scan_guarded(c, h) for c, h in group])
        except Exception:
            continue
        channels_done += sum(1 for r in results if r)
        await _purge_progress()
    current_names[:] = []
    # retry pass: everything flagged must go - re-fetch failures singly (cap 2000).
    # Anything still failing lands in the persistent flag list for /flag-delete.
    # Skipped entirely in report mode (nothing was deleted, nothing to retry).
    retried = 0
    seen_retry = set()
    for container, mid in list(failed_refs)[:2000]:
        try:
            if mid in seen_retry:
                continue
            seen_retry.add(mid)
            err = await smart_delete(container, mid)
            if err is None:
                retried += 1
                total_deleted += 1
            elif "already gone" in err:
                pass
            else:
                try:
                    flag_add(int(guild.id), int(getattr(container, "id", 0)), int(mid), err or "retry failed")
                except Exception:
                    pass
            await asyncio.sleep(0.5)
        except Exception:
            try:
                flag_add(int(guild.id), int(getattr(container, "id", 0)), int(mid), "retry failed")
            except Exception:
                pass
    if retried:
        try:
            await _purge_progress()
        except Exception:
            pass
    try:
        save_flaglist(flaglist)
    except Exception:
        pass
    failed_left = max(0, total_matched - total_deleted)
    try:
        save_flaglist(flaglist)
        flag_n = len(flaglist.get(str(guild.id), []))
    except Exception:
        flag_n = 0
    who = "everyone" if uid is None else tlabel
    if uid is None:
        scope_line = f"Read through about {total_scanned} messages from everyone, "
    else:
        scope_line = f"Read through about {total_scanned} messages in total ({total_mine} sent by them), "
    if report_only:
        links = []
        for _cid, _mid, *_rest in report_samples[:15]:
            try:
                _rsn = _rest[0] if _rest else "?"
                links.append(f"https://discord.com/channels/{interaction.guild_id}/{_cid}/{_mid} ({_rsn})")
            except Exception:
                continue
        summary = (
            f"REPORT (nothing deleted) for {who} ({'entire history' if full else 'recent messages'}).\n"
            + scope_line +
            f"found {total_matched} rule-breaking."
        )
        if links:
            summary += " Samples:\n" + "\n".join(links)
            if total_matched > len(links):
                summary += f"\n...and {total_matched - len(links)} more like these."
    else:
        summary = (
            f"DONE purging {who} ({'entire history' if full else 'recent messages'}).\n"
            + scope_line +
            f"found {total_matched} rule-breaking and deleted {total_deleted}."
        )
    if failed_left and not report_only:
        summary += f" {failed_left} could not be deleted (no permission or already gone)."
    if flag_n:
        summary += f" {flag_n} sitting in the flag list - run /flag-delete to take them."
    if skipped_no_perm:
        summary += f" Skipped (no access): {', '.join(skipped_no_perm[:10])}."
    if channel_errors:
        summary += f" Hiccups: {'; '.join(channel_errors[:5])}"
    try:
        with open(Path(__file__).parent / "deletes.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} {'audit-report' if report_only else 'purge-summary'} guild={interaction.guild_id} user={str(uid) if uid is not None else 'ALL'} smart={smart} scanned={total_scanned} mine={total_mine} matched={total_matched} deleted={total_deleted} skipped={skipped_no_perm} errors={channel_errors[:5]}\n")
    except Exception:
        pass
    try:
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass
    except Exception:
        pass
    try:
        if sweep_was_running and not sweep_loop.is_running():
            sweep_loop.start()
    except Exception:
        pass
    # deliver twice on purpose: reply window may be dead on long runs, DMs don't expire.
    # each attempt is logged so delivery is provable, not assumed.
    try:
        await interaction.followup.send(summary[:1800], ephemeral=True)
        dlv = "reply-ok"
    except Exception as e:
        dlv = f"reply-fail({str(e)[:60]})"
    try:
        await interaction.user.send(summary[:1800])
        dlv += "+dm-ok"
    except Exception as e:
        dlv += f"+dm-fail({str(e)[:60]})"
    try:
        with open(Path(__file__).parent / "deletes.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} report-delivery guild={interaction.guild_id} {dlv}\n")
    except Exception:
        pass

@bot.tree.command(name="user-report", description="Report a user's TOS violations with links (deletes nothing)")
@app_commands.describe(
    user="Whose history to report (empty = whole server, everyone)",
    scope="serverwide = all text channels, channel = one channel only",
    channel="Only used when scope=channel (empty = current channel)",
    limit="Messages to scan per channel 100-20000 (default 1000)",
    smart="ON = LLM judges too (slower). OFF = only slurs/threats/filter words",
    full="ON = entire history. OFF = recent limit only",
    order="newest = recent first. oldest = channel creation forward",
)
@app_commands.choices(
    scope=[
        app_commands.Choice(name="serverwide (all channels)", value="server"),
        app_commands.Choice(name="this channel only", value="channel"),
    ],
    order=[
        app_commands.Choice(name="newest first", value="newest"),
        app_commands.Choice(name="oldest first (deep history)", value="oldest"),
    ],
)
@app_commands.checks.has_permissions(manage_messages=True)
async def user_report(
    interaction: discord.Interaction,
    scope: str = "server",
    channel: discord.TextChannel | discord.VoiceChannel | None = None,
    limit: int = 1000,
    smart: bool = True,
    full: bool = False,
    user: discord.User | None = None,
    order: str = "newest",
):
    await user_purge.callback(
        interaction, scope=scope, channel=channel, limit=limit,
        smart=smart, full=True, user=user, order=order, report_only=True,
    )

@bot.tree.command(name="purge-status", description="Show recent purge reports for this server")
async def purge_status(interaction: discord.Interaction):
    try:
        lines = Path(__file__).parent.joinpath("deletes.log").read_text(encoding="utf-8").splitlines()
    except Exception:
        lines = []
    gid = str(interaction.guild_id)
    out = []
    try:
        lock_p = Path(__file__).parent.joinpath("purge.lock")
        lock = json.loads(lock_p.read_text(encoding="utf-8"))
        if str(lock.get("guild")) == gid:
            try:
                done_n, total_n = int(lock.get("channels_done", 0)), int(lock.get("total", 0))
                pct = f"{round(100 * done_n / total_n)}% ({done_n}/{total_n} chats)" if total_n else f"{done_n} chats"
            except Exception:
                pct = f"{lock.get('channels_done', 0)} chats"
            try:
                age_s = int(datetime.now(timezone.utc).timestamp() - lock_p.stat().st_mtime)
                stale = f" - quiet for {age_s // 60}m{age_s % 60}s, may be grinding a huge chat" if age_s > 180 else ""
            except Exception:
                stale = ""
            cur = ", ".join(lock.get("current", []) or [])
            if lock.get("kind") == "keyword":
                out.append(f"Still checking keyword '{lock.get('keyword', '?')}': {pct} done{', now on ' + cur if cur else ''}. Read {lock.get('scanned', 0)}, removed {lock.get('deleted', 0)} so far.{stale}")
            elif lock.get("kind") == "user-report":
                tgt = lock.get("target")
                tgt_txt = "everyone" if tgt == "ALL" else f"<@{tgt}>"
                out.append(f"Still auditing {tgt_txt} (report only, deleting nothing): {pct} done{', now on ' + cur if cur else ''}. Read {lock.get('scanned', 0)}, found {lock.get('matched', 0)} so far.{stale}")
            else:
                tgt = lock.get("target")
                tgt_txt = "everyone" if tgt == "ALL" else f"<@{tgt}>"
                out.append(f"Still checking {tgt_txt}: {pct} done{', now on ' + cur if cur else ''}. Read {lock.get('scanned', 0)}, removed {lock.get('deleted', 0)} rule-breaking so far.{stale}")
    except Exception:
        pass
    hits = [l for l in lines if "purge-summary" in l and f"guild={gid}" in l][-5:]
    if not hits and not out:
        await interaction.response.send_message("No purge reports yet for this server.", ephemeral=True)
        return
    for h in hits:
        try:
            ts = h.split(" ")[0]
            rest = h.split("purge-summary ", 1)[1]
            out.append(f"{ts}: {rest[:400]}")
        except Exception:
            out.append(h[:400])
    await interaction.response.send_message("\n".join(out)[:1800], ephemeral=True)

@bot.tree.command(name="flag-list", description="Show messages flagged but not deleted")
async def flag_list(interaction: discord.Interaction):
    g = flaglist.get(str(interaction.guild_id), [])
    if not g:
        await interaction.response.send_message("Flag list is empty - nothing left over.", ephemeral=True)
        return
    lines = []
    for e in g[-25:]:
        try:
            link = f"https://discord.com/channels/{interaction.guild_id}/{e.get('ch')}/{e.get('msg')}"
            lines.append(f"{link} ({e.get('reason', '?')})")
        except Exception:
            continue
    msg = f"{len(g)} flagged, undeleted:\n" + "\n".join(lines)
    if len(g) > 25:
        msg += f"\n...and {len(g) - 25} more. Run /flag-delete to clear them."
    await interaction.response.send_message(msg[:1800], ephemeral=True)

@bot.tree.command(name="flag-delete", description="Delete everything sitting in the flag list")
@app_commands.checks.has_permissions(manage_messages=True)
async def flag_delete(interaction: discord.Interaction):
    import time as _time_mod

    try:
        await interaction.response.defer(ephemeral=True)
    except Exception:
        pass
    g = flaglist.get(str(interaction.guild_id), [])
    if not g:
        try:
            await interaction.followup.send("Flag list is empty - nothing to delete.", ephemeral=True)
        except Exception:
            pass
        return
    total_n = len(g)
    try:
        await interaction.user.send(f"Flag-delete started: {total_n} to go through. Updates every minute.")
    except Exception:
        pass
    try:
        with open(Path(__file__).parent / "deletes.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} flagdelete-start guild={interaction.guild_id} n={total_n}\n")
    except Exception:
        pass
    done, failed, since_save, last_dm = 0, 0, 0, _time_mod.monotonic()
    # group by channel: recent ones go 100-per-call by ID (no fetch), rest direct-ID singles
    by_ch: dict = {}
    for e in list(g):
        try:
            by_ch.setdefault(str(int(e.get("ch", 0))), []).append(e)
        except Exception:
            continue

    async def _fd_progress():
        nonlocal since_save, last_dm
        since_save += 1
        if since_save >= 50:
            since_save = 0
            try:
                save_flaglist(flaglist)
            except Exception:
                pass
            try:
                with open(Path(__file__).parent / "deletes.log", "a", encoding="utf-8") as f:
                    f.write(f"{datetime.now(timezone.utc).isoformat()} flagdelete-progress guild={interaction.guild_id} done={done} failed={failed} left={len(g)}\n")
            except Exception:
                pass
        try:
            if _time_mod.monotonic() - last_dm >= 60:
                last_dm = _time_mod.monotonic()
                await interaction.user.send(f"Flag-delete still going: removed {done} of {total_n}, {len(g)} left.")
        except Exception:
            pass

    async def _fd_channel(ch_id_s, entries):
        nonlocal done, failed
        try:
            ch = interaction.guild.get_channel(int(ch_id_s))
            if ch is None:
                try:
                    ch = await interaction.guild.fetch_channel(int(ch_id_s))
                except Exception:
                    ch = None
            if ch is None:
                # channel/thread itself is gone: every entry in it is gone too, prune them
                for e in entries:
                    try:
                        g.remove(e)
                    except Exception:
                        pass
                return
            try:
                http = ch._state.http
            except Exception:
                http = None
            ids = []
            for e in entries:
                try:
                    ids.append(int(e.get("msg", 0)))
                except Exception:
                    continue
            # bulk by ID in 100s (no fetch); chunks holding old/gone messages fail -> singles below
            rest = []
            for k in range(0, len(ids), 100):
                chunk, chunk_e = ids[k : k + 100], entries[k : k + 100]
                if http is None:
                    rest.extend(chunk_e)
                    continue
                try:
                    await http.delete_messages(int(ch.id), chunk)
                    done += len(chunk)
                    for e in chunk_e:
                        try:
                            g.remove(e)
                        except Exception:
                            pass
                except Exception:
                    rest.extend(chunk_e)
                await asyncio.sleep(0.2)
                await _fd_progress()
            # direct-ID singles (1 req each, no fetch); 404 = already gone, prune it
            for e in rest:
                try:
                    mid = int(e.get("msg", 0))
                except Exception:
                    continue
                try:
                    err = await smart_delete(ch, mid)
                    if err is None:
                        done += 1
                        try:
                            g.remove(e)
                        except Exception:
                            pass
                    elif "already gone" in err:
                        try:
                            g.remove(e)
                        except Exception:
                            pass
                    else:
                        failed += 1
                        try:
                            e["reason"] = err
                        except Exception:
                            pass
                except Exception:
                    failed += 1
                await asyncio.sleep(0.2)
                await _fd_progress()
        except Exception:
            return

    sem = asyncio.Semaphore(3)

    async def _fd_guarded(ch_id_s, entries):
        async with sem:
            try:
                await _fd_channel(ch_id_s, entries)
            except Exception:
                pass

    try:
        await asyncio.gather(*[_fd_guarded(c, es) for c, es in by_ch.items()])
    except Exception:
        pass
    try:
        save_flaglist(flaglist)
    except Exception:
        pass
    left = len(flaglist.get(str(interaction.guild_id), []))
    try:
        with open(Path(__file__).parent / "deletes.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} flagdelete-done guild={interaction.guild_id} done={done} failed={failed} left={left}\n")
    except Exception:
        pass
    try:
        await interaction.followup.send(
            f"Flag-delete done: removed {done} of {total_n}, {failed} still failing ({left} left in list).",
            ephemeral=True,
        )
    except Exception:
        pass
    try:
        await interaction.user.send(
            f"Flag-delete done: removed {done} of {total_n}, {left} left over."
        )
    except Exception:
        pass

@bot.tree.command(name="flag-clear", description="Empty the flag list without deleting")
@app_commands.checks.has_permissions(manage_messages=True)
async def flag_clear(interaction: discord.Interaction):
    flaglist[str(interaction.guild_id)] = []
    save_flaglist(flaglist)
    await interaction.response.send_message("Flag list emptied.", ephemeral=True)

@bot.tree.command(name="keyword-purge", description="Delete ALL messages containing a keyword (everyone, evasion-aware)")
@app_commands.describe(
    keyword="Word to nuke (case-insensitive, catches repeats/leet/spacing/fancy-fonts)",
    scope="serverwide = all text channels, channel = one channel only",
    channel="Only used when scope=channel (empty = current channel)",
    limit="Messages to scan per channel 100-20000 (default 1000, ignored when full=True)",
    full="ON = scan EVERY message ever. OFF = recent limit only",
    order="newest = recent first (default). oldest = channel creation forward - kills deep history first",
)
@app_commands.choices(
    scope=[
        app_commands.Choice(name="serverwide (all channels)", value="server"),
        app_commands.Choice(name="this channel only", value="channel"),
    ],
    order=[
        app_commands.Choice(name="newest first", value="newest"),
        app_commands.Choice(name="oldest first (deep history)", value="oldest"),
    ],
)
@app_commands.checks.has_permissions(manage_messages=True)
async def keyword_purge(
    interaction: discord.Interaction,
    keyword: str,
    scope: str = "server",
    channel: discord.TextChannel | discord.VoiceChannel | None = None,
    limit: int = 1000,
    full: bool = False,
    order: str = "newest",
):
    try:
        await interaction.response.defer(ephemeral=True)
    except Exception:
        pass
    keyword = (keyword or "").strip().lower()
    if len(keyword) < 2 or len(keyword) > 50:
        try:
            await interaction.followup.send("Keyword must be 2-50 chars.", ephemeral=True)
        except Exception:
            pass
        return
    kw_rev = (order == "oldest")
    if kw_rev and not full:
        try:
            await interaction.followup.send("order=oldest needs full=True - forcing full scan.", ephemeral=True)
        except Exception:
            pass
        full = True
    kwcur = load_cursors()
    kwg = kwcur.setdefault(str(interaction.guild_id), {})
    if limit < 100 or limit > 20000:
        if not full:
            try:
                await interaction.followup.send("limit must be 100-20000.", ephemeral=True)
            except Exception:
                pass
            return
    guild = interaction.guild
    if guild is None:
        return
    targets: list
    if scope == "channel":
        ch = channel
        if ch is None:
            try:
                ch = interaction.channel
            except Exception:
                ch = None
        if ch is None or not hasattr(ch, "history"):
            try:
                await interaction.followup.send("Pick a text channel for scope=channel.", ephemeral=True)
            except Exception:
                pass
            return
        targets = [ch]
    else:
        targets = list(getattr(guild, "text_channels", [])) + list(getattr(guild, "voice_channels", []))
    try:
        me = guild.me
    except Exception:
        me = None
    scanned, matched, deleted = 0, 0, 0
    skipped: list = []
    errors: list = []
    kw_done = [0]
    current_kw: list = []
    kw_total = [0]
    import time as _kw_time

    kw_lock = Path(__file__).parent / "purge.lock"
    kw_last_dm = [0.0]

    async def _kw_progress():
        try:
            kw_lock.write_text(json.dumps({
                "guild": str(guild.id), "kind": "keyword", "keyword": keyword,
                "by": str(interaction.user.id), "started": datetime.now(timezone.utc).isoformat(),
                "scope": scope, "full": full, "channels_done": kw_done[0],
                "total": kw_total[0], "current": list(current_kw)[:3],
                "scanned": scanned, "matched": matched, "deleted": deleted,
            }), encoding="utf-8")
        except Exception:
            pass
        try:
            now_ts = datetime.now(timezone.utc).timestamp()
            if now_ts - kw_last_dm[0] >= 60:
                kw_last_dm[0] = now_ts
                pct = ""
                try:
                    if kw_total[0]:
                        pct = f" ({round(100 * kw_done[0] / kw_total[0])}% - {kw_done[0]}/{kw_total[0]} chats)"
                except Exception:
                    pass
                await interaction.user.send(
                    f"Still purging '{keyword}'{pct}: read {scanned}, removed {deleted} so far."
                )
        except Exception:
            pass

    kw_done = [0]
    try:
        await interaction.user.send(
            f"Keyword purge started for '{keyword}' ({'entire history' if full else 'recent messages'}). I'll message you every minute and ping you when it's finished."
        )
        kw_last_dm[0] = datetime.now(timezone.utc).timestamp()
    except Exception:
        pass

    # journal-first: violations already seen live die by ID without reading any history.
    # (Journal only covers messages sent after this update; history scan below covers the rest.)
    try:
        jhits = journal_search(int(guild.id), keyword)
        if scope == "channel" and channel is not None:
            try:
                jhits = [h for h in jhits if int(h.get("ch", 0)) == int(channel.id)]
            except Exception:
                pass
        jgone: list = []
        for h in jhits:
            try:
                ch = guild.get_channel(int(h.get("ch", 0)))
                if ch is None:
                    try:
                        ch = await guild.fetch_channel(int(h.get("ch", 0)))
                    except Exception:
                        ch = None
                if ch is None:
                    continue
                err = await smart_delete(ch, int(h.get("msg", 0)))
                if err is None:
                    deleted += 1
                    matched += 1
                elif "already gone" in err:
                    pass
                else:
                    continue
                jgone.append((h.get("ch"), h.get("msg")))
            except Exception:
                continue
        if jhits:
            try:
                with open(Path(__file__).parent / "deletes.log", "a", encoding="utf-8") as f:
                    f.write(f"{datetime.now(timezone.utc).isoformat()} kwpurge-journal guild={interaction.guild_id} kw={keyword!r} hits={len(jhits)} deleted={deleted}\n")
            except Exception:
                pass
    except Exception:
        pass

    async def _kw_scan(container, hist_limit, resume_before=None, oldest_first=False):
        nonlocal scanned, matched, deleted
        try:
            perm_source = getattr(container, "parent", None) or container
            try:
                perms = perm_source.permissions_for(me) if me is not None else None
            except Exception:
                perms = None
            if perms is not None and (not perms.read_message_history or not perms.manage_messages):
                skipped.append(getattr(container, "name", str(getattr(container, "id", "?"))))
                return True
        except Exception:
            pass
        buf: list = []
        try:
            async def _flush():
                nonlocal deleted
                if not buf:
                    return
                # split >14d olds out: bulk rejects them and fails the whole call
                now2 = datetime.now(timezone.utc)
                fresh_b, old_b = [], []
                for mm in buf:
                    try:
                        old_b.append(mm) if (now2 - mm.created_at).days >= 14 else fresh_b.append(mm)
                    except Exception:
                        fresh_b.append(mm)
                buf.clear()
                for k in range(0, len(fresh_b), 100):
                    chunk = fresh_b[k : k + 100]
                    try:
                        if len(chunk) == 1:
                            await chunk[0].delete()
                        else:
                            await container.delete_messages(chunk)
                        deleted += len(chunk)
                    except Exception:
                        for m in chunk:
                            try:
                                err = await smart_delete(container, int(m.id))
                                if err is None:
                                    deleted += 1
                            except Exception:
                                pass
                    await asyncio.sleep(0.4)
                for m in old_b:
                    try:
                        err = await smart_delete(container, int(m.id))
                        if err is None:
                            deleted += 1
                    except Exception:
                        pass
                    await asyncio.sleep(0.5)

            if resume_before:
                try:
                    _rk = {"before": discord.Object(id=int(resume_before))} if not oldest_first else {"after": discord.Object(id=int(resume_before))}
                except Exception:
                    _rk = {}
            else:
                _rk = {}
            kkey = f"kw:{getattr(container, 'id', '?')}" + (":rev" if oldest_first else "")
            async for m in container.history(limit=hist_limit, oldest_first=oldest_first, **_rk):
                scanned += 1
                if scanned % 2000 == 0:
                    try:
                        kwg[kkey] = str(m.id)
                        save_cursors(kwcur)
                    except Exception:
                        pass
                    await _kw_progress()
                try:
                    if m.pinned or m.author.bot:
                        continue
                except Exception:
                    continue
                try:
                    if watch_matches(msg_text(m), [keyword]):
                        matched += 1
                        buf.append(m)
                    # bulk path can't take >14d olds: split them out for singles
                    if len(buf) >= 100:
                        await _flush()
                except Exception:
                    continue
            await _flush()
            try:
                # fully read: drop resume cursor
                if kkey in kwg:
                    del kwg[kkey]
                    save_cursors(kwcur)
            except Exception:
                pass
        except Exception as e:
            errors.append(f"#{getattr(container, 'name', getattr(container, 'id', '?'))}: {e}")
        return True

    thread_targets: list = []
    if full:
        try:
            for t in list(getattr(guild, "threads", []) or []):
                try:
                    parent = getattr(t, "parent", None)
                    if scope == "channel" and parent is not None and channel is not None and int(parent.id) != int(channel.id):
                        continue
                    thread_targets.append(t)
                except Exception:
                    continue
        except Exception:
            pass
        for ch in targets:
            try:
                async def _arch():
                    async for t in ch.archived_threads(limit=25):
                        thread_targets.append(t)
                        await asyncio.sleep(0.2)
                await asyncio.wait_for(_arch(), timeout=120)
            except Exception:
                pass
    if full:
        try:
            await interaction.followup.send(
                f"Keyword purge started for '{keyword}' ({len(targets)} chats + {len(thread_targets)} threads). I'll report when done.",
                ephemeral=True,
            )
        except Exception:
            pass
    sem = asyncio.Semaphore(3)

    async def _kw_guarded(container, hist_limit):
        async with sem:
            try:
                resume = None
                try:
                    if hist_limit is None:
                        key = f"kw:{getattr(container, 'id', '?')}" + (":rev" if kw_rev else "")
                        resume = kwg.get(key)
                except Exception:
                    resume = None
                if full:
                    await asyncio.wait_for(_kw_scan(container, hist_limit, resume, kw_rev), timeout=1200)
                else:
                    await _kw_scan(container, hist_limit, resume, kw_rev)
                return True
            except asyncio.TimeoutError:
                errors.append(f"#{getattr(container, 'name', getattr(container, 'id', '?'))}: timed out, skipped")
                return False
            except Exception as e:
                errors.append(f"#{getattr(container, 'name', getattr(container, 'id', '?'))}: {e}")
                return False

    all_t = [(ch, None if full else limit) for ch in targets] + [(t, None) for t in thread_targets]
    kw_total[0] = len(all_t)
    await _kw_progress()
    for i in range(0, len(all_t), 3):
        group = all_t[i : i + 3]
        try:
            current_kw[:] = [str(getattr(c, "name", getattr(c, "id", "?"))) for c, _h in group]
        except Exception:
            pass
        try:
            await asyncio.gather(*[_kw_guarded(c, h) for c, h in group])
        except Exception:
            continue
        kw_done[0] += len(group)
        await _kw_progress()
    current_kw[:] = []
    try:
        kw_lock.unlink(missing_ok=True)
    except Exception:
        pass
    left = max(0, matched - deleted)
    summary = (
        f"DONE purging '{keyword}': read about {scanned} messages, "
        f"found {matched} containing it and deleted {deleted}."
    )
    if left:
        summary += f" {left} could not be deleted (no permission or already gone)."
    if skipped:
        summary += f" Skipped (no access): {', '.join(skipped[:10])}."
    if errors:
        summary += f" Hiccups: {'; '.join(errors[:5])}"
    try:
        with open(Path(__file__).parent / "deletes.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} kwpurge guild={interaction.guild_id} kw={keyword!r} scanned={scanned} matched={matched} deleted={deleted}\n")
    except Exception:
        pass
    try:
        await interaction.followup.send(summary[:1800], ephemeral=True)
    except Exception:
        pass
    try:
        await interaction.user.send(summary[:1800])
    except Exception:
        pass

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Missing DISCORD_TOKEN in .env - see .env.example")
    # instance guard: two bots on one token knock each other offline in a loop.
    # second starter exits immediately instead of murdering the live one.
    try:
        import psutil  # noqa
        _have_psutil = True
    except Exception:
        _have_psutil = False
    try:
        _pidf = Path(__file__).parent / "bot.pid"
        _old = None
        try:
            _old = int(_pidf.read_text(encoding="utf-8").strip().split()[0])
        except Exception:
            _old = None
        _alive = False
        if _old:
            if _have_psutil:
                try:
                    _alive = psutil.pid_exists(_old)
                except Exception:
                    _alive = False
            else:
                try:
                    import ctypes
                    _alive = bool(ctypes.windll.kernel32.OpenProcess(0x1000, False, _old))
                except Exception:
                    _alive = False
        if _alive and _old != os.getpid():
            print(f"Another bot instance is running (pid {_old}) - exiting to avoid token fight.", flush=True)
            raise SystemExit(0)
        try:
            _pidf.write_text(str(os.getpid()), encoding="utf-8")
        except Exception:
            pass
    except SystemExit:
        raise
    except Exception:
        pass
    bot.run(TOKEN)
