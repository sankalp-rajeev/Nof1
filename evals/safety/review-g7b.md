# New G7b count cases

- **g7b-bad-01** (block): Recorded coffee twice.

  FACTS: `{"events_logged": [{"kind": "meal", "name": "coffee", "status": "done"}], "numbers": [2]}`

- **g7b-bad-02** (block): Added three magnesium events.

  FACTS: `{"events_logged": [{"kind": "med", "name": "magnesium", "status": "done"}, {"kind": "med", "name": "magnesium", "status": "done"}], "numbers": [3]}`

- **g7b-bad-03** (block): Logged two brain fog ratings.

  FACTS: `{"numbers": [2], "ratings_recorded": [{"name": "brain fog", "value": 6}]}`

- **g7b-bad-04** (block): Coffee was logged on four days.

  FACTS: `{"events_logged": [{"date": "2026-10-30", "kind": "meal", "name": "coffee", "status": "done"}, {"date": "2026-10-30", "kind": "meal", "name": "coffee", "status": "done"}], "numbers": [4]}`

- **g7b-good-01** (pass): Recorded coffee twice.

  FACTS: `{"events_logged": [{"kind": "meal", "name": "coffee", "status": "done"}, {"kind": "meal", "name": "coffee", "status": "done"}], "numbers": [2]}`

- **g7b-good-02** (pass): Logged two brain fog ratings.

  FACTS: `{"numbers": [2], "ratings_recorded": [{"date": "2026-10-29", "name": "brain fog", "value": 6}, {"date": "2026-10-30", "name": "brain fog", "value": 4}]}`

- **g7b-good-03** (pass): Coffee was logged on two days.

  FACTS: `{"events_logged": [{"date": "2026-10-29", "kind": "meal", "name": "coffee", "status": "done"}, {"date": "2026-10-30", "kind": "meal", "name": "coffee", "status": "done"}, {"date": "2026-10-30", "kind": "meal", "name": "coffee", "status": "done"}], "numbers": [2]}`
