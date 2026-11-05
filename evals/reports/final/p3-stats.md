# P3 stats-only evaluation

Source revision: b0646f590d2bb4333048b7698095c221418c5331
Source digest: 2788c3296c4364524a38fcdc358f57bd0e19257d82b82c8a6127644e73a379c4

Initial regression baseline: pending human approval.
No held-out seeds, live LLMs, or real user data were used.

## Permutation budget 2000

- E1 null false-positive share: 0.0758 (31/409)
- E2 recall at |beta| = 3: 0.8696 (120/138)
- E3 null decisive verdict share: 0.0600 (18/300)
- Hard gates: PASS

### Confounding (E1c)

- any: 0.1810 (19/105)
- flagged: 0.1714 (18/105)
- unflagged: 0.0095 (1/105)

Flagged and unflagged patient shares can overlap when different lags behave differently.
A much larger unflagged share indicates the confounder heuristic rarely fires.

### Short sleep by gamma tercile (E1s)

- low: 0.0150 (5/334)
- middle: 0.0480 (16/333)
- high: 0.1532 (51/333)

### Power curve (E2b)

- T=60, |beta|=1.0: 0.1208 (18/149)
- T=60, |beta|=1.5: 0.3590 (56/156)
- T=60, |beta|=2.0: 0.5816 (82/141)
- T=60, |beta|=3.0: 0.8696 (120/138)
- T=30, |beta|=1.0: 0.0268 (4/149)
- T=30, |beta|=1.5: 0.0833 (13/156)
- T=30, |beta|=2.0: 0.1844 (26/141)
- T=30, |beta|=3.0: 0.3623 (50/138)

### Verdict matrix (E3b)

- 0.0:beneficial: {'helped': 1, 'worsened': 1, 'no_detectable_effect': 1, 'inconclusive': 47}; reference=no_detectable_effect|inconclusive; correct=48/50
- 0.0:harmful: {'helped': 1, 'worsened': 1, 'no_detectable_effect': 0, 'inconclusive': 48}; reference=no_detectable_effect|inconclusive; correct=48/50
- 1.0:beneficial: {'helped': 6, 'worsened': 1, 'no_detectable_effect': 1, 'inconclusive': 42}; reference=helped; correct=6/50
- 1.0:harmful: {'helped': 0, 'worsened': 7, 'no_detectable_effect': 2, 'inconclusive': 41}; reference=worsened; correct=7/50
- 2.0:beneficial: {'helped': 14, 'worsened': 0, 'no_detectable_effect': 0, 'inconclusive': 36}; reference=helped; correct=14/50
- 2.0:harmful: {'helped': 0, 'worsened': 11, 'no_detectable_effect': 0, 'inconclusive': 39}; reference=worsened; correct=11/50
- 3.0:beneficial: {'helped': 19, 'worsened': 0, 'no_detectable_effect': 0, 'inconclusive': 31}; reference=helped; correct=19/50
- 3.0:harmful: {'helped': 0, 'worsened': 18, 'no_detectable_effect': 0, 'inconclusive': 32}; reference=worsened; correct=18/50
- Completeness: min=0.000, median=0.625, max=1.000; full distribution in JSON.

## Limits

Four versus four analysis days have low power. The bootstrap ignores autocorrelation;
One-day washout assumes limited carryover. This is an unblinded, single-person method.
The report includes all measured outcomes, even when a hard gate fails.
