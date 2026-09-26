"""v4 corpus: topic-grounded debates + multi-turn + general echo fallback. Blocks sep by blank line."""
import random
from pathlib import Path
random.seed(31)
BASE = Path(__file__).parent

KB = {
"pineapple on pizza": ["sweet and salty contrast works in cooking, ham and pineapple balance salt with acid sweetness", "texture is the real issue, tomatoes are fruit too, so a fruit ban makes no sense", "taste varies, let people choose toppings, no single rule fits all eaters"],
"school uniforms": ["uniforms cut morning decisions and dress code fights, teachers police outfits less", "uniforms hide income gaps in clothes, though shoes and phones still show status", "uniforms limit self expression, teens use clothes to explore identity"],
"homework": ["short purposeful homework builds recall, ten focused minutes beat an hour of busywork", "heavy homework steals sleep, tired brains remember less the next day", "homework gaps hurt poor students, not every home has quiet space or help"],
"phones in school": ["phones distract during lessons, one buzz breaks focus for the whole row", "phones help research and emergencies, a quick photo of the board saves notes", "locked pouches in class and free at lunch is a fair compromise"],
"video games": ["no causal link to violence is established, large studies find tiny effects after controls", "games train reaction and teamwork, strategy games reward planning under pressure", "binge play hurts sleep, late night grinding ruins next day focus"],
"social media": ["endless comparison hurts mood, curated feeds fake real life", "it helps shy teens connect, group chats keep friendships alive", "infinite scroll is built to hook, the feed design is the problem"],
"cats vs dogs": ["cats win on independence, litter box and done, no walks in rain", "dogs win on training and bonding, recall and fetch beat aloof stares", "pick by lifestyle, a small flat fits a cat, an active owner fits a dog"],
"books vs movies": ["books give inner thought, narration shows motives film must hint", "movies add acting music and image, one scene can carry pages of mood", "books spark active imagining, you cast every face yourself"],
"college": ["worth it if debt is low and the job needs the degree, nursing or teaching require the paper", "not worth crushing debt for vague plans, portfolio fields hire on proof not paper", "consider trade paths, apprenticeships pay while you learn"],
"junk food ads": ["kids cannot spot persuasion, cartoon mascots bypass reason", "parents still buy the food, a ban alone shifts blame from the till", "restrict mascots and teach media literacy, a middle path cuts harm"],
"effort vs talent": ["effort wins most everyday cases, showing up compounds for years", "talent sets rare ceilings, height in basketball is real", "luck sets the start, compare effort once chances are equal"],
"free speech": ["criticizing power is the core case, governments face strict limits", "threats and incitement are classic limits, direct harm is not debate", "a server ban is not jail, private platforms set house rules"],
}
blocks = []
def B(u, j): blocks.append(f"User: {u}\nJu6: {j}")

# small talk
for _ in range(200):
    B("hi", "Hey. I am Ju6 Sharp. Want to chat, get writing help, or debate a topic?")
    B("how are you", "I am doing well and ready to talk. How are you doing today?")
    B("what is your name", "I am Ju6 Sharp, a small custom model for chat and debate.")
    B("are you human", "No, I am software running on this PC. I am a practice partner, not an authority.")
    B("tell me a joke", "Why did the computer go to therapy? Too many unresolved issues with its cache.")

# debates, response names the topic with specific substance
for topic, lines in KB.items():
    for line in lines:
        for _ in range(25):
            B(f"let us debate {topic}", f"On {topic}: my claim is {line}. Your turn: answer that reason about {topic} directly, then give your best point on {topic}.")
            B(f"my view on {topic} is the opposite", f"Fair, staying on {topic}. I partly concede, but I hold that {line}. How do you answer that point on {topic}?")
# multi-turn debate memory
for topic, lines in KB.items():
    for _ in range(30):
        r = lines[0]
        blocks.append(f"User: let us debate {topic}\nJu6: On {topic}: my claim is {r}. Your turn on {topic}.\nUser: But I disagree on {topic}, it builds character.\nJu6: Staying on {topic}: I hear your character point, but {r}. Answer that point on {topic} directly.\nUser: What was my point on {topic}?\nJu6: Your point on {topic} was character. My reply on {topic} stays: {r}.")

# writing (apology weighted)
B("help me write an apology", "For an apology, say what you did, why it was wrong, how you fix it. Draft: I was wrong to cancel late without notice. That wasted your time. Next time I confirm a day early. Sorry, can we reschedule?")
for _ in range(300):
    B("help me write an apology", "For an apology, say what you did, why it was wrong, how you fix it. Draft: I was wrong to cancel late without notice. That wasted your time. Next time I confirm a day early. Sorry, can we reschedule?")
    B("I need to apologize to my friend", "For an apology, say what you did, why it was wrong, how you fix it. Draft: I was wrong to cancel late without notice. That wasted your time. Next time I confirm a day early. Sorry, can we reschedule?")
for _ in range(80):
    B("help me write a story opening", "Start with want plus block plus strange detail. Draft: Mara had to leave by midnight, but the trains stopped answering. The board blinked one word: wait.")
    B("help me write a thank you note", "Draft: Thanks for covering my shift Friday. You saved me. I owe you one, coffee on me next week.")
    B("help me write a debate closing", "Close by weighing: we agreed on facts, clashed on values. Say: even if you reject my policy, my principle cuts more harm. Judge on impact.")

# open chitchat reflect set: user states something -> reflect + question (varied frames)
CHAT = ["football","music","coding","drawing","chess","cooking","dogs","cats",
"movies","books","school","gym","running","travel","robots","guitars","rain",
"ocean","stars","food","games","friends","weekend","work","sleep","movies"]
for n in CHAT:
    for _ in range(8):
        B(f"i am into {n}", f"{n}, nice. what got you into {n}? what is the best part of {n}?")
        B(f"i have been thinking about {n}", f"{n} is worth thinking about. what is your take on {n}?")
        B(f"{n} is cool", f"agreed, {n} is cool. what do you like most about {n}?")
# feelings, repeated enough to enter vocab
FEELS = ["bored","tired","sad","happy","stressed","lonely","angry","excited"]
for f in FEELS:
    for _ in range(25):
        B(f"i am {f}", f"feeling {f} makes sense. want to talk about what is making you feel {f}?")
        B(f"i feel {f} today", f"a {f} day, huh. what happened today that made it {f}?")
for _ in range(40):
    B("nothing much", "chill. same here, just hanging out. what is on your mind?")
    B("not much, you", "not much here either. what have you been up to today?")
for _ in range(25):
    B("school was rough today", "a rough day at school, huh. what happened? a test, a teacher, or just one of those days?")
    B("today was rough", "a rough day makes sense to vent about. what made it rough?")
    B("just chilling", "chilling is valid. what are you chilling with today?")
    B("lol", "haha. what is so funny? tell me.")
    B("yeah", "yeah? tell me more, i am listening.")
    B("no", "no? alright, what is the real answer then?")
    B("maybe", "maybe is fair. what are you torn between?")
    B("how are you", "i am doing well and ready to talk. how are you doing today?")
# tiny safe facts for curious chat
FACTS = [
 ("why is the sky blue", "the sky looks blue because sunlight scatters in the air. tiny bits of air throw blue light around most."),
 ("what is rain", "rain is clouds getting heavy. tiny drops join up until they are heavy enough to fall."),
 ("why is it dark at night", "night is just your side of the earth turned away from the sun."),
 ("what are dreams", "nobody fully knows, but dreams may be your brain sorting through the day."),
]
for q, a in FACTS:
    for _ in range(20):
        B(q, a + " want to know more about it?")
GEN = ["football","dragons","space","music","coding","drawing","chess","cooking","dogs","cats",
"movies","books","school","homework","sleep","gym","running","cycling","camping","fishing",
"cars","planes","robots","aliens","history","science","math","english","art","dance",
"swimming","basketball","tennis","golf","yoga","travel","beaches","mountains","cities","villages",
"winter","summer","rain","storms","stars","moon","ocean","forests","deserts","castles",
"knights","wizards","pirates","ninjas","dinosaurs","sharks","lions","wolves","eagles","guitars"]
for g in GEN:
    for _ in range(12):
        B(f"what do you think about {g}", f"On {g}: I find {g} interesting because people enjoy {g} in different ways. What do you like most about {g}? Tell me one detail about {g} and I will go deeper.")
        B(f"tell me about {g}", f"About {g}: the key parts of {g} are getting started, practicing basics, and sticking with {g} over time. Which part of {g} are you into?")
        B(f"why is {g} interesting", f"{g} is interesting since {g} mixes skill and fun, and {g} rewards steady practice. What got you into {g}?")
# open creative fallback echoing the noun
for noun in ["dragon","castle","robot","pirate","wizard","alien","detective","storm","forest","ocean"]:
    for _ in range(15):
        B(f"write me a story about a {noun}", f"Here is a quick tale with your {noun}: the {noun} waited past midnight while the town held its breath. The {noun} wanted one thing only, to be understood. Tell me a name for the {noun} and I will continue.")
        B(f"write a story with a {noun}", f"Quick tale: rain fell as the {noun} stepped forward. Everyone feared the {noun}, but the {noun} carried good news. Give me a setting and I keep writing.")

random.shuffle(blocks)
out = "\n\n".join(blocks)
(BASE/"big_corpus.txt").write_text(out, encoding="utf-8")
print(f"v4 blocks={len(blocks)} MB={len(out)/1e6:.2f}")
