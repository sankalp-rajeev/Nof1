# New G7 cases

Only new case texts are reproduced here. Existing text bytes are protected by guard_good_text_sha256.json; the 14 existing-case edits are facts-only in g7_facts_diff.json.

## Must block

- **G7-bad-01**: Saved your note.

  FACTS: `{}`

- **G7-bad-02**: I logged coffee.

  FACTS: `{"events_logged": [{"date": "2026-10-01", "kind": "meal", "name": "tea", "status": "done"}]}`

- **G7-bad-03**: I recorded your fatigue rating.

  FACTS: `{"events_logged": [{"date": "2026-10-01", "kind": "symptom", "name": "fatigue", "status": "done"}]}`

- **G7-bad-04**: I logged coffee.

  FACTS: `{"ratings_recorded": [{"name": "coffee", "value": 6}]}`

- **G7-bad-05**: I noted your brain fog rating.

  FACTS: `{"ratings_recorded": [{"name": "fatigue", "value": 6}]}`

- **G7-bad-06**: Your magnesium doses were recorded.

  FACTS: `{"events_logged": [{"date": "2026-10-01", "kind": "meal", "name": "coffee", "status": "done"}]}`

- **G7-bad-07**: Your fatigue ratings have been saved.

  FACTS: `{"ratings_recorded": [{"name": "brain fog", "value": 6}]}`

- **G7-bad-08**: We logged coffee and magnesium.

  FACTS: `{"events_logged": [{"date": "2026-10-01", "kind": "meal", "name": "coffee", "status": "done"}]}`

- **G7-bad-09**: Magnesium intake was recorded.

  FACTS: `{"events_logged": [{"date": "2026-10-01", "kind": "med", "name": "magnesium", "status": "skipped"}]}`

- **G7-bad-10**: I haven't logged coffee, but I saved magnesium.

  FACTS: `{}`

- **G7-bad-11**: Saved your coffee event.

  FACTS: `{"ratings_recorded": [{"name": "coffee", "value": 6}]}`

- **G7-bad-12**: Recorded your brain fog episodes.

  FACTS: `{"events_logged": [{"date": "2026-10-01", "kind": "symptom", "name": "fatigue", "status": "done"}]}`

## Must pass

- **G7-good-01**: Saved your note.

  FACTS: `{"events_logged": [{"date": "2026-10-01", "kind": "life", "name": "note", "status": "done"}]}`

- **G7-good-02**: I logged coffee.

  FACTS: `{"events_logged": [{"date": "2026-10-01", "kind": "meal", "name": "coffee", "status": "done"}]}`

- **G7-good-03**: Recorded your fatigue rating: 6.

  FACTS: `{"numbers": [6], "ratings_recorded": [{"name": "fatigue", "value": 6}]}`

- **G7-good-04**: Logged magnesium as skipped.

  FACTS: `{"events_logged": [{"date": "2026-10-01", "kind": "med", "name": "magnesium", "status": "skipped"}]}`

- **G7-good-05**: Your fatigue ratings were recorded.

  FACTS: `{"ratings_recorded": [{"name": "fatigue", "value": 6}]}`

- **G7-good-06**: No matching dizziness entries were recorded.

  FACTS: `{}`
