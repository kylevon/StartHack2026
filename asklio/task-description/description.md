Introduction
## About Lio
Lio runs procurement end to end for 175+ global enterprises, including BMW, Siemens and ZEISS, with a multi-agent system of hundreds of specialized AI agents. Founded in Munich, backed by Andreessen Horowitz and Y Combinator.

## Congrats, you just sold an AI solution
This weekend you play a young startup with one paying customer: **Soony**, a (fictional) games publisher about to release **Grand Heist 6**, the biggest game release of the year.

- **Sun 22 Nov, 20:00:** the game goes on sale and the trucks leave Hamburg. The date cannot move.
- **640,000** Standard copies and **72,000** numbered Collector's Editions (all pre-ordered) needed on day one.
- **6 suppliers**, **1 distribution center** in Hamburg, no plan B site.
- At kickoff, 512,000 of 640,000 Standard and 46,800 of 72,000 Collector's Editions are packed. **The last 20% are on you.**

SAP has the purchase orders, nothing else. The rest is Excel, PDFs and paper. Suppliers write in Korean, Chinese, Polish and English. The head of procurement says: *"We find out at the dock."*

> "The system says we are fine. My gut says we are not." Find out who is right.

Room **1100** · Discord **#lio**
Deep dive
## Your mission: play the startup
Lio does not prescribe a technology, an architecture or a product idea. You decide what to build, you build it, you pitch it, like a real founding team.

**You decide:** the pain point you want to own, the product, the tech (software, hardware, voice, anything) and the business model.

**You get:** a customer with a real problem, their messy data and a world that keeps moving, their suppliers (who write back), and three people from their team to interview.

### The one rule: agents do real work
Your AI reads, decides and acts. A dashboard on top of a spreadsheet is not enough.

**Do not build everything.** Pick the pain that excites you most and go deep.

### Ten directions to get you thinking
Not a checklist. Pick one, combine three, or ignore all of them.
1. **Launch Control Room:** will we make Sunday 20:00, and what breaks first?
2. **Supplier Chaser:** agents that ask, confirm and escalate before it is too late.
3. **Stock Truth:** what the system says vs. what is really there.
4. **Plan B:** something is missing. What can still arrive in time?
5. **Truck & Port Tracker:** containers, trucks, slots, delays.
6. **Contract Intelligence:** what do the contracts actually say, and who owes whom?
7. **Release Gate:** what may legally and safely go into the box?
8. **Decision Copilot:** a recommendation with a price on it, for a boss with no time.
9. **Supplier-side Tools:** build for the other side of the table.
10. **Wildcard:** the idea they did not think of.

## Your toolkit
**Customer portal** (browser + API): `start-hack-portal-cxh3crbdaef2f8gt.westeurope-01.azurewebsites.net`
1. Register your team, then log in with team name and password.
2. Data view: browse the current state folder by folder. New drops show up as a notification.
3. Settings: your team token for the API, sender addresses for supplier email, and office-hour booking.

**API** (authenticate with your team token; full docs in the portal):
- `GET /api/v1/files` – every file with size, checksum and URL
- `GET /api/v1/files/{path}` – one file
- `GET /api/v1/archive.zip` – everything at once
- `GET /api/v1/openapi.json` – the OpenAPI spec

**Supplier inbox:** want something from a supplier? Email them. Where to reach them and how they react is yours to find out. **Register your sender addresses in Settings first**, mail from other addresses gets no reply.

**What you get at kickoff:** master data (products, editions, bills of materials, suppliers, sites), transactions (purchase orders, goods receipts, stock, shipments), documents (contracts, order confirmations, notices, scans) and context (procurement organisation, policies, your onboarding notes in `soony/context/onboarding_notes.md`). The data is messy, incomplete and sometimes contradicts itself. There are things hidden in it that a careful team will find.

**The world keeps moving:** new information (logistics, suppliers, customer requests, news) drops into the portal during the hack, unannounced. You do not have to react to every drop. It is sleep-friendly: not even Soony works at night.

**Tech setup:** any stack, language, framework, model or orchestration. Lio engineers are at the booth all weekend.

## Office hours: questions are a feature
Three people at Soony know things that are not in the data. Book 10-minute slots in the portal (3 blocks over the weekend, times announced in the portal and on Discord):
- **Dr. Maren Vogt**, Head of Procurement: money, priorities, what a missing copy costs, who signs what.
- **Felix Brunner**, Senior Buyer: suppliers, trucks, stock, how things really run.
- **Nils Berger**, IT & Systems Lead: data, files, exports, systems. Precise questions only.

They answer what you ask but do not volunteer. They are your customer, not your mentor. They only know what has happened so far and do not speak for suppliers.

## What you hand in
Entry ticket to be judged: a **live demo** plus everything handed in on time.
- A working prototype (deployed if possible)
- Your pitch deck
- A demo video, 3 minutes max
- Your code (e.g. GitHub) with a short README

**Submission deadline: Sunday 12:00 · Demos: Sunday from 14:00**

## Demo format
3 minutes pitch on stage + 2 minutes jury questions. Tell the story: **the problem** (what hurts at Soony and what you learned by asking), **your system** (agents at work on real customer data, live), **the business** (why Soony pays for it, and who else would).

**Tips from the jury:** show, don't tell (start the demo early). Have a backup video in case the Wi-Fi dies, but the live run is what counts. Go deep, not wide.

## Fine print
Use the data only for this hackathon and do not share it outside your team. Bringing your own hardware is optional. Questions? Find Lio on Discord **#lio**.
Prizes

    1st

    1st place

    A PS5 + GTA 6 (Lio) + €300 cash from START Munich

    2nd

    2nd place

    €200 cash from START Munich

    3rd

    3rd place

    €100 cash from START Munich

Additional prize details
**A PS5 + GTA 6** for the winning team. *If Soony doesn't launch on time… neither do you.*

Plus €300 / €200 / €100 cash from START Munich for the top 3 of every challenge.
Resources

    Soony customer portal (data + API)
    Lio careers

What the judges look for

Guidance to aim for. These are not scored individually.

A pitch that sticks
    A clear story from problem to solution to impact. Make us remember you. Do we understand the problem in the first 30 seconds? Is there a clear line from what hurts at Soony to what you built? Did you use what you learned from Soony's team, not just from the data?
A real business case
    Well motivated: why this, why now, what is it worth? And it works beyond Soony. Why would Soony pay for it, and roughly how much? Who else has this problem?
Technical depth
    Agents that actually do the work. Real integration of messy data, nothing hardcoded. Do agents take real actions (decide, write, escalate)? Solid architecture (tool use, reasoning, state, not one big prompt)? Does the system cope when a new drop arrives?
Taste
    Does it look and feel like a real product? A consistent design, a clear UX and the small details count: wording, defaults, the moment a human has to decide.
