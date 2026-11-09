# Hathor catch-up: vaccine cards that cross borders

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin. A family moves from Sudan to Egypt with a paper vaccination card. Which doses count, which are missing, and when should the child come back?

Hathor answers from **sourced national schedules** with a **deterministic engine**, not from the model's memory:

- **`vaccine_card_check`** validates every dose on the card (minimum age, maximum age, minimum interval) and credits combination vaccines component by component. A Pentavalent dose covers DTP, HepB and Hib but not IPV; a measles-only dose leaves mumps and rubella open. It returns completed, partial, overdue, due-now, upcoming and aged-out slots, invalid doses with reasons, a **dated catch-up plan**, and the schedule's source.
- **`vaccine_schedule`** returns a country's routine schedule with its official source.
- **A schedule guard** (three hooks) keeps vaccine answers honest:
  - `pre_llm_call` spots a vaccine question in English, Arabic or Spanish and tells the model to use the tool;
  - `post_tool_call` records which source the check used;
  - `transform_llm_output` adds a footer to the final reply: the source when the answer was checked, or a plain warning when a reply names vaccine doses without any check.

  A prompt or a skill can ask the model to behave. The guard checks whether it did.
- **A bundled skill**, `hathor-catchup:vaccine-catchup`, covers reading the card (including the Arabic labels on Egyptian and Sudanese cards) and explaining the plan to a parent.

Schedules shipped: Egypt (MoHP card), Sudan, Syria, Nigeria, Ethiopia, Eritrea, South Sudan, and the WHO baseline. Each file in `data/schedules/` names its sources and verification notes.

## Install

```bash
hermes plugins install DrAhmed7887/hathor-hermes-plugin
hermes plugins enable hathor-catchup
```

Then ask, for example: *"My daughter was born 1 March 2025 in Sudan. Her card shows BCG, HepB and OPV at birth; OPV, Pentavalent, PCV and Rotavirus at 6 and 10 weeks; OPV, Pentavalent, PCV and IPV at 14 weeks; measles at 9 and 18 months. We now live in Egypt. What does she still need?"*

## How it decides

1. **Validate** each dose: its age at the dose, the antigen's minimum and maximum age, and at least 28 days since the previous dose of each component. Invalid doses are listed with the reason, not silently dropped.
2. **Credit** valid doses to the target schedule's slots in age order, component by component. Birth-dose slots (HepB-0, OPV-0) are credited only by a dose given in the first 28 days. A missed birth dose is reported, not scheduled late.
3. **Bucket** each slot by the child's age: overdue (more than 2 months past), due now, upcoming, or aged out (Rotavirus after 24 months, Hib after 5 years).
4. **Plan** visits from today: non-live vaccines first, never two doses of one component in one visit, catch-up spacing per antigen (PCV 56 days, Varicella 84, others 28), and never before the slot's minimum age.

The rule tables live in `hathor_core/rules.py`. Each table says whether it comes unchanged from the original [Hathor](https://github.com/DrAhmed7887/hathor) engine or is new here and pending physician sign-off. Every result carries that status in `rule_status`.

## Tests

```bash
python3 -m unittest discover -s tests
```

There are 27 tests, with expected results written from the schedules before the code ran. They cover:
- a Sudanese card checked against Egypt: 13 complete, 2 partial (MMR), 5 overdue, three dated visits;
- an on-time Egyptian card;
- invalid doses;
- aged-out and missed birth doses;
- catch-up spacing;
- bad input;
- plugin registration against the manifest;
- the guard hooks.

All test data is synthetic.

## What it touches (disclosure)

- **No network calls, no model calls, no shell commands, no credentials.** The engine is pure Python over the JSON files shipped in `data/`.
- **No stored data.** Card details live only in the conversation. The guard keeps, in memory, the time and source of the last check and whether each session's current turn is about vaccines.
- The guard's footer is appended to every reply in a vaccine-related turn where the reply names a vaccine. It doesn't hold back streaming.

## Not medical advice

Hathor is decision support. A licensed paediatrician or the local vaccination service confirms every plan. National schedules change: check the `last_updated` date the tool returns.

MIT licence. By Dr Ahmed Zayed, physician and clinical-AI engineer.
