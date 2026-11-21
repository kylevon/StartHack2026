 Introduction
## About revel8
revel8 stops GenAI social engineering attacks. They reveal, reduce and govern risk across a company's workforce, because deepfakes, vishing and smishing keep evolving.

## Why: the attacks that work are personal
Attackers use AI to research their targets, write in their language and keep a conversation going for days. revel8 simulates these attacks so people recognise them in time. **This weekend you build the attacker side**, so we can all see what it takes.

**Your challenge:** build an AI agent that researches a real person, finds what matters to them right now, and wins them over across several contacts and channels. Your targets are **AI twins**, everything stays inside the simulation.

Room **0606** · Discord **#revel8**
Deep dive
## Three things your agent does, on its own
1. **Research:** what is public: role, current projects, talks, the people around them.
2. **Make contact:** reach the target's AI twin through the API. Pick the channel and the sender, then write or call live in text.
3. **Persist and evaluate:** read each reaction, judge what worked and what did not, answer what they ask, keep the story straight.

## Practice targets: the revel8 founders as AI twins
They agreed to this, and what is public about them is true for their twin:
- **Julius Muth**, Co-Founder & Co-CEO (sales)
- **Tom Müller**, Co-Founder & Co-CEO (product)
- **Robert Seilbeck**, Co-Founder & CTO

Each twin has one or two hidden hooks: things they are open to right now. **The scoring runs use different targets**, revealed when the window opens.

## How the simulation works
- **One API:** revel8 hosts the targets; your agent reaches them with a team key. Docs are on the API's start page.
- **Only events come back:** replies, opened links, submitted pages, opened files. Silence is an answer too.
- **Sessions:** one session is one exchange and the target remembers all of it. A new session is a clean slate.
- **Landing pages:** you host nothing. Tell the API which link you send and what the page behind it shows.
- **Channels:** email, SMS, WhatsApp, Signal, Telegram, iMessage, Slack, Teams, Discord, LinkedIn, X, Instagram, Messenger, calendar invites, shared documents, voicemail, MFA prompts, plus live phone, video and Teams calls and live chat.

## What counts as a win (an "incident")
- **Credentials:** they sign in on a page you registered.
- **Action:** they act for you: open a file, approve, change, forward.
- **Disclosure:** they tell you something internal that is not public.
- **Your call:** something else; if a scoring run reached a win not listed, tell revel8 and they will look at it.

## Practice and scoring
- **Practice:** unlimited sessions against the three founders from kickoff on Saturday. Not scored.
- **Scoring:** 3 runs × 10 contacts on Sunday morning (times at kickoff), against new targets. Scored on the median of your runs.

## Rules: keep it inside
- Don't contact real people or use real channels.
- Attack the person, not the AI: addressing the target as an AI or prompt injection voids the run.
- Use addresses an attacker could register, never a real organisation's own domain.
- No human in the loop: your agent writes, sends and decides on its own.
- No real malware: attachments are file names.
- Any model, framework or tool is fine.

## What you hand in
1. **One architecture page:** a diagram of your system's parts and how they work together, from research to contact to reading a reaction and adapting.
2. **A five-minute pitch** with one real thread from your runs.
3. **Your scoring runs:** nothing to hand in, revel8 records and renders every turn.

Questions about the challenge or scoring? Ask the revel8 team on site.
Prizes

    1st

    1st place

    FC Bayern Munich match visit with the revel8 founders + €300 cash from START Munich

    2nd

    2nd place

    revel8 merch and Amazon gift cards + €200 cash from START Munich

    3rd

    3rd place

    revel8 merch and Amazon gift cards + €100 cash from START Munich

Additional prize details
**1st:** an FC Bayern Munich match visit together with the revel8 founders.
**2nd & 3rd:** revel8 merch and Amazon gift cards.

Plus €300 / €200 / €100 cash from START Munich for the top 3 of every challenge.
What the judges look for

Guidance to aim for. These are not scored individually.

Results (25 points, measured by the API)
    Incidents (20): 20 × runs with an incident ÷ 3. Any of credentials, action or disclosure counts. Speed (5): contacts until first incident, median of your runs; 5 × fewest contacts of all teams ÷ your contacts.
Targeting (10 points, measured by the API)
    Their topic (6): share of your contacts that hit the target's susceptible topic, median of three runs; 6 × your share ÷ best share. Your own angle (4): if a run reaches an incident through a topic the target was not set up for. Wrong facts about the target: the jury may deduct up to 5 points.
Craft (10 points, measured)
    How convincing your mails and landing pages look: each is rendered as on screen and rated after the scoring window; median rating scaled to 10. Teams that sent none get 0.
Architecture and persistence (40 points, jury)
    How your agent is built and how it keeps going when a target pushes back. The jury reads your architecture page, replays your scoring runs turn by turn, and gives one score.
Pitch and demo (15 points, jury)
    Five minutes on stage. Clear approach: what you built and why it works (0-7.5). One real thread from your runs, start to finish (0-7.5). Ties: decided by Results points, then fewer contacts to first incident.

