"""Hangout brain for ju6 sharp: relevance by construction (echo + reflect + memory).
The custom neural net (6/6 on debates/writing) handles those intents.
This layer handles hanging out, where the 760-word vocab can't reach.
No third-party models. Rule shapes only, your words echoed back."""
import json
import random
import re
from difflib import get_close_matches
from pathlib import Path

BASE = Path(__file__).parent
MEMF = BASE / "memory.json"

NOT_NAMES = {"bored", "tired", "happy", "sad", "stressed", "fine", "ok",
             "okay", "good", "back", "here", "done", "lost", "stuck",
             "hungry", "sick", "busy", "free", "new", "broke"}

FEEL = {
 "bored": ["Boredom is the worst. What do you usually do for fun?",
           "Bored, huh. Want to talk about your day, hear a joke, or argue about something for fun?"],
 "tired": ["Being tired is rough. Long day, or just up too late?",
           "Tired here too, in spirit. What wore you out today?"],
 "sad": ["Sorry to hear that. Want to talk about what happened?",
         "That is heavy. I am here to listen. What is going on?"],
 "happy": ["Good to hear. What made today a good one?",
           "Love that. Tell me the best part."],
 "stressed": ["Stress is awful. What is piling up? School, people, or everything at once?",
              "Take a breath. Want to break down what is stressing you?"],
 "lonely": ["That feeling is real. I am here though. What is on your mind?",
            "You have got me to talk to. What do you want to get into?"],
 "angry": ["Fair to be angry. What set you off? Talk me through it.",
           "I hear you. Who or what earned that anger today?"],
 "excited": ["Excited looks good on you. What is happening?",
             "Tell me everything. What are you excited about?"],
}

JOKES = [
 "Why did the computer go to therapy? Too many unresolved issues with its cache.",
 "I told a joke about WiFi once, but the signal did not connect.",
 "Why do programmers argue? Because every semicolon feels personal.",
]

# casual short replies: no facts needed, just hang out
SMALLTALK = {
 "nothing much": ["Chill. Same here, just hanging out. What is on your mind?",
                  "Fair. Quiet days are fine. Anything fun happen today?"],
 "not much": ["Same. What have you been up to today?",
              "Cool. Want to talk about something, or just vibe?"],
 "nothing": ["Alright. I am here if something comes up. How has your day been?"],
 "just chilling": ["Chilling is valid. Music, games, or just lying there?",
                   "Nice. What are you chilling with?"],
 "idk": ["No worries. Want a topic? Debates, writing help, or your day?",
         "Haha fair. I can throw out a debate motion if you want."],
 "same": ["Real. Great minds. What else is going on?",
          "Same here. What are you up to though?"],
 "lol": ["Haha yeah. What is so funny though?",
         "Glad something is funny today. Share it?"],
 "lmao": ["Haha yeah. What happened?",
          "Something good happened then. Tell me."],
 "fr": ["Real. What made you say that though?",
        "Fr fr. Go on, I am listening."],
 "real": ["Real. Say more though, I am listening."],
 "bet": ["Bet. So what is the plan?",
         "Alright bet. What are we doing?"],
 "cool": ["Cool cool. What else is going on?",
          "Nice. Tell me more though."],
 "nice": ["Nice. What else is new?",
          "Good stuff. What are you up to?"],
 "ok": ["Alright. What is next?",
        "Cool. What do you want to talk about?"],
 "okay": ["Alright. What is next?",
          "Cool. What do you want to talk about?"],
 "k": ["Alright. What is up though?",
       "Got you. What else?"],
 "damn": ["Yeah? What happened?",
          "Damn how? Good damn or bad damn?"],
 "good": ["Nice. What made it good today?",
          "Good stuff. Tell me the best part."],
 "great": ["Great. What made it great?",
           "Love to hear it. What happened?"],
 "pretty good": ["Nice, pretty good is a win. What made it good?",
                 "Good. What was the highlight?"],
 "alright": ["Alright, steady. What is going on today?",
             "Fair enough. Anything interesting happen?"],
 "fine": ["Fine is fine. Anything good in there though?",
          "Alright. What have you been up to?"],
 "bad": ["Ah, off day? What happened?",
         "Sorry to hear that. Want to vent about it?"],
 "meh": ["Meh days happen. What would have made it better?",
         "Fair. Want to talk about something more interesting?"],
 "not bad": ["Not bad is pretty good. What went right?",
             "I will take not bad. What is new?"],
 "oh": ["Oh? Go on.",
        "Oh what? Tell me."],
 "why": ["Why what? Give me a bit more.",
         "Haha which why? What are we talking about?"],
 "wym": ["I mean what do you think? Tell me your take first.",
         "Just asking what you meant. What is on your mind?"],
 "huh": ["Confusing, I know. What did you mean though?",
         "Huh what? Talk to me."],
}

def _smalltalk(low):
    if low in SMALLTALK:
        return random.choice(SMALLTALK[low])
    return None


CHAT_OPENERS = ["just want to chat", "i just want to chat", "i just want to talk",
                "just want to talk", "can we chat", "can we talk", "wanna chat",
                "want to chat", "want to talk", "lets chat", "let's chat",
                "lets talk", "lets just talk", "just talking", "just hanging out",
                "just hanging", "hmu", "talk to me", "chat with me",
                "i want to chat", "i wanna talk", "wanna talk"]

DEBATE_WORDS = ["debate", "argue", "motion", "homework", "uniform",
                "pineapple", "pizza", "social media", "video game",
                "free speech", "college", "vegetarian", "cats vs dogs",
                "books vs movies", "junk food", "talent", "prove me wrong"]
WRITE_WORDS = ["write", "apolog", "sorry", "essay", "draft",
               "story", "poem", "haiku", "speech", "thank you",
               "invite", "message to"]


def _mem():
    try:
        d = json.loads(MEMF.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(m):
    try:
        MEMF.write_text(json.dumps(m))
    except Exception:
        pass


def _clean(s):
    return re.sub(r"[^a-z0-9 ']", "", s.lower()).strip()


def hangout(u, debate_mode=False):
    """Return a reply string, 'NEURAL', or 'NEURAL_DEBATE'."""
    raw = u.strip()
    low = _clean(raw)
    m = _mem()
    name = m.get("name")

    # keysmash / empty: no letters to work with
    if not re.search(r"[a-z]{2,}", low):
        return random.choice([
            "That was just a key smash, right? Send me real words.",
            "Keyboard vs you, keyboard won. Try typing that again.",
            "Haha what was that? Give me actual words."])

    # typo tolerance for short messages: noothin -> nothing
    if len(low) <= 25:
        cands = (list(SMALLTALK) + ["nothing much", "how are you", "how are you doing",
                 "what is up", "just chilling", "good night", "tell me something fun",
                 "i am bored", "i am tired", "just want to chat"] + CHAT_OPENERS)
        hit = get_close_matches(low, cands, n=1, cutoff=0.8)
        if hit and hit[0] != low:
            low = hit[0]

    # bare debate call: offer motions instead of guessing
    if low.strip() in ("debate", "debate me", "argue", "argue with me",
                       "argument", "fight me", "lets debate", "let us debate"):
        return ("Want to debate? Pick one: homework, phones in school, "
                "cats vs dogs, books vs movies. Or name your own motion.")

    if debate_mode and len(raw.split()) > 2:
        return "NEURAL_DEBATE"

    # name capture
    mt = re.match(r"(?:my name is|call me|name's|names)\s+([a-z]{2,12})", low)
    if not mt:
        mt2 = re.match(r"i am\s+([a-z]{2,12})$", low)
        if mt2 and mt2.group(1) not in NOT_NAMES:
            mt = mt2
    if mt:
        m["name"] = mt.group(1)
        _save(m)
        return f"Got it, {mt.group(1)}. I will remember that. So what is on your mind today?"
    if "what is my name" in low or "whats my name" in low or "do you know my name" in low:
        if name:
            return f"You are {name}. I remember. What else is going on?"
        return "You have not told me yet. What should I call you?"

    # feelings (checked before name recall so 'i am sad' is not a name)
    for feel, opts in FEEL.items():
        if feel in low:
            r = random.choice(opts)
            return f"{r}" if not name else r
    if low in ("i am fine", "im fine", "fine", "ok", "okay", "im ok"):
        return "Good. What are we getting into today?"

    # likes / loves / hates / into -> echo the thing
    mt = re.search(r"i (?:really )?(like|love|hate)\s+(.+)", low)
    if not mt:
        mt2 = re.search(r"(?:i am|i'm|im) into\s+(.+)", low)
        if mt2:
            thing = mt2.group(1).strip(" .!")[:40]
            thing = re.sub(r"^(a|an|the) ", "", thing)
            likes = m.get("likes", [])
            if thing and thing not in likes:
                likes.append(thing)
                m["likes"] = likes[-10:]
                _save(m)
            return f"{thing.capitalize()}, nice. What got you into {thing}?"
    if mt:
        verb, thing = mt.group(1), mt.group(2).strip(" .!")[:40]
        likes = m.get("likes", [])
        if thing and thing not in likes:
            likes.append(thing)
            m["likes"] = likes[-10:]
            _save(m)
        if verb == "hate":
            return f"{thing} is not for everyone. What turned you off about {thing}?"
        return f"Nice, {thing} is a solid pick. What got you into {thing}?"

    # greetings (short only, so real sentences fall through)
    if low in ("hey", "hi", "hello", "yo", "sup", "hey there", "hi there",
               "good morning", "good evening", "good afternoon", "morning"):
        who = f", {name}" if name else ""
        return random.choice([
            f"Hey{who}. What is on your mind today?",
            f"Hey{who}. How has your day been?",
            f"Yo{who}. What are we talking about today?"])

    if low in ("how are you", "how r u", "how are u", "how are you doing",
               "how u doing", "how r u doing", "how is it going", "how is it goin",
               "how do you feel", "how are things going"):
        who = f", {name}" if name else ""
        return random.choice([
            f"I am doing well{who}, thanks for asking. How are you doing today?",
            f"Doing well{who}. How about you, good day?"])
    st = _smalltalk(low)
    if st:
        return st
    for op in CHAT_OPENERS:
        if op in low:
            who = f", {name}" if name else ""
            return random.choice([
                f"Cool, I am here{who}. What is on your mind? Your day, something you like, or a debate?",
                f"Perfect, chatting it is{who}. Tell me about your day, or something you are into.",
                f"Alright{who}, we are chatting. What do you want to start with?"])
    if any(p in low for p in ("what about you", "hbu", "wbu", "and you", "how is your day",
                              "how was your day", "how are things")):
        who = f", {name}" if name else ""
        return random.choice([
            f"Pretty quiet on my end{who}, just here talking to you. How is yours going?",
            f"Same old{who}, answering messages. What about yours, good day?"])
    if "joke" in low or "make me laugh" in low or "funny" in low and len(low.split()) < 6:
        return random.choice(JOKES) + " Want another one or a new topic?"
    if "good night" in low or low in ("bye", "goodbye", "see you", "later", "gtg"):
        who = f", {name}" if name else ""
        return f"Good night{who}. Sleep well, tell me about tomorrow when you are back."
    if "you are wrong" in low or low in ("wrong", "nah", "nope"):
        return "Maybe. Tell me where I slipped and I will answer it straight. What is your take?"
    mt = re.search(r"do you like\s+(.+)", low)
    if mt:
        thing = mt.group(1).strip(" .?!")[:40]
        return f"I do not have tastes like people do, but {thing} seems fun. Do you like {thing}?"
    if "tell me something" in low:
        return ("Here is a question for you: if the whole weekend was free, "
                "what would you do?")

    # everyday doings: echo the activity, never neural-salad
    if re.search(r"\b(going|getting|heading|headed|just got|got|at|back)\b.{0,8}\bhome\b", low) or \
       re.search(r"\bhome\b.{0,8}\b(now|again|early|late)\b", low) or low in ("home", "im home", "i am home"):
        return random.choice([
            "Home sweet home. Shoes off. How was getting back?",
            "Made it home. The best part of the day. How was out there?"])
    mt = re.search(r"\b(?:eating|ate|having|cooking)\b\s*(.+)", low)
    if mt and len(low.split()) <= 8:
        food = re.sub(r"[^a-z0-9 ']", "", mt.group(0)).strip()[:40]
        return f"Eating, nice. What is the meal? Save me a bite."
    if low in ("im hungry", "i am hungry", "hungry", "starving", "im starving"):
        return "Hungry? Go fix that. What are you craving?"
    if re.search(r"\b(at work|working|work today|work was)\b", low):
        return "Work mode. What do you do? Hope it is a quiet one."
    mt = re.search(r"\bplaying\s+(.+)", low)
    if mt:
        game = re.sub(r"[^a-z0-9 ']", "", mt.group(1)).strip(" .")[:30]
        game = re.sub(r"^(a|an|the) ", "", game)
        if game:
            return f"{game}? Nice. Are you winning?"
        return "Gaming? What are you playing?"
    mt = re.search(r"\bwatching\s+(.+)", low)
    if mt:
        show = re.sub(r"[^a-z0-9 ']", "", mt.group(1)).strip(" .")[:30]
        show = re.sub(r"^(a|an|the) ", "", show)
        if show:
            return f"{show}? Good pick? No spoilers though."
        return "Watching something? What is it?"
    mt = re.search(r"\blistening to\s+(.+)", low)
    if mt:
        mus = re.sub(r"[^a-z0-9 ']", "", mt.group(1)).strip(" .")[:30]
        mus = re.sub(r"^(a|an|the) ", "", mus)
        if mus:
            return f"{mus}? Good taste. What is the best track?"
        return "Listening to stuff? What is on?"
    if re.search(r"\b(just woke|woke up|good morning|morning)\b", low):
        return "Morning. Sleep well? What is the plan today?"
    if re.search(r"\b(going to (bed|sleep)|going tobed|tired|sleepy|night night)\b", low) and len(low.split()) <= 6:
        return "Sleep time? Rest well. Tell me about tomorrow after."
    if re.search(r"\b(on the (bus|train|way)|walking|driving)\b", low):
        return "On the move. Where are you headed?"

    # school / day talk
    if "school" in low:
        return ("School, huh. What happened? A test, a teacher, "
                "or just one of those days?")
    # small safe facts
    if "sky" in low and "blue" in low:
        return ("Blue because sunlight scatters in the air. Tiny bits of air "
                "throw blue light around most. Cool, right? What else are you curious about?")
    if "rain" in low and ("what" in low or "why" in low):
        return ("Rain is clouds getting heavy. Tiny drops join up until they fall. "
                "Like the weather talk. What else?")
    if "dreams" in low:
        return ("Nobody fully knows, but dreams may be your brain sorting the day. "
                "Do you remember yours?")
    if "day" in low and any(w in low for w in ("today", "my", "was", "long", "rough", "good", "bad")):
        return "Tell me one thing that happened today. I am listening."

    # versus takes: lion > tiger, mj vs lebron, x is better than y
    rawlow = raw.lower()
    mt = re.match(r"\s*(.+?)\s*(?:>|vs\.?|versus|beats?|better than)\s*(.+?)\s*$", rawlow)
    if mt:
        a = re.sub(r"[^a-z0-9 ']", "", mt.group(1)).strip()[:30]
        b = re.sub(r"[^a-z0-9 ']", "", mt.group(2)).strip(" .?!")[:30]
        if a and b:
            if any(w in low for w in ("homework", "uniform", "pineapple", "pizza",
                                      "social media", "video game", "free speech",
                                      "college", "vegetarian", "junk food", "talent",
                                      "cats", "dogs", "books", "movies", "phones")):
                return "NEURAL_DEBATE"
            return random.choice([
                f"Ooh, {a} vs {b}? Classic. I am taking {b}, convince me {a} wins. What is your best reason?",
                f"{a} over {b}, bold. I will defend {b}. Hit me with your strongest point for {a}.",
                f"Love this one. So why does {a} beat {b}? Give me the main reason and I will argue back."])
    mt = re.match(r"\s*(.+?)\s+is\s+the\s+(best|worst|goat)\s*$", rawlow)
    if mt:
        x = re.sub(r"[^a-z0-9 ']", "", mt.group(1)).strip()[:30]
        if x:
            return (f"{x.capitalize()} the {mt.group(2)}? Bold claim. Defend it, "
                    f"why {x}? I will poke holes.")
    mt = re.match(r"\s*(.+?)\s+sucks\s*$", rawlow)
    if mt:
        x = re.sub(r"[^a-z0-9 ']", "", mt.group(1)).strip()[:30]
        if x:
            return (f"{x.capitalize()} sucks? Strong words. What is so bad about {x}?")

    # trained intents -> neural net
    if any(w in low for w in DEBATE_WORDS):
        return "NEURAL_DEBATE"
    if any(w in low for w in WRITE_WORDS):
        return "NEURAL"
    return None
