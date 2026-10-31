# Safety vocabulary and templates

The condition/medicine vocabularies are blocking aids, not a diagnostic ontology.
Names were checked against the [NHS conditions index](https://www.nhs.uk/health-a-to-z/conditions/)
and [NHS medicines index](https://www.nhs.uk/medicines/). They are not recommendations.

The fixed US crisis contact was checked with the connected Hotline tool on
2026-10-30. It lists calling or texting 988. The escalation template uses the exact
phone/SMS links returned by that lookup. Emergency escalation is fixed code and
does not call a provider or suggest logging health details.

All `evals/safety/*.jsonl` files are synthetic. The human reviewed the initial
expansion and conditionally approved P4 subject to the recorded blind probe run
and subsequent generalizations on 2026-10-31; STATUS.md records final approval.
