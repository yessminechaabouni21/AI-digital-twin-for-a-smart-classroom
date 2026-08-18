# Spanish Classroom CO₂ Preprocessing Plan

Plan + findings from direct inspection of `data/raw/environmental_sensors.csv`
(38,890 data rows, 13 columns), done as part of this pass — no prior profiling
document exists for this dataset. Every cleaning/key/duplicate decision below
is a direct consequence of a finding stated explicitly here.

**Not the UCI Occupancy Detection dataset.** That dataset lives separately at
`data/raw/occupancy+detection/` and is not touched by this plan, this schema,
or this preprocessing code. There is no shared identifier, no join, and no
code in this pipeline should assume otherwise.

Target schema being populated (new, independent of OULAD/xAPI/ASSISTments and
of any future Occupancy Detection schema): a single table,
`co2_sensor_readings`.

---

## Source profile

- **1 file**, `data/raw/environmental_sensors.csv` — 38,890 data rows (plus
  header), 13 columns: `published_at, date_time, date, month, w_day, hour,
  mint, sec, temp, hum, co2, bat, sensor_id`.
- **Malformed CSV framing**: every line (including the header) is wrapped in
  an outer pair of double quotes, with every embedded double quote doubled
  (`"published_at,""date_time"",...`). `pandas.read_csv` cannot parse this
  directly — it reads the whole file as a single column. The preprocessing
  stage strips the outer quote pair from each line and un-escapes `""` → `"`
  before handing the text to `pandas.read_csv`. This is a framing fix only,
  no field values are altered by it.
- **Zero missing values** in any column — confirmed by direct inspection, and
  re-asserted at load time.
- **413 fully-duplicate rows** (all 13 columns identical, including
  `sensor_id` and `published_at` to the millisecond) — evidence of sensor
  retransmission, not 413 independent readings. After `drop_duplicates()`,
  38,477 rows remain and `(sensor_id, published_at)` is unique with **zero**
  remaining collisions (verified: 0 rows share `(sensor_id, published_at)`
  post-dedup, and no case exists anywhere in the source where the same
  `(sensor_id, published_at)` pair carries *different* other values — the 413
  duplicates are the only source of collision). This is the opposite
  situation from xAPI's 4 duplicate rows (see xapi-preprocessing-plan.md):
  there, no natural key existed even after accounting for duplicates, so they
  were kept. Here, dropping the duplicates directly *produces* a clean
  natural key, so they are dropped.
- **6 sensors**: `CO2_01`..`CO2_06`. Row counts per sensor are uneven (4,739
  to 7,552) — expected for independently-operating hardware, not a data
  quality issue.
- **`sensor_id` has a stray leading space** in every value in the raw file
  (e.g. `" CO2_06"`, not `"CO2_06"`) — an artifact of the malformed-CSV
  framing (the field follows a comma inside the doubled-quote structure).
  Stripped at preprocessing time.
- **Date range**: 2021-05-03T07:00:05.241Z to 2021-05-31T11:15:07.113Z — one
  calendar month, May 2021.
- **`date`, `month`, `w_day`, `hour`, `mint`, `sec` are 100% derivable from
  `date_time`** — verified programmatically (date match, `%B` month name
  match, `%a` weekday match, hour/minute/second match, all `True` across all
  38,890 rows). Per CLAUDE.md's instruction not to store redundant derived
  date/time fields without a clear reason, none of these six columns are
  persisted.
- **`published_at` and `date_time` represent the same instant**, but are not
  identical representations: `published_at` is UTC (`Z` suffix) with
  millisecond precision; `date_time` has no timezone marker and truncates to
  whole seconds. Their difference is always in `[0, 1)` seconds (consistent
  with `date_time` being a truncation of `published_at`, not a second
  independent measurement). `published_at` is the more complete of the two,
  so it is kept as the table's single timestamp column; `date_time` is
  dropped as redundant.
- **Value ranges observed** (all physically plausible for an indoor
  classroom CO₂/temp/humidity sensor, no negative or absurd values):
  - `temp`: 20.0 – 39.9 °C
  - `hum`: 14.3 – 63.9 %
  - `co2`: 301 – 1,213 ppm
  - `bat`: 0.0 – 100.0 % — **40 rows have `bat == 0`**, spread across
    multiple sensors. This is kept as-is, not treated as invalid: a battery
    reading of 0 is real sensor-health signal (a dying/dead battery), and the
    corresponding `temp`/`hum`/`co2` readings on those rows are not
    themselves out of range, so there's no basis for discarding the row.

---

## Guiding rules for this pass

1. **One file, one logical table.** All 38,890 rows share the same 13
   columns, the same measurement grain (one sensor, one timestamp, one
   reading), and no join key to any other file — there's nothing to
   normalize into a separate sensor-metadata table. A `co2_sensors` lookup
   table was considered and rejected: nothing beyond `sensor_id` describes a
   sensor (no model, location, or install-date column exists in the source),
   so a second table would carry only a single column duplicating
   `co2_sensor_readings.sensor_id`'s distinct values — pure overhead.
2. **Re-verify every claim in this document at load time**, same discipline
   as OULAD/xAPI/ASSISTments — the duplicate count, null count, and
   derived-column-redundancy findings above are point-in-time observations;
   the preprocessing stage asserts them rather than trusting this document on
   a future re-download.
3. **Never merge with UCI Occupancy Detection, OULAD, xAPI, or ASSISTments.**
   No column in this source overlaps in meaning or identity space with any
   table in those schemas. `co2_sensor_readings` is loaded standalone.
4. **Persist raw measurements, not encodings or aggregates.** `temp`, `hum`,
   `co2`, `bat` are stored as given (renamed for clarity, not transformed).
   No binning, no rolling averages — that's an `analytics/`-layer concern.

---

## Pipeline — 1 stage

### `environmental_sensors.csv` → `co2_sensor_readings`

- **Framing fix:** strip the outer quote pair and un-escape doubled quotes on
  every raw line before parsing as CSV (see "Malformed CSV framing" above).
- **Cleaning:** strip leading/trailing whitespace from `sensor_id`.
- **Column selection:** keep `sensor_id`, `published_at`, `temp`, `hum`,
  `co2`, `bat`. Drop `date_time` (redundant, lower-precision duplicate of
  `published_at`) and `date`/`month`/`w_day`/`hour`/`mint`/`sec` (100%
  derivable from `date_time`/`published_at`).
- **Renaming:** `published_at` → `recorded_at`, `temp` → `temperature_c`,
  `hum` → `humidity_pct`, `co2` → `co2_ppm`, `bat` → `battery_pct`.
- **Missing values:** none present — asserted, not assumed.
- **Duplicates:** `drop_duplicates()` on the full row **before** column
  selection (so a duplicate is judged on all 13 source columns, not just the
  6 retained ones). Row count drops from 38,890 to 38,477. This is a
  deliberate deviation from xAPI's "never collapse duplicates" rule — see
  "413 fully-duplicate rows" above for why the two cases differ.
- **Dtype conversions:** `sensor_id` → `string`; `recorded_at` → UTC
  timezone-aware `datetime64`; `temperature_c`/`humidity_pct`/`battery_pct` →
  `float64`; `co2_ppm` → `int64`.
- **Primary-key validation:** assert `(sensor_id, recorded_at)` is unique
  post-dedup (`assert_unique`).
- **Range checks (non-fatal, `warn_out_of_range`):** `temperature_c` in
  [0, 50] °C, `humidity_pct` in [0, 100] %, `co2_ppm` in [300, 5000] ppm,
  `battery_pct` in [0, 100] % — observations from profiling, not
  schema-enforced source constraints, so a future violation is logged, not
  rejected.
- **`sensor_id` validity check:** log (not reject) if a future load sees a
  `sensor_id` outside the 6 values observed here (`CO2_01`..`CO2_06`) — new
  sensors being added over time is plausible and not itself an error.
- **Load into Postgres:** single stage, no dependency ordering.

---

## PostgreSQL load

```
1. co2_sensor_readings   (standalone — no FK to any other table)
```

---

## Primary key strategy

**Natural composite key**: `(sensor_id, recorded_at)`. Verified unique after
dropping the 413 fully-duplicate rows (0 collisions), and re-verified
programmatically at load time. No surrogate key is introduced — unlike
xAPI's `record_id`, a natural key genuinely exists here once the exact
duplicate retransmissions are removed.

---

## Schema

```
co2_sensor_readings
├── sensor_id       String(10), PK       -- "CO2_01".."CO2_06" observed
├── recorded_at     DateTime(tz=True), PK -- from published_at, UTC, ms precision
├── temperature_c   Float, not null
├── humidity_pct    Float, not null
├── co2_ppm         Integer, not null
└── battery_pct     Float, not null       -- 0 = dead/dying battery, kept as signal
```

---

## Features preserved for the Classroom Digital Twin

This dataset feeds **environmental time-series monitoring**, not occupancy
classification — it has no occupancy label and is never treated as one:

- **Per-sensor time series**: `temperature_c`, `humidity_pct`, `co2_ppm`
  trends over time for a given `sensor_id`, usable as a classroom's ambient
  air-quality signal (e.g. rising CO₂ as a proxy for poor ventilation/
  occupancy density, without claiming it *is* an occupancy measurement).
- **Sensor health monitoring**: `battery_pct` trends per `sensor_id` support
  detecting a dying sensor (declining battery) or a data gap explained by
  battery depletion, rather than a silent, unexplained gap in the twin's
  environmental signal.
- **Not linked to any student or class identity.** There is no `sensor_id`
  → classroom/course mapping in the source data — inventing one would
  violate CLAUDE.md's "don't invent relationships that don't exist in the
  source data." Until a real sensor-to-classroom mapping is supplied,
  `co2_sensor_readings` supports a classroom-environment twin only at the
  granularity of "this sensor," not "this specific classroom/course."

---

## Resolved scope decisions

1. **Single table, no sensor-metadata table.** Nothing beyond `sensor_id`
   describes a sensor in this source; a separate table would add a join for
   no informational gain.
2. **`co2_` table prefix**, not `environmental_` or `sensor_` — deliberately
   specific so this table is never confused with a future, differently-
   shaped Occupancy Detection or generic-sensor schema. Follows the same
   dataset-scoped-prefix convention as `xapi_`/`assist_`.
3. **413 exact-duplicate rows dropped**, not kept — direct evidence
   (retransmission, not independent readings) supports this, unlike xAPI's
   duplicates.
4. **Natural composite PK `(sensor_id, recorded_at)`**, no surrogate —
   confirmed unique post-dedup by direct evidence, not assumed.
5. **`published_at` kept as `recorded_at`; `date_time` and all six derived
   date/time columns dropped** — redundancy verified column-by-column, not
   assumed from column naming alone.
6. **Independent schema**, no join to OULAD, xAPI, ASSISTments, or any future
   Occupancy Detection table.
7. **Code location:** `data/preprocessing/preprocess_environmental_sensors.py`
   plus a `load_environmental_sensors.py` orchestrator mirroring
   `load_xapi.py`'s single-stage shape, reusing existing `validation.py`
   helpers.
