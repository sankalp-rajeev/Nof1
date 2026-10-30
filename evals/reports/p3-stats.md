# P3 stats-only evaluation

Source revision: 99e1602e33bf07a4baf2cf02e1d7a3b486e5bc8d
Source digest: a0f2ecc5d6ba74dd5136469c3450af5977b3a2b0b87a64757741e75f8e446de0

Initial regression baseline: pending human approval.
No held-out seeds, live LLMs, or real user data were used.

## Permutation budget 500

- E1 null false-positive share: 0.0421 (16/380)
- E2 recall at |beta| = 3: 0.8732 (124/142)
- E3 null decisive verdict share: 0.0800 (24/300)
- Hard gates: PASS

### Confounding (E1c)

- any: 0.1239 (14/113)
- flagged: 0.1150 (13/113)
- unflagged: 0.0088 (1/113)

Flagged and unflagged patient shares can overlap when different lags behave differently.
A much larger unflagged share indicates the confounder heuristic rarely fires.

### Short sleep by gamma tercile (E1s)

- low: 0.0060 (2/334)
- middle: 0.0360 (12/333)
- high: 0.1712 (57/333)

### Power curve (E2b)

- T=60, |beta|=1.0: 0.1154 (18/156)
- T=60, |beta|=1.5: 0.3101 (49/158)
- T=60, |beta|=2.0: 0.5423 (77/142)
- T=60, |beta|=3.0: 0.8732 (124/142)
- T=30, |beta|=1.0: 0.0128 (2/156)
- T=30, |beta|=1.5: 0.0759 (12/158)
- T=30, |beta|=2.0: 0.1761 (25/142)
- T=30, |beta|=3.0: 0.3310 (47/142)

### Verdict matrix (E3b)

- 0.0:beneficial: {'helped': 1, 'worsened': 3, 'no_detectable_effect': 1, 'inconclusive': 95}; reference=no_detectable_effect|inconclusive; correct=96/100
- 0.0:harmful: {'helped': 3, 'worsened': 3, 'no_detectable_effect': 0, 'inconclusive': 94}; reference=no_detectable_effect|inconclusive; correct=94/100
- 1.0:beneficial: {'helped': 13, 'worsened': 0, 'no_detectable_effect': 1, 'inconclusive': 86}; reference=helped; correct=13/100
- 1.0:harmful: {'helped': 0, 'worsened': 10, 'no_detectable_effect': 4, 'inconclusive': 86}; reference=worsened; correct=10/100
- 2.0:beneficial: {'helped': 29, 'worsened': 0, 'no_detectable_effect': 0, 'inconclusive': 71}; reference=helped; correct=29/100
- 2.0:harmful: {'helped': 0, 'worsened': 25, 'no_detectable_effect': 0, 'inconclusive': 75}; reference=worsened; correct=25/100
- 3.0:beneficial: {'helped': 34, 'worsened': 0, 'no_detectable_effect': 0, 'inconclusive': 66}; reference=helped; correct=34/100
- 3.0:harmful: {'helped': 0, 'worsened': 35, 'no_detectable_effect': 0, 'inconclusive': 65}; reference=worsened; correct=35/100
- Completeness: min=0.000, median=0.750, max=1.000; full distribution in JSON.

## Permutation budget 2000

- E1 null false-positive share: 0.0553 (21/380)
- E2 recall at |beta| = 3: 0.8944 (127/142)
- E3 null decisive verdict share: 0.0800 (24/300)
- Hard gates: PASS

### Confounding (E1c)

- any: 0.1416 (16/113)
- flagged: 0.1327 (15/113)
- unflagged: 0.0088 (1/113)

Flagged and unflagged patient shares can overlap when different lags behave differently.
A much larger unflagged share indicates the confounder heuristic rarely fires.

### Short sleep by gamma tercile (E1s)

- low: 0.0120 (4/334)
- middle: 0.0420 (14/333)
- high: 0.1832 (61/333)

### Power curve (E2b)

- T=60, |beta|=1.0: 0.1282 (20/156)
- T=60, |beta|=1.5: 0.3797 (60/158)
- T=60, |beta|=2.0: 0.5704 (81/142)
- T=60, |beta|=3.0: 0.8944 (127/142)
- T=30, |beta|=1.0: 0.0192 (3/156)
- T=30, |beta|=1.5: 0.0759 (12/158)
- T=30, |beta|=2.0: 0.1831 (26/142)
- T=30, |beta|=3.0: 0.3732 (53/142)

### Verdict matrix (E3b)

- 0.0:beneficial: {'helped': 1, 'worsened': 3, 'no_detectable_effect': 1, 'inconclusive': 95}; reference=no_detectable_effect|inconclusive; correct=96/100
- 0.0:harmful: {'helped': 3, 'worsened': 3, 'no_detectable_effect': 0, 'inconclusive': 94}; reference=no_detectable_effect|inconclusive; correct=94/100
- 1.0:beneficial: {'helped': 13, 'worsened': 0, 'no_detectable_effect': 1, 'inconclusive': 86}; reference=helped; correct=13/100
- 1.0:harmful: {'helped': 0, 'worsened': 10, 'no_detectable_effect': 4, 'inconclusive': 86}; reference=worsened; correct=10/100
- 2.0:beneficial: {'helped': 29, 'worsened': 0, 'no_detectable_effect': 0, 'inconclusive': 71}; reference=helped; correct=29/100
- 2.0:harmful: {'helped': 0, 'worsened': 25, 'no_detectable_effect': 0, 'inconclusive': 75}; reference=worsened; correct=25/100
- 3.0:beneficial: {'helped': 34, 'worsened': 0, 'no_detectable_effect': 0, 'inconclusive': 66}; reference=helped; correct=34/100
- 3.0:harmful: {'helped': 0, 'worsened': 35, 'no_detectable_effect': 0, 'inconclusive': 65}; reference=worsened; correct=35/100
- Completeness: min=0.000, median=0.750, max=1.000; full distribution in JSON.

## Limits

Four versus four analysis days have low power. The bootstrap ignores autocorrelation;
One-day washout assumes limited carryover. This is an unblinded, single-person method.
The report includes all measured outcomes, even when a hard gate fails.
