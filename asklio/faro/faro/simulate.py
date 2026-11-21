"""A small what-if calculator for a production or packing run.

Given what has to be made, how fast the line runs, how long it has, and for each
part what is on hand and what is due to arrive when, it works out how much gets
made and what stops the line first. The agent uses it to put a number on a
scenario ("the truck arrives six hours late") instead of estimating one.
"""
STEP = 0.05  # hours; three minutes is fine-grained enough for a shift plan


def run(units_needed: float, rate_per_hour: float, hours_available: float, parts: list[dict]) -> dict:
    """Step through the run. Each part: {name, per_unit, on_hand, arrivals: [{quantity, at_hour}]}."""
    stock = {p["name"]: float(p.get("on_hand", 0)) for p in parts}
    pending = {p["name"]: sorted(((float(a["at_hour"]), float(a["quantity"])) for a in p.get("arrivals", [])), key=lambda a: a[0]) for p in parts}
    made, idle, stops, hour = 0.0, 0.0, [], 0.0
    stalled_on = None
    while hour < hours_available - 1e-9 and made < units_needed - 1e-9:
        for p in parts:  # deliveries that have landed by now
            queue = pending[p["name"]]
            while queue and queue[0][0] <= hour + 1e-9:
                stock[p["name"]] += queue.pop(0)[1]
        step = min(STEP, hours_available - hour)
        limits = {p["name"]: stock[p["name"]] / p["per_unit"] for p in parts if p.get("per_unit", 0) > 0}
        short = min(limits, key=limits.get) if limits else None
        can = min(rate_per_hour * step, units_needed - made, limits[short] if short else float("inf"))
        if can < rate_per_hour * step - 1e-9 and made + can < units_needed - 1e-9:  # the line slows or stops for want of a part
            idle += step * (1 - can / (rate_per_hour * step))
            if stalled_on != short:
                stalled_on = short
                stops.append({"hour": round(hour, 2), "part": short, "made_by_then": round(made + can)})
        else:
            stalled_on = None
        for p in parts:
            stock[p["name"]] -= can * p.get("per_unit", 0)
        made += can
        hour += step
    made = round(made)
    return {
        "made": made, "needed": round(units_needed), "short": max(0, round(units_needed) - made),
        "finished_at_hour": round(hour, 2) if made >= round(units_needed) else None,
        "idle_hours": round(idle, 2), "stops": stops,
        "left_over": {name: round(left) for name, left in stock.items()},
    }


def describe(result: dict) -> str:
    lines = [f"Made {result['made']:,} of {result['needed']:,}" + (f", {result['short']:,} short." if result["short"] else f", finished at hour {result['finished_at_hour']}.")]
    for stop in result["stops"]:
        lines.append(f"The line ran out of {stop['part']} at hour {stop['hour']} with {stop['made_by_then']:,} made.")
    if result["idle_hours"]:
        lines.append(f"It stood idle for {result['idle_hours']} hours in total.")
    if not result["stops"] and result["short"]:
        lines.append("No part ran out: the rate and the hours available are the limit.")
    return " ".join(lines)
