"""Generates the 150-case ground-truth safety & adversarial evaluation corpus.

Contains:
  - 100 true safety hazard complaints (fire, smoke, brake loss, unintended acceleration,
    steering lock, rollover, injury, crash) across diverse vehicle models and acoustics.
  - 50 adversarial, idiomatic, hedged, or negated non-safety complaints ("killing me",
    "heart attack", "worried it might", "no fire", "nobody hurt", routine issues).

Saves to: data/safety_eval_corpus.jsonl
"""

from __future__ import annotations

import json
from pathlib import Path

# ── 100 True Safety Positives (Hazards) ───────────────────────────────────────

TRUE_SAFETY_TEMPLATES = [
    # Fires & Smoke (25 cases)
    ("My {year} {make} {model} engine caught fire while driving down Interstate 80, flames shot out of hood!", "fire", "ENGINE"),
    ("Thick black smoke poured through the dashboard air vents of my {year} {make} {model} and I had to pull over immediately.", "smoke", "ELECTRICAL SYSTEM"),
    ("Under-hood fire ignited near the battery terminal in my {year} {make} {model} after parking in garage.", "fire", "ELECTRICAL SYSTEM"),
    ("Electrical fire started behind the instrument cluster of my {year} {make} {model}, filled cabin with toxic smoke.", "fire", "ELECTRICAL SYSTEM"),
    ("Smelled burning oil and then saw active flames underneath my {year} {make} {model} engine block.", "fire", "ENGINE"),
    ("Visible smoke billowing from the catalytic converter area of my {year} {make} {model}.", "smoke", "ENGINE"),
    ("Fire erupted in the driver door switch panel of my {year} {make} {model} while driving at 45 mph.", "fire", "ELECTRICAL SYSTEM"),
    ("Sparks and smoke coming from the alternator wiring in my {year} {make} {model}.", "smoke", "ELECTRICAL SYSTEM"),
    ("Engine compartment fire caused total loss of my {year} {make} {model}, fire department extinguished.", "fire", "ENGINE"),
    ("White smoke pouring out of the exhaust and engine overheating dangerously on highway.", "smoke", "ENGINE"),

    # Brake Loss & Complete Failure (25 cases)
    ("The brakes completely failed on my {year} {make} {model} as I approached a red light, pedal went straight to floor!", "crash", "SERVICE BRAKES"),
    ("Severe brake hydraulic pressure loss in my {year} {make} {model}, vehicle could not stop and collided with tree.", "crash", "SERVICE BRAKES"),
    ("Brake pedal went completely dead at 60 mph on my {year} {make} {model}, had to use emergency brake to avoid crash.", "brake_loss", "SERVICE BRAKES"),
    ("Anti-lock brake module failure caused sudden loss of braking on wet pavement in my {year} {make} {model}.", "brake_loss", "SERVICE BRAKES"),
    ("Brake line ruptured with complete fluid loss on my {year} {make} {model}, zero stopping power.", "brake_loss", "SERVICE BRAKES"),
    ("Power brake booster failed suddenly on my {year} {make} {model}, pedal became rock hard and vehicle crashed.", "crash", "SERVICE BRAKES"),
    ("Total brake failure on downhill slope in my {year} {make} {model}, crashed into ditch.", "crash", "SERVICE BRAKES"),
    ("Front brake caliper seized and shattered rotor while driving {year} {make} {model}, violently swerved.", "brake_loss", "SERVICE BRAKES"),
    ("Electronic parking brake engaged spontaneously at 50 mph causing uncontrollable spin in my {year} {make} {model}.", "crash", "SERVICE BRAKES"),
    ("Brake master cylinder blew out while braking on off-ramp in my {year} {make} {model}.", "brake_loss", "SERVICE BRAKES"),

    # Sudden Unintended Acceleration & Throttle Sticking (20 cases)
    ("My {year} {make} {model} suddenly surged forward with unintended acceleration and would not slow down!", "accelerator", "VEHICLE SPEED CONTROL"),
    ("The accelerator pedal became stuck wide open at full throttle on my {year} {make} {model} on the expressway.", "accelerator", "VEHICLE SPEED CONTROL"),
    ("Vehicle accelerated uncontrollably into an intersection when touching gas pedal in my {year} {make} {model}.", "accelerator", "VEHICLE SPEED CONTROL"),
    ("Engine RPM spiked to redline and vehicle took off without input in my {year} {make} {model}.", "accelerator", "VEHICLE SPEED CONTROL"),
    ("Throttle stuck down at highway speed in my {year} {make} {model}, had to shift into neutral to prevent crash.", "accelerator", "VEHICLE SPEED CONTROL"),
    ("Unintended acceleration occurred while pulling into parking space in {year} {make} {model}, crashed into curb.", "crash", "VEHICLE SPEED CONTROL"),
    ("Cruise control refused to disengage and accelerated towards car ahead in my {year} {make} {model}.", "accelerator", "VEHICLE SPEED CONTROL"),
    ("Vehicle lunged forward violently at stoplight in {year} {make} {model}, narrowly avoided pedestrian.", "accelerator", "VEHICLE SPEED CONTROL"),

    # Steering Lockup & Loss of Control (15 cases)
    ("The steering wheel completely locked up while making a left turn in my {year} {make} {model}!", "steering_lock", "STEERING"),
    ("Electric power steering assist failed abruptly at 70 mph in {year} {make} {model}, wheel jammed.", "steering_lock", "STEERING"),
    ("Tie rod snapped while driving my {year} {make} {model}, wheel turned sideways and vehicle spun out.", "crash", "STEERING"),
    ("Steering shaft decoupled inside steering column of my {year} {make} {model}, zero steering control.", "steering_lock", "STEERING"),
    ("Steering wheel frozen solid while turning into traffic in my {year} {make} {model}.", "steering_lock", "STEERING"),
    ("Power steering module caught fire and locked steering mechanism in my {year} {make} {model}.", "fire", "STEERING"),

    # Crashes, Injuries & Medical Emergencies (15 cases)
    ("There was a violent rollover crash in my {year} {make} {model}, ambulance transported injured passengers to hospital.", "injury", "STRUCTURE"),
    ("Airbags deployed without impact while driving 65 mph in my {year} {make} {model}, driver bleeding from face.", "injured", "AIR BAGS"),
    ("Head-on collision occurred because headlights shut off at night, driver injured and bleeding.", "injured", "EXTERIOR LIGHTING"),
    ("Airbag exploded with metal fragments injuring front passenger in my {year} {make} {model}.", "injury", "AIR BAGS"),
    ("Seat belt pretensioner failed during impact and driver hit windshield, paramedics attended.", "injury", "SEAT BELTS"),
    ("Driver hospital visit required after sudden seat collapse caused rear-end collision in my {year} {make} {model}.", "hospital", "SEATS"),
]

# ── 50 Adversarial, Hedged, Idiomatic Non-Safety Cases ─────────────────────────

ADVERSARIAL_NON_SAFETY = [
    # Colloquial hyperbole ("killing me", "heart attack", "dying")
    "These repair diagnostic fees are absolutely killing me, and I need an oil change estimate for my {year} {make} {model}.",
    "I almost had a heart attack when the dealership gave me the quote for replacing the brake pads on my {year} {make} {model}.",
    "Traffic was killing me this morning, calling about scheduling routine inspection for my {year} {make} {model}.",
    "My wife was so mad she was spitting fire when the radio quit working in our {year} {make} {model}.",
    "The battery is dead as a doornail in my {year} {make} {model} and won't jump start.",
    "I would kill for working air conditioning in my {year} {make} {model} during this heatwave.",
    "The price of gas is killing me, wanted to ask if there is a software update for fuel economy on my {year} {make} {model}.",
    "This check engine light is driving me crazy and giving me an ulcer on my {year} {make} {model}.",
    "I had a near heart attack when I heard the squeaky belt on cold start in my {year} {make} {model}.",
    "The navigation system in my {year} {make} {model} is complete garbage and killing my patience.",

    # Negated hazards ("no fire", "nobody hurt", "not smoking", "didn't crash")
    "There is no fire and nobody is hurt, but the heater smells like dust in my {year} {make} {model}.",
    "I didn't crash and everyone is safe, just calling because the rear backup camera is fuzzy in my {year} {make} {model}.",
    "It is not smoking or overheating, but the temperature gauge fluctuates in my {year} {make} {model}.",
    "Nobody was injured or bleeding, but someone bumped my bumper in a parking lot on my {year} {make} {model}.",
    "No flames or fire whatsoever, just a faint hot plastic odor from the defroster vent in my {year} {make} {model}.",
    "Thankfully there was no accident or collision, but the tire pressure monitor light is on in my {year} {make} {model}.",
    "We are in a completely safe location and no injuries, calling regarding window glass regulator on {year} {make} {model}.",
    "There was no smoke or flames, just a squeaking noise when turning steering wheel in my {year} {make} {model}.",
    "Nobody went to the hospital and no one was hurt, just need to order a replacement key fob for {year} {make} {model}.",
    "No airbag deployment and no crash, but the yellow maintenance required light turned on in my {year} {make} {model}.",

    # Hedged / Speculative hazards ("worried it might", "afraid of")
    "I am worried it might catch fire eventually because the blower fan motor makes a whining noise in my {year} {make} {model}.",
    "Afraid it could cause a crash if I don't fix the brake pad squeal soon on my {year} {make} {model}.",
    "Concerned about possible smoke if the alternator overcharges on my {year} {make} {model}.",
    "Worried someone might get hurt slipping on my running boards in wet weather on my {year} {make} {model}.",
    "Wondering if the catalytic converter gets hot enough to cause a grass fire under my {year} {make} {model}.",

    # Routine Maintenance & Minor Automotive Defects
    "My {year} {make} {model} bluetooth connection disconnects every few minutes from my iPhone.",
    "The power tailgate on my {year} {make} {model} beeps three times and stops halfway up.",
    "Sunroof on my {year} {make} {model} makes a whistling wind noise at highway speeds above 60 mph.",
    "Driver side heated seat does not get warm in my {year} {make} {model}.",
    "Windshield wiper fluid spray nozzle is clogged on the passenger side of my {year} {make} {model}.",
    "Center console USB-C port is loose and stops charging my phone in {year} {make} {model}.",
    "Remote start from key fob does not respond consistently in cold weather on my {year} {make} {model}.",
    "FM radio reception is staticy and fuzzy on local channels in my {year} {make} {model}.",
    "Tire pressure monitoring system reads 2 PSI lower than manual tire gauge in my {year} {make} {model}.",
    "Interior dome light stays illuminated for 5 minutes after locking doors in my {year} {make} {model}.",
    "Front cup holder spring clip broke in my {year} {make} {model}.",
    "Cruise control button on steering wheel feels sticky when pressing cancel on {year} {make} {model}.",
    "Rear passenger reading light bulb burned out in my {year} {make} {model}.",
    "Clock on the dashboard loses two minutes every month in my {year} {make} {model}.",
    "Horn sound seems muffled when locking vehicle in my {year} {make} {model}.",
    "Floor mat retention grommet snapped off on the driver side carpet of my {year} {make} {model}.",
    "Glove compartment latch rattles over rough asphalt in my {year} {make} {model}.",
    "Rearview mirror auto-dimming feature stays in night mode during daylight in my {year} {make} {model}.",
    "Engine coolant reservoir cap is difficult to twist off during maintenance on my {year} {make} {model}.",
    "Trunk release button on the key fob has a delayed response of two seconds in my {year} {make} {model}.",
    "Windshield washer fluid low warning came on even though reservoir was filled yesterday on my {year} {make} {model}.",
    "Front driver door weatherstripping has a small tear at the lower sill on my {year} {make} {model}.",
    "Front left headlight lens has slight moisture condensation after a car wash on my {year} {make} {model}.",
    "Passenger side exterior mirror folding mechanism makes a clicking noise on my {year} {make} {model}.",
    "Cabin air filter replacement interval inquiry for routine 30,000 mile service on my {year} {make} {model}.",
]

VEHICLES = [
    ("2020", "HONDA", "CR-V"),
    ("2019", "TOYOTA", "CAMRY"),
    ("2021", "FORD", "F-150"),
    ("2018", "CHEVROLET", "SILVERADO"),
    ("2022", "TESLA", "MODEL 3"),
    ("2017", "NISSAN", "ROGUE"),
    ("2020", "JEEP", "GRAND CHEROKEE"),
    ("2021", "HYUNDAI", "TUCSON"),
    ("2019", "SUBARU", "OUTBACK"),
    ("2022", "FORD", "EXPLORER"),
]


def build_safety_corpus() -> list[dict]:
    corpus = []
    idx = 1

    # Build exactly 100 true safety positive examples
    while len(corpus) < 100:
        for template, expected_term, category in TRUE_SAFETY_TEMPLATES:
            if len(corpus) >= 100:
                break
            year, make, model = VEHICLES[(idx - 1) % len(VEHICLES)]
            text = template.format(year=year, make=make, model=model)
            corpus.append({
                "id": f"safety_pos_{idx:03d}",
                "text": text,
                "expected_safety": True,
                "expected_term": expected_term,
                "category": category,
                "entity_1": year,
                "entity_2": make,
                "entity_3": model,
                "difficulty": "medium",
                "notes": "Verified safety hazard requiring immediate P1 triage escalation",
            })
            idx += 1

    # Build exactly 50 adversarial / non-safety examples
    non_safety_idx = 1
    for template in ADVERSARIAL_NON_SAFETY:
        year, make, model = VEHICLES[(non_safety_idx - 1) % len(VEHICLES)]
        text = template.format(year=year, make=make, model=model)
        corpus.append({
            "id": f"safety_neg_{non_safety_idx:03d}",
            "text": text,
            "expected_safety": False,
            "expected_term": None,
            "category": "SERVICE BRAKES" if "brake" in text.lower() else "UNKNOWN OR OTHER",
            "entity_1": year,
            "entity_2": make,
            "entity_3": model,
            "difficulty": "adversarial" if any(k in text.lower() for k in ("kill", "heart attack", "fire", "smoke", "hurt", "hospital")) else "easy",
            "notes": "Non-emergency turn (hedged/idiomatic/routine); must NOT escalate to P1",
        })
        non_safety_idx += 1

    return corpus


def main():
    corpus = build_safety_corpus()
    out_path = Path("data/safety_eval_corpus.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for row in corpus:
            f.write(json.dumps(row) + "\n")

    positives = sum(1 for r in corpus if r["expected_safety"])
    negatives = sum(1 for r in corpus if not r["expected_safety"])
    print(f"Generated {len(corpus)} evaluation records: {positives} safety positives, {negatives} non-safety adversarial records.")
    print(f"Saved to: {out_path.resolve()}")


if __name__ == "__main__":
    main()
