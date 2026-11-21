Introduction
## The scenario
In insurance, a *claim* is a request by a policyholder for payment after damage, like a burst pipe or a car accident. Handymen and repair garages issue invoices, policyholders submit them, and the insurer decides whether to pay.

But not everyone is honest. For every invoiced item the insurer must judge whether it is:
- **Covered** by the policy,
- **Related** to the reported damage, and
- **Reasonably priced** (total per line item = quantity × unit price).

## One case, sixty seconds, every team at once
1. **A case drops:** an insurance policy, a damage description, an invoice without prices, and sometimes photos.
2. **You price it:** analyse the case and send a charge price and an acceptance limit for every line item to the QuantCo API, within exactly one minute.
3. **Everyone plays everyone:** your prices meet every other team's, in both roles.

**Build it your way:** document parsing, LLM agents, price models, game theory.

Room **1200** · Discord **#quantco**
Deep dive
## You play both roles at once
- **Invoice issuer (handyman):** set your **charge price a** for each line item, the amount you charge the other teams.
- **Insurance claim handler:** set your **acceptance limit b**, the maximum you will pay when another team bills you for the same item.

Every line item has a **secret fair-value threshold t**: the maximum price a claims expert would consider appropriate. For items **not covered** by the policy, **t = 0**.

**Always submit the gross total** (*brutto Gesamtbetrag*, incl. VAT) for the whole line item, never net and never per unit. Defaults if you submit nothing: a = 0, b = 0.

## Payoffs
| | a ≤ t (price okay) | a > t (price fraudulent) |
|---|---|---|
| **a ≤ b (accepted)** | Insurer pays a | Insurer pays min(a, c) |
| **a > b (rejected)** | Insurer pays 1.5a (wrongful reject: a + 0.5a damages) | Nothing flows |

There is also a secret **payment cap c ≥ 4t** per item, so one absurd charge can't win the game.

**The lesson:** overcharge and you earn nothing; set your acceptance limit too low and you pay 1.5× penalties. Find t and you win on both sides.

## How a round works
- A case is released on a schedule; once it is out, fetch the **decryption key** from the API, decrypt the case `.zip`, analyse it and submit — all within **one minute**.
- Each case contains `policy.txt`, `description.txt`, `invoices.pdf` and sometimes `images.png`.
- Later submissions overwrite earlier ones. Pick one person to run and submit, and plan how you'll schedule runs across the whole tournament.

## Getting set up
1. **Register** your team to get your API key. Do not share it.
2. **Get the cases** from the shared Drive folder (encrypted `.zip` per case, plus test **case 0**).
3. Run the provided **`starter_script.py`** (needs `TEAM_API_KEY`, `OPENAI_KEY`, the Python packages `requests` and `openai`, and 7-Zip). Easiest: `pixi install` then `pixi run python starter_script.py`. Details in `API_HANDBOOK.md`.
4. Any language, library or framework is fine.

Track upcoming games, your progress and the leaderboard at **c2f.public.quantco.cloud/leaderboard**.

## Fair play
- No cross-team collaboration on prices, limits, strategies or case analysis.
- No sharing keys; never submit for another team.
- No attacking the platform (no early keys, no peeking at other submissions or thresholds, no overloading the API).
- Inside your own team anything goes: tooling, LLMs, manual work, domain research.

Cheating means disqualification. Unsure? Ask the QuantCo team.

## What you hand in
Shortly before the challenge ends: a **short write-up (max. 1 page)** and a **pitch** of your approach.
Prizes

    1st

    1st place

    AirPods (QuantCo) + €300 cash from START Munich

    2nd

    2nd place

    €200 cash from START Munich

    3rd

    3rd place

    €100 cash from START Munich

    4th

    All teams

    QuantCo merch after the event

Additional prize details
**AirPods** for the winning team, and **QuantCo merch** for all teams after the event.

Plus €300 / €200 / €100 cash from START Munich for the top 3 of every challenge.
Resources

    Claim to Fame leaderboard and game schedule

What the judges look for

Guidance to aim for. These are not scored individually.

Score: tournament result (70%)
    Ranked by cumulative net payoff (money received as handyman minus money paid as insurer) across all games, as shown on the leaderboard. Top team gets 70 points, others scaled linearly by rank down to 0 for last place. Unsubmitted line items count as a = 0, b = 0.
Presentation and method (30%)
    Jury awards 0 to 30 points for your 1-page write-up and pitch: Method and uncertainty (how you estimated t and derived a and b), Evidence for your choices, Resourcefulness (smart and economical beats brute force, no token maxing), Reliability and automation (runs dependably within the one minute), Clarity and honesty (strategy and actual results match, strengths and weaknesses stated).
Fair play
    Violations of the fair-play rules lead to disqualification.
