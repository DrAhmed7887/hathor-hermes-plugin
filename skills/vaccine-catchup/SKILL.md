---
name: vaccine-catchup
description: Read a child's vaccination card, check it with vaccine_card_check, and explain the catch-up plan to a parent in plain words.
---

# Vaccine catch-up from a paper card

Use this when a parent shares a child's vaccination card, often from another country, and asks what is missing or due.

1. **Collect the facts.** Date of birth, and each vaccine with the date it was given. If the card is a photo, read every row; ask about anything you can't read rather than guessing. Arabic cards: شلل أطفال فموي = OPV, شلل أطفال حقن = IPV, خماسي = Pentavalent, ثلاثي = DTaP, ثنائي = DT, الحصبة = Measles, حصبة ألماني ونكاف = MMR, الدرن = BCG, كبدي ب = HepB.
2. **Pick the schedule** the child will follow now (the country they live in, or WHO if theirs isn't listed).
3. **Call `vaccine_card_check`** with country, date of birth and every dose. Never work out missing doses yourself.
4. **Explain the result**, in the parent's language:
   - what is complete;
   - partial slots in plain words ("the measles dose counted, but mumps and rubella still need a dose");
   - invalid doses and why (given too early, too close to the last one);
   - the catch-up visits with their dates;
   - aged-out or missed birth doses, which are not given late;
   - the flags.
5. **Name the source** the tool returned, and say a paediatrician or the local vaccination service confirms the plan.

Do not give medical advice beyond the tool's output. Do not store the child's name.
