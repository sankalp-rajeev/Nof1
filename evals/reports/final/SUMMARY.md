# Offline final evaluation — one held-out statistics run

Executed 2026-11-05 under explicit P9 authorization. Command: `make eval-final` (local Make binary and backend Python override), with no `--chat`. Exit code: 0. New live/model generation calls: 0. Provider API cost: $0.

Frozen revision: `b0646f590d2bb4333048b7698095c221418c5331`. Source digest: `2788c3296c4364524a38fcdc358f57bd0e19257d82b82c8a6127644e73a379c4`.

The CLI's required $0.01 positive budget was an unused offline sentinel, not spend. STARTED.json records chat_requested=false; the exclusive final marker was absent before the single invocation and is now consumed. Do not rerun or tune on these held-out results.

## Cohorts and method

- A: 1,000 synthetic patients, seeds 10,000–10,999, 60 days.
- A30: the same 1,000 seeds, 30 days.
- N: 300 null experiments, seeds 10,000–10,299.
- V: 400 experiments, seeds 10,300–10,699, 50 per effect-size/sign cell.
- Full permutation budget: 2,000. Existing deterministic methods and thresholds are unchanged.

## Main results

- E1 null-patient false-positive share: 31/409 = 0.07579462102689487 (7.58%).
- E2 strong-effect recall at |beta|=3: 120/138 = 0.8695652173913043 (86.96%).
- E3 decisive helped/worsened verdict share on null experiments: 18/300 = 0.06 (6.00%).
- Reported hard_gate_failures: [] — the offline synthetic statistical gates met their fixed thresholds. This is not a live extraction/safety or clinical-validity result.

## Power, confounding and verdicts

- E2b T=60, |beta|=1.0: 18/149 = 0.12080536912751678.
- E2b T=60, |beta|=1.5: 56/156 = 0.358974358974359.
- E2b T=60, |beta|=2.0: 82/141 = 0.5815602836879432.
- E2b T=60, |beta|=3.0: 120/138 = 0.8695652173913043.
- E2b T=30, |beta|=1.0: 4/149 = 0.026845637583892617.
- E2b T=30, |beta|=1.5: 13/156 = 0.08333333333333333.
- E2b T=30, |beta|=2.0: 26/141 = 0.18439716312056736.
- E2b T=30, |beta|=3.0: 50/138 = 0.36231884057971014.

- E1c confounded patients: any 19/105; flagged 18/105; unflagged 1/105. Categories can overlap.
- E1s short-sleep reports by gamma tercile: low 5/334; middle 16/333; high 51/333.

- E3b 0.0:beneficial: {'helped': 1, 'inconclusive': 47, 'no_detectable_effect': 1, 'worsened': 1}; reference=no_detectable_effect|inconclusive; correct=48/50.
- E3b 0.0:harmful: {'helped': 1, 'inconclusive': 48, 'no_detectable_effect': 0, 'worsened': 1}; reference=no_detectable_effect|inconclusive; correct=48/50.
- E3b 1.0:beneficial: {'helped': 6, 'inconclusive': 42, 'no_detectable_effect': 1, 'worsened': 1}; reference=helped; correct=6/50.
- E3b 1.0:harmful: {'helped': 0, 'inconclusive': 41, 'no_detectable_effect': 2, 'worsened': 7}; reference=worsened; correct=7/50.
- E3b 2.0:beneficial: {'helped': 14, 'inconclusive': 36, 'no_detectable_effect': 0, 'worsened': 0}; reference=helped; correct=14/50.
- E3b 2.0:harmful: {'helped': 0, 'inconclusive': 39, 'no_detectable_effect': 0, 'worsened': 11}; reference=worsened; correct=11/50.
- E3b 3.0:beneficial: {'helped': 19, 'inconclusive': 31, 'no_detectable_effect': 0, 'worsened': 0}; reference=helped; correct=19/50.
- E3b 3.0:harmful: {'helped': 0, 'inconclusive': 32, 'no_detectable_effect': 0, 'worsened': 18}; reference=worsened; correct=18/50.

Usable-day completeness: min=0.0, median=0.625, max=1.0. Full distribution remains in JSON.

## Raw artifact caveat

The unchanged shared writer names its outputs p3-stats.json / p3-stats.md and carries legacy P3 headings, pending-baseline wording and a false no-held-out sentence in the Markdown template. Those are writer-label defects, not this run's scope. The final CLI and JSON cohort ranges establish that this run used held-out seeds. The previously approved regression baseline remains unchanged; the raw outputs are preserved byte-for-byte and this summary supplies the correct context. Local Git attributes disable line-ending conversion for the three original artifacts so their recorded hashes also survive checkout on other platforms.

This offline run does not replace the P8 safety failures or incomplete live E4 cohort. The method remains unblinded and single-person; short windows, missingness, day-to-day correlation, assumed washout and simulator realism limit interpretation.
