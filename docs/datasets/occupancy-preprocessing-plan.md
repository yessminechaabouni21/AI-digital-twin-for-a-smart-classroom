# UCI Occupancy Detection Preprocessing Plan

Plan + findings from direct inspection of the three raw files under
`data/raw/occupancy+detection/`, done as part of this pass — no prior
profiling document exists for this dataset.

**Not the Spanish Classroom CO₂ dataset.** That dataset lives separately at
`data/raw/environmental_sensors.csv` and is loaded into `co2_sensor_readings`
(see [spanish-co2-preprocessing-plan.md](spanish-co2-preprocessing-plan.md)).
There is no shared identifier, no join, and no code in this pipeline should
assume otherwise. This dataset also has no relationship to OULAD, xAPI,
ASSISTments, or any future Dropout Prediction / NYC Attendance schema.

Target schema being populated (new, independent of every schema above): a
single table, `occupancy_readings`.

---

## Source profile

- **3 files**, all under `data/raw/occupancy+detection/`:
  - `datatraining.txt` — 8,143 data rows
  - `datatest.txt` — 2,665 data rows
  - `datatest2.txt` — 9,752 data rows
  - **20,560 rows total.** (Note: the actual filenames on disk are
    `datatraining.txt`, `datatest.txt`, `datatest2.txt` — the original task
    description referred to `dataset.txt`/`dataset2.txt`, but these three are
    the only occupancy-detection files present in the repo and match the
    documented UCI Occupancy Detection column layout exactly.)
- **8 columns per line, 7 named** in the header
  (`"date","Temperature","Humidity","Light","CO2","HumidityRatio","Occupancy"`):
  every data line has an extra **leading unnamed field**, a per-file row id
  (e.g. `"1","2015-02-04 17:51:00",23.18,...`). Parsed as the DataFrame index
  (`index_col=0`), not a named column.
- **Quoting is inconsistent within and across files**: most fields are
  double-quoted (`"1"`, `"2015-02-04 17:51:00"`), but `datatest2.txt` leaves
  `date` and several numeric fields unquoted on every line. Both parse
  correctly under standard CSV quoting rules (`pandas.read_csv` default), so
  no framing fix is needed — unlike the Spanish CO₂ source.
- **Zero missing values** in any column, any file — confirmed by direct
  inspection, re-asserted at load time.
- **Zero duplicate rows** (full-row) and **zero duplicate timestamps** within
  any individual file.
- **Row-id column is per-file, not a global identifier**: `datatraining.txt`
  ids run 1–8143, `datatest.txt` ids run 140–2804, `datatest2.txt` ids run
  1–9752. Ranges overlap *in value* across files (e.g. both `datatraining.txt`
  and `datatest2.txt` contain a row id `1`) — confirming this id only has
  meaning paired with its source file, never as a standalone key.
- **Date ranges are disjoint across all three files, and non-overlapping in
  time**:
  - `datatest.txt`: 2015-02-02 14:19:00 → 2015-02-04 10:43:00
  - `datatraining.txt`: 2015-02-04 17:51:00 → 2015-02-10 09:33:00
  - `datatest2.txt`: 2015-02-11 14:48:00 → 2015-02-18 09:19:00

  Verified programmatically: zero timestamp overlap between any pair of
  files. Combined with the well-known UCI naming (`datatraining` /
  `datatest` / `datatest2`), these are **chronologically contiguous-ish
  splits of one continuous sensor deployment** (the original ML train/test
  split for the occupancy-classification benchmark task), not three
  independent datasets and not random samples of a larger pool. They are
  treated here as **one logical dataset**, loaded into one table, with the
  originating file preserved per row (`source_file`) so the original
  split is never lost.
- **No timezone marker** on any timestamp (e.g. `2015-02-04 17:51:00`, no `Z`
  or offset) — stored as a naive timestamp, unlike `co2_sensor_readings.recorded_at`
  which had an explicit UTC `Z` suffix. Nothing in the source establishes a
  timezone; inventing one (e.g. assuming UTC) would not be justified by the
  data itself.
- **Occupancy distribution** — binary `{0, 1}` in every file, no other values
  observed:
  - `datatraining.txt`: 6,414 × 0, 1,729 × 1 (21.2% occupied)
  - `datatest.txt`: 1,693 × 0, 972 × 1 (36.5% occupied)
  - `datatest2.txt`: 7,703 × 0, 2,049 × 1 (21.0% occupied)
- **Value ranges observed** (all physically plausible for an indoor office/
  classroom sensor deployment, no negative or absurd values):
  - `Temperature`: 19.0 – 24.41 °C
  - `Humidity`: 16.75 – 39.5 %
  - `Light`: 0 – 1,697.25 (lux). A large fraction of rows (5,160 /
    8,143 in training; 1,615 / 2,665 in test; 5,997 / 9,752 in test2) have
    `Light == 0` — physically consistent with "lights off / room dark /
    unoccupied," not a sensor fault, and correlates with `Occupancy == 0` as
    expected. Kept as-is.
  - `CO2`: 412.75 – 2,076.5 ppm. Unlike the Spanish CO₂ dataset's `co2_ppm`
    (integer readings), these values carry fractional ppm (e.g. `713.5`,
    `1029.666...`) — stored as `Float`, not `Integer`.
  - `HumidityRatio`: 0.002674 – 0.006476 (kg water / kg dry air) — a derived
    humidity measure already present in the source, not computed here.

---

## Guiding rules for this pass

1. **Three files, one logical table.** All three share the same 7 measured
   columns, the same measurement grain (one room, one timestamp, one
   reading), and are time-disjoint segments of a single sensor deployment —
   there is no basis for three separate tables. `source_file` is kept as a
   column so the original split is recoverable, not discarded.
2. **Re-verify every claim in this document at load time** — same discipline
   as OULAD/xAPI/ASSISTments/CO₂: null count, duplicate count, cross-file
   timestamp disjointness, and the `Occupancy` value set are all asserted in
   code, not trusted from this document on a future re-download.
3. **Never merge with `co2_sensor_readings`, OULAD, xAPI, or ASSISTments.**
   No column here overlaps in meaning or identity space with any of those
   schemas. `occupancy_readings` is loaded standalone.
4. **Persist raw measurements, not encodings or aggregates.** `Temperature`,
   `Humidity`, `Light`, `CO2`, `HumidityRatio` are stored as given (renamed
   for naming-convention consistency, not transformed). No binning, no
   rolling averages — that is an `analytics/`-layer concern.

---

## Pipeline — 1 stage

### `{datatraining,datatest,datatest2}.txt` → `occupancy_readings`

- **Parsing:** standard `pandas.read_csv` per file, `index_col=0` (the
  leading unnamed row-id field), no framing fix needed.
- **Combining:** concatenate the three parsed frames, tagging each row with
  `source_file` (`"training"`, `"test"`, `"test2"`) before concatenation.
- **Column selection / renaming:** `date` → `recorded_at`, `Temperature` →
  `temperature_c`, `Humidity` → `humidity_pct`, `Light` → `light_lux`, `CO2`
  → `co2_ppm`, `HumidityRatio` → `humidity_ratio`, `Occupancy` → `occupancy`.
  The per-file row id becomes `source_row_id` (informational only, not part
  of the primary key, since it repeats across files by design).
- **Missing values:** none present — asserted per file, not assumed.
- **Duplicates:** none present within any file — asserted, not assumed. Not
  re-checked post-concatenation beyond the primary-key uniqueness check
  below, since `source_file` is part of the key and the three files are
  independently duplicate-free.
- **Dtype conversions:** `source_file` → `string` (categorical values,
  see below); `recorded_at` → naive `datetime64` (no timezone in source);
  `temperature_c`/`humidity_pct`/`light_lux`/`co2_ppm`/`humidity_ratio` →
  `float64`; `occupancy` → `int64`; `source_row_id` → `int64`.
- **Primary-key validation:** assert `(source_file, recorded_at)` is unique
  (`assert_unique`) — true both within each file (verified) and across files
  (verified zero cross-file timestamp overlap), so this also gives a
  collision-free key even though `recorded_at` alone happens to be globally
  unique in the current data.
- **Row-count preservation:** assert combined row count equals the sum of
  the three source files' row counts (`assert_row_count_preserved`) — no
  step in this pipeline is expected to drop or add rows.
- **Range checks (non-fatal, `warn_out_of_range`):** `temperature_c` in
  [0, 50] °C, `humidity_pct` in [0, 100] %, `light_lux` in [0, 2000] lux,
  `co2_ppm` in [300, 5000] ppm, `humidity_ratio` in [0, 0.03] — observations
  from profiling, not schema-enforced source constraints, so a future
  violation is logged, not rejected.
- **`occupancy` domain validation (fatal):** assert every value is in
  `{0, 1}` — the only two values this dataset's target variable supports;
  unlike the range checks above, an out-of-domain occupancy value would mean
  the label itself is corrupted, not just an unusual measurement, so this
  rejects the load rather than warning.
- **`source_file` domain validation (fatal):** assert every value is in
  `{"training", "test", "test2"}` — this is an internally-assigned tag, not
  raw source data, so any other value indicates a bug in this pipeline.
- **Load into Postgres:** single stage, no dependency ordering.

---

## PostgreSQL load

```
1. occupancy_readings   (standalone — no FK to any other table)
```

---

## Primary key strategy

**Natural composite key**: `(source_file, recorded_at)`. Verified unique
within each file and across all three files (zero timestamp collisions,
zero cross-file overlap), and re-verified programmatically at load time. No
surrogate key is introduced — the per-file row id is not globally unique by
design (each file restarts its own numbering) so it is kept only as an
informational `source_row_id` column, not as (part of) the key.

---

## Schema

```
occupancy_readings
├── source_file      String(8), PK   -- "training" | "test" | "test2"
├── recorded_at      DateTime(tz=False), PK  -- naive, no tz in source
├── source_row_id    Integer, not null  -- original per-file row id, informational only
├── temperature_c    Float, not null
├── humidity_pct     Float, not null
├── light_lux        Float, not null   -- 0 observed for rooms with lights off/unoccupied
├── co2_ppm          Float, not null   -- fractional ppm, unlike co2_sensor_readings' integer co2_ppm
├── humidity_ratio   Float, not null   -- kg water / kg dry air, precomputed in source
└── occupancy        Integer, not null -- target variable, restricted to {0, 1}
```

---

## Features preserved for the Classroom Digital Twin

This dataset feeds **ground-truth room-occupancy time series**, distinct
from `co2_sensor_readings`' ambient air-quality-only signal:

- **Binary occupancy ground truth** (`occupancy`) alongside the environmental
  readings that correlate with it (`co2_ppm`, `light_lux`, `temperature_c`,
  `humidity_pct`) — usable later (in `analytics/`, not this pass) as
  training data for an occupancy-from-environment classifier, or as a
  reference for validating occupancy inferred from other classroom sensors.
- **`source_file` preserves the original train/test split** used in the
  published benchmark, so a later ML pass can reproduce the canonical
  train/test evaluation instead of re-splitting arbitrarily.
- **Not linked to any student, class, or room identity.** There is no
  room/building identifier in the source data — inventing one would violate
  CLAUDE.md's "don't invent relationships that don't exist in the source
  data." This table supports a classroom-environment twin only at the
  granularity of "this deployment's timestamped readings," not a specific
  named classroom, until a real room mapping is supplied.

---

## Limitations

- Single room/sensor deployment, ~16 days of data (2015-02-02 to
  2015-02-18) — not a multi-room or multi-week dataset. Any twin feature
  built on this data should be scoped as a small reference/ground-truth
  signal, not treated as broad building-wide occupancy coverage.
- No timezone information — timestamps are naive and their absolute UTC
  offset is unknown.
- No spatial/room identifier to join against any other dataset in this
  project.

---

## Resolved scope decisions

1. **Single table, all three files combined.** They are time-disjoint
   segments of one deployment (verified, not assumed from filenames alone);
   splitting them into three tables would add join overhead for no
   informational gain, and merging them without preserving `source_file`
   would silently discard the original train/test split.
2. **No `occupancy_` or dataset-name table prefix** — `occupancy_readings`
   is already unambiguous and distinct from `co2_sensor_readings`; matches
   the CO₂ table's own precedent of using a descriptive, not schema-prefixed,
   name for a standalone single-table dataset.
3. **Natural composite PK `(source_file, recorded_at)`**, no surrogate —
   confirmed unique both within-file and cross-file by direct evidence.
4. **`source_row_id` kept as a plain informational column**, not part of the
   key — it is not globally unique by construction (each file restarts its
   own numbering).
5. **Independent schema**, no join to `co2_sensor_readings`, OULAD, xAPI, or
   ASSISTments.
6. **Code location:** `data/preprocessing/preprocess_occupancy.py` plus a
   `load_occupancy.py` orchestrator mirroring `load_environmental_sensors.py`'s
   single-stage shape, reusing existing `validation.py` helpers (extended
   with one new helper, `assert_allowed_values`, for the fatal `occupancy`/
   `source_file` domain checks — no existing helper covers "value must be in
   this finite set").
