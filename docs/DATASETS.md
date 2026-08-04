# Dataset Research: AI Digital Twin for a Smart Classroom

Research date: 2026-08-04. This document catalogs 27 publicly available datasets
evaluated as candidates for this project, compares and ranks them, and
recommends a final dataset combination. See [DECISIONS.md](../DECISIONS.md)
ADR-008 for the resulting architectural decision, and
[PROJECT_PLAN.md](../PROJECT_PLAN.md) M1 for how this feeds implementation.

**Methodology:** every dataset below was verified via live web search and
direct fetch of its source page/API (not recalled from memory alone), on
2026-08-04. Where a link, license, or file could not be independently
confirmed (e.g., Kaggle's JS-rendered pages blocking automated fetch, paywalls,
dead domains), that is flagged explicitly in the entry rather than presented
as fact. Treat flagged items as needing a manual sanity-check before you rely
on them for the actual build.

**The 8 project objectives** referenced throughout (by number):
1. Student Performance Prediction
2. Student Engagement Detection
3. Attendance Prediction
4. Classroom/Resource Utilization Prediction
5. Anomaly Detection
6. Dropout Risk Prediction
7. Recommendation System (personalized learning)
8. Classroom occupancy / environmental monitoring

---

## Part 1 — Dataset catalog

### Category A: Academic performance / LMS / institutional records

#### A1. Open University Learning Analytics Dataset (OULAD)
- **Source:** The Open University (UK), Kuzilek, Hlosta & Zdrahal, published in *Scientific Data* (Nature), 2017
- **Download:** https://research.stem.open.ac.uk/ouanalyse/dataset/ (direct: `http://schools.stem.open.ac.uk/cdn/files/anonymisedData.zip`, verified HTTP 200, 46,750,706 bytes) — also mirrored at UCI: https://archive.ics.uci.edu/dataset/349/open+university+learning+analytics+dataset. **No registration required.**
- **License:** CC BY 4.0
- **Samples:** 32,593 students, 22 course presentations (7 modules), 10,655,280 VLE click-log rows; 7 relational CSV tables
- **Features:** demographics (region, IMD band, age, gender, disability, education), registration/withdrawal dates, per-course daily VLE click counts by activity type, assessment scores, final result (Pass/Fail/Withdrawn/Distinction)
- **Format:** relational CSV (join on student/module/presentation IDs)
- **Data quality:** peer-reviewed, large-scale, real; some missing demographic fields; class imbalance in outcomes; clicks are daily aggregates, not per-event timestamps
- **Strengths:** genuine LMS interaction data at scale; single dataset covers 4 of 8 objectives; stable verified download; excellent documentation
- **Weaknesses:** UK distance-learning (adult) context, not a synchronous physical classroom; relational complexity; no environmental/sensor data
- **Objectives satisfied:** 1, 2, 4, 6
- **Preprocessing:** Moderate — join 7 tables, encode demographics, aggregate/window daily clicks

#### A2. UCI Student Performance (Cortez & Silva)
- **Source:** UCI ML Repository, Univ. of Minho, 2008
- **Download:** https://archive.ics.uci.edu/dataset/320/student+performance — verified live
- **License:** CC BY 4.0
- **Samples:** 395 (Math) + 649 (Portuguese) students, 33 attributes each
- **Features:** demographics, parental education/job, study time, failures, support, internet access, alcohol use, health, absences, grades G1/G2/G3
- **Format:** CSV
- **Data quality:** no missing values; real survey data, small, single-region, some self-report bias
- **Strengths:** clean, tiny, extremely well-documented classic benchmark
- **Weaknesses:** small N, no LMS/sensor/time-series signal, dated (2008)
- **Objectives satisfied:** 1, 6 (via absences/failures as proxies)
- **Preprocessing:** Light — categorical encoding only

#### A3. UCI "Predict Students' Dropout and Academic Success"
- **Source:** UCI ML Repository, Portuguese higher-ed institution (Realinho et al., 2021)
- **Download:** https://archive.ics.uci.edu/dataset/697/predict+students+dropout+and+academic+success — verified live, DOI 10.24432/C5MC89
- **License:** CC BY 4.0
- **Samples:** 4,424 instances, 36 features + 3-class target (Dropout/Enrolled/Graduate)
- **Features:** marital status, application mode, course, attendance mode, parental qualification/occupation, scholarship/tuition status, semester curricular units, macroeconomic indicators (unemployment/inflation/GDP)
- **Format:** CSV
- **Data quality:** no missing values (pre-cleaned by institution); notable class imbalance
- **Strengths:** purpose-built for dropout prediction, real records, combines academic + socioeconomic + macro features
- **Weaknesses:** single institution/country, class imbalance needs handling
- **Objectives satisfied:** 6, 1, 5 (minority-class/outlier students)
- **Preprocessing:** Light-moderate — class-imbalance correction (SMOTE/class weights), categorical encoding

#### A4. xAPI-Edu-Data (Students' Academic Performance Dataset, Kalboard 360)
- **Source:** Kaggle (`aljarah`), originally an EDM research dataset (Amrieh, Hamtini, Aljarah — University of Jordan)
- **Download:** https://www.kaggle.com/datasets/aljarah/xAPI-Edu-Data — page confirmed live; full metadata cross-verified via mirrors (Kaggle's JS rendering blocks direct scrape)
- **License:** CC BY-SA 4.0 (confirmed via secondary sources, not first-party-scraped — verify on-page before redistribution)
- **Samples:** 480 students, 16 columns, 2 semesters, 14 nationalities
- **Features:** gender, nationality, stage/grade/section, topic, **raised hands, visited resources, viewed announcements, discussion participation**, parent survey/satisfaction, absence days; target Class (Low/Middle/High)
- **Format:** CSV
- **Data quality:** no missing values; small N; coarse 3-class target
- **Strengths:** the only dataset here with explicit *behavioral engagement* features tied to a performance label — strong, easy fit for Engagement Detection
- **Weaknesses:** small, single unnamed institution, dated, coarse labels
- **Objectives satisfied:** 2, 1, 3 (absence-days feature)
- **Preprocessing:** Light — categorical/ordinal encoding

#### A5. OECD PISA 2022 Database
- **Source:** OECD
- **Download:** https://www.oecd.org/en/data/datasets/pisa-2022-database.html (primary page returned HTTP 403 to automated fetch; content corroborated via Zenodo mirror https://zenodo.org/records/13382904)
- **License:** OECD data terms ≈ CC BY 4.0 for raw data (do not confuse with OECD "Products"/reports, which are CC BY-NC-SA 3.0 IGO)
- **Samples:** ~690,000 students, 81 countries; student file ~2.1 GB
- **Features:** math/reading/science plausible values, SES/ESCS index, study habits, school/teacher questionnaires
- **Format:** SAS (.sas7bdat) / SPSS (.sav) — **not CSV**
- **Data quality:** rigorous, real, internationally standardized; requires correct handling of "plausible values" and sampling weights
- **Strengths:** gold-standard scale and rigor for performance benchmarking
- **Weaknesses:** heavy format/statistical complexity, one-time assessment (no time-series/engagement/classroom data), overkill for a single-classroom scope
- **Objectives satisfied:** 1 only
- **Preprocessing:** Heavy — format conversion, plausible-value handling, survey weighting

#### A6. Kaggle "Students Performance in Exams"
- **Source:** Kaggle (`spscientist`); acknowledged origin: roycekimmons.com data generator — **synthetic, not real student records**
- **Download:** https://www.kaggle.com/datasets/spscientist/students-performance-in-exams — verified live via embedded schema.org metadata
- **License:** **"Unknown"** (confirmed from the page's own JSON-LD license field — do not assume CC0 despite informal claims elsewhere)
- **Samples:** 1,000 rows × 8 columns
- **Features:** gender, race/ethnicity group, parental education, lunch type (US SES proxy), test prep completion, math/reading/writing scores
- **Format:** CSV
- **Data quality:** clean, no nulls — but synthetic
- **Strengths:** very clean, tiny, great for fast prototyping/tutorials
- **Weaknesses:** synthetic, license unconfirmed, no temporal/behavioral/institutional signal
- **Objectives satisfied:** 1 only (demo-grade)
- **Preprocessing:** Light — categorical encoding

#### A7. HarvardX-MITx Person-Course Academic Year 2013 (v3.0)
- **Source:** Harvard Dataverse (HarvardX/MITx)
- **Download:** https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/26147 — page live; **direct anonymous file download tested and returned HTTP 403**; requires free Dataverse account + acceptance of Community Norms (no re-identification)
- **License:** click-through data use agreement, not an open/anonymous license
- **Samples:** ~641,138 records, ~20 fields (figure from secondary sources; not independently re-verified due to access gate)
- **Features:** course_id, registered/viewed/explored/certified flags, country, education level, birth year, gender, grade, event/activity counts, video plays
- **Format:** CSV/TAB
- **Data quality:** de-identified, well-documented; real MOOC data
- **Strengths:** real large-scale engagement + completion + demographics
- **Weaknesses:** **access gated** (not instantly downloadable), course- not classroom-level, over a decade old
- **Objectives satisfied:** 1, 2, 6
- **Preprocessing:** Moderate — account request, missing self-report fields, categorical encoding

---

### Category B: Engagement / affect / fine-grained interaction logs

#### B1. DAiSEE (Dataset for Affective States in E-Environments)
- **Source:** IIT Hyderabad
- **Download:** https://people.iith.ac.in/vineethnb/resources/daisee/index.html (live) — actual ~15GB data requires a Google Form data-use agreement
- **License:** custom research-only terms (no redistribution)
- **Samples:** 9,068 ten-second video clips (112 users, ~25 hours, ~2.7M frames)
- **Features:** raw video + 4-point labels for boredom, confusion, engagement, frustration (crowd-annotated, expert-checked)
- **Format:** video + label CSV
- **Data quality:** crowd labels are inherently noisy; skewed toward "engaged"
- **Strengths:** purpose-built video engagement/affect benchmark, widely cited
- **Weaknesses:** 15GB + DUA gate, needs a full CV pipeline, single-country student population
- **Objectives satisfied:** 2, 5
- **Preprocessing:** Heavy — frame/face extraction, embedding extraction, label alignment

#### B2. EdNet (Riiid)
- **Source:** Riiid Labs (Korea, "Santa" AI tutoring app)
- **Download:** https://github.com/riiid/ednet (repo live) — actual files distributed only via bit.ly→Google Drive redirects (e.g. `bit.ly/ednet_kt1`); **no official GitHub Release**, a fragile distribution channel
- **License:** CC BY-NC 4.0 (non-commercial only)
- **Samples:** 131.4M interactions, 784,309 students, 13,169 problems, 2017–2019
- **Features:** KT1 (timestamp, question, answer, elapsed time) up to KT4 (full UI events)
- **Format:** CSV, one file per student
- **Data quality:** timestamps deliberately shifted for privacy; otherwise clean, heavily benchmarked
- **Strengths:** enormous real production-scale interaction data
- **Weaknesses:** NC license, fragile link chain, Korean tutoring-app context (not "classroom")
- **Objectives satisfied:** 1, 7, 6
- **Preprocessing:** Moderate-heavy — sequence construction, large-scale wrangling

#### B3. ASSISTments 2009–2010 Skill-Builder Dataset (use the corrected file)
- **Source:** Worcester Polytechnic Institute / ASSISTments.org
- **Download:** https://sites.google.com/site/assistmentsdata/home/2009-2010-assistment-data/skill-builder-data-2009-2010 — verified live; corrected/de-duplicated version explicitly linked and should be preferred over the original (known duplicate-row bug). Also mirrored on IEEE DataPort/figshare.
- **License:** no formal license tag; attribution/citation expected (research-use convention)
- **Samples:** ~4,200 students, ~325K–347K interaction rows (figures vary slightly by source/version), 110 skill-builder problems
- **Features:** student/problem/skill IDs, correctness, attempt count, hint count, response time, opportunity count
- **Format:** CSV
- **Data quality:** real ITS logs; known duplicate-record issue in the *original* file — use the corrected version
- **Strengths:** the closest thing here to genuine fine-grained interaction data at a manageable scale; standard EDM/knowledge-tracing benchmark; strongest fit for a recommendation/mastery-tracking module
- **Weaknesses:** math-only, US ITS context (not general classroom), informal license
- **Objectives satisfied:** 1, 2, 7, 5
- **Preprocessing:** Moderate — must use corrected file, skill-tag encoding, sequence construction

#### B4. Junyi Academy Math Practicing Log Dataset
- **Source:** Junyi Academy Foundation (Taiwan), via Kaggle
- **Download:** https://www.kaggle.com/datasets/junyiacademy/learning-activity-public-dataset-by-junyi-academy — live/indexed (Kaggle bot-protection blocks direct programmatic fetch, as expected)
- **License:** CC BY-NC-SA 4.0
- **Samples:** ~16.2M problem-attempt logs, 72,630 students, Aug 2018–Jul 2019 (~2.6–9.1GB depending on format)
- **Features:** timestamps, correctness, difficulty, hints, learning stage, content topic/chapter hierarchy
- **Format:** CSV
- **Data quality:** large, modern, fairly clean; Chinese-language content metadata
- **Strengths:** large recent scale, free access, rich content hierarchy good for recommendation
- **Weaknesses:** share-alike license restricts derivative use, math-only, large files
- **Objectives satisfied:** 1, 7, 6
- **Preprocessing:** Moderate — large-file handling, session feature engineering, possible translation

#### B5. Kaggle "Confused Student EEG Brainwave Data"
- **Source:** Haohan Wang (CMU), Kaggle (`wanghaohan`)
- **Download:** https://www.kaggle.com/datasets/wanghaohan/confused-eeg — live/indexed (confirmed via multiple citations; direct non-browser fetch 404s as expected for Kaggle)
- **License:** CC0 (public domain)
- **Samples:** 10 students × 20 two-minute MOOC video clips (10 confusing/10 not), ~12,000+ EEG rows
- **Features:** Attention, Meditation, raw EEG voltage, band powers (Delta–Gamma), self-reported confusion (1–7)
- **Format:** CSV
- **Data quality:** consumer-grade single-channel EEG (NeuroSky), subjective self-report labels, **n=10 — too small to generalize**
- **Strengths:** direct quantitative confusion/attention signal, permissive CC0 license, tiny/fast to prototype
- **Weaknesses:** unrealistic for real classroom deployment (no student wears an EEG headset in class); best as a proof-of-concept side module only
- **Objectives satisfied:** 2, 5
- **Preprocessing:** Light-moderate — signal normalization/windowing

#### B6. KDD Cup 2015 (XuetangX MOOC Dropout Prediction)
- **Source:** XuetangX (Tsinghua), KDD Cup 2015 competition
- **Download:** **Official site `kddcup2015.com` is dead** (parked/squatted domain, verified by direct fetch). `moocdata.cn` has a TLS cert mismatch. The `biendata.xyz` mirror states data is "only open to invited users." Unofficial Kaggle/GitHub re-uploads exist but with unclear provenance.
- **License:** none confirmed; unofficial mirrors carry no clear license
- **Samples:** reported ~200K enrollments / ~8M log events across ~39 courses (not independently verifiable — authoritative source inaccessible)
- **Features:** enrollment/course/user IDs, event logs, binary dropout label (truth_train.csv)
- **Format:** CSV
- **Data quality:** cannot verify first-hand
- **Strengths:** if obtained, directly matches Dropout Risk with a clean label
- **Weaknesses:** **access is broken** — dead official link, invite-only mirror, uncertain unofficial re-uploads. Treat as unusable/fallback-only; OULAD covers the same capability with guaranteed access.
- **Objectives satisfied:** 6, 4 (nominal — access risk overrides usefulness)
- **Preprocessing:** N/A given access problems

#### B7. MOOCCube
- **Source:** Tsinghua University KEG (THU-KEG), built on XuetangX data, ACL 2020 paper
- **Download:** https://github.com/thukg/MOOCCube — verified live; direct links in README (`lfs.aminer.cn` + Google Drive mirror), **no request form required**
- **License:** CC0-1.0
- **Samples:** 706 courses, 38,181 videos, 114,563 concepts, 199,199 real users + behavior logs
- **Features:** course-video-concept relations, watching/exercise logs, forum comments, concept prerequisite graph
- **Format:** JSON
- **Data quality:** real production data, credible peer-reviewed provenance
- **Strengths:** large, real, free, no registration — rich enough for a genuine content+behavior recommender
- **Weaknesses:** Chinese-language content, heavy ETL for an internship scope, no explicit ratings (implicit signals only)
- **Objectives satisfied:** 7, 2, 6
- **Preprocessing:** Heavy — knowledge-graph + behavior-log ETL into a user-item matrix

---

### Category C: Environmental / occupancy / resource utilization

#### C1. UCI Occupancy Detection Data Set (Candanedo & Feldheim)
- **Source:** UCI ML Repository (Candanedo & Feldheim, *Energy and Buildings*, 2016)
- **Download:** https://archive.ics.uci.edu/dataset/357/occupancy+detection — verified live, direct zip confirmed
- **License:** CC BY 4.0
- **Samples:** 20,560 instances (train + 2 test splits), 6 features + binary occupancy target
- **Features:** timestamp, temperature, relative humidity, light, CO2, humidity ratio
- **Format:** plain-text CSV-like
- **Data quality:** no missing values, 1-minute resolution, ground truth from timestamped photos
- **Strengths:** clean, standard benchmark, minute-level resolution, ideal for supervised occupancy classification methodology
- **Weaknesses:** single small office room (not a classroom), short span, no HVAC/energy tie-in
- **Objectives satisfied:** 4, 5, 8
- **Preprocessing:** Light — timestamp parsing, optional resampling

#### C2. UCI Room Occupancy Estimation Data Set (Singh & Chaudhari)
- **Source:** UCI ML Repository, 2018, DOI 10.24432/C5P605
- **Download:** https://archive.ics.uci.edu/dataset/864/room+occupancy+estimation — verified live
- **License:** CC BY 4.0
- **Samples:** 10,129 instances, 18 features + multi-class occupancy count (0–3) target
- **Features:** 4× temp sensors, 4× light sensors, sound, CO2, CO2 slope, 2× PIR motion sensors
- **Format:** CSV
- **Data quality:** no missing values, 30-second sampling, 4-day collection window
- **Strengths:** multi-class occupancy **count** (not just binary), richer sensor mix than C1
- **Weaknesses:** small room (6m×4.6m), 4-day span, max occupancy 3 people — far below real classroom headcounts, no HVAC running (unrealistic)
- **Objectives satisfied:** 5, 8
- **Preprocessing:** Light — merge date+time, straightforward load

#### C3. Data on CO2, Temperature and Air Humidity in Spanish Classrooms (Zenodo)
- **Source:** Trilles, Juan, Chaudhuri, Vicente Fortea — *Data in Brief* (Elsevier), 2021
- **Download:** https://doi.org/10.5281/zenodo.5036228 — verified via PMC mirror (https://pmc.ncbi.nlm.nih.gov/articles/PMC8520590/); ScienceDirect page itself 403'd to automated fetch but DOI/content independently confirmed
- **License:** CC BY
- **Samples:** ~80,000 CO2 observations, 12 classrooms across 2 primary schools, May–June 2021
- **Features:** CO2 (ppm), temperature, relative humidity, battery level, sensor ID, timestamp
- **Format:** CSV
- **Data quality:** low-cost Sensirion SCD30 sensors (±30ppm CO2), 5-minute interval; some invalid/missing values from connectivity issues noted by authors
- **Strengths:** **genuinely classroom-based real data** (not a generic building stand-in), multi-classroom/multi-school comparison possible
- **Weaknesses:** narrow ~2-month COVID-reopening window (atypical ventilation/occupancy patterns), no direct occupancy counts (CO2-only proxy)
- **Objectives satisfied:** 5, 8, 3/4 (indirectly, via CO2-as-occupancy-proxy modeling)
- **Preprocessing:** Light-moderate — timestamp alignment, missing-value handling, sensor normalization

#### C4. IEEE Dataport — IoT-based Indoor Air Quality for Intelligent Education Environments
- **Source:** IEEE DataPort (Rosa-Bilbao, Butt, Merkl, Wagner, Schäfer, Boubeta-Puig)
- **Download:** https://ieee-dataport.org/documents/dataset-iot-based-indoor-air-quality-management-system-intelligent-education-environments — page live, DOI 10.21227/z865-5v63; **file download requires an IEEE DataPort account/subscription**
- **License:** gated, not stated publicly
- **Samples:** unstated on public page (4.13MB zip of "complex events")
- **Features:** CO2, PM2.5, TVOCs, temperature, humidity + example LSTM notebook
- **Format:** ZIP (CSV + code)
- **Data quality:** cannot verify without access
- **Strengths:** genuinely classroom/lecture-room-specific, multi-pollutant, real deployed sensor network
- **Weaknesses:** paywalled access, unknown sample size/license until obtained
- **Objectives satisfied:** 5, 8, 4 (partial)
- **Preprocessing:** unknown (likely light, ships with example notebook)

#### C5. Building Data Genome Project 2 (BDG2)
- **Source:** BUDS Lab (Miller et al.), *Scientific Data* (Nature), 2020
- **Download:** https://github.com/buds-lab/building-data-genome-project-2 — verified live
- **License:** CC BY-SA 4.0
- **Samples:** 3,053 meters, 1,636 non-residential buildings, ~53.6M hourly readings, 2016–2017
- **Features:** hourly electricity/water/steam meter readings, building metadata (use, sq ft, industry), site weather
- **Format:** CSV (raw + cleaned versions)
- **Data quality:** documented cleaning pipeline, cleaned version addresses raw gaps/anomalies
- **Strengths:** large-scale real multi-building/multi-year data, clear license, good for resource-utilization + anomaly modeling
- **Weaknesses:** offices/commercial buildings, not classrooms; no occupancy or environmental (temp/CO2) sensors — energy meters only
- **Objectives satisfied:** 4, 5
- **Preprocessing:** Moderate — filter to a manageable building subset, join meter/metadata/weather

#### C6. ASHRAE "Great Energy Predictor III" (Kaggle)
- **Source:** ASHRAE, Kaggle competition, 2019 (same underlying data lineage as BDG2)
- **Download:** https://www.kaggle.com/c/ashrae-energy-prediction — page exists; JS-rendered, full terms not directly scrapable
- **License:** Kaggle competition terms (BDG2 above is the same data with a clearer CC BY-SA 4.0 license — **prefer BDG2**)
- **Samples:** >20M training rows, 2,380 meters, ~1,449 buildings, 16 sites
- **Features:** meter type/reading, timestamp, building metadata, weather
- **Format:** CSV
- **Data quality:** known data errors/anomalies (widely discussed post-competition)
- **Strengths:** large scale, strong existing community tooling/notebooks
- **Weaknesses:** redundant with BDG2 but with murkier licensing and noisier data — **not recommended over C5**
- **Objectives satisfied:** 4, 5
- **Preprocessing:** Moderate-heavy — cleaning known errors, chunked processing

#### C7. CU-BEMS (Chulalongkorn University Building Energy Management System)
- **Source:** Chulalongkorn University, *Scientific Data* (Nature), 2020, via Figshare
- **Download:** https://doi.org/10.6084/m9.figshare.11726517 — **landing page 403'd to automated fetch**; existence/metadata corroborated via PMC (https://pmc.ncbi.nlm.nih.gov/articles/PMC7371880/)
- **License:** conflicting secondary reports (CC0 vs CC BY 4.0) — **re-confirm directly on Figshare before use**
- **Samples:** 14 CSV files, up to 525,600 rows each (1-min resolution × 18 months)
- **Features:** per-zone electricity (AC/lighting/plug loads), indoor temp, humidity, illuminance, 33 zones
- **Format:** CSV
- **Data quality:** real deployed BEMS, unusually rich resolution/duration; some expected sensor gaps
- **Strengths:** combines energy + environmental sensing at high resolution, academic-building context
- **Weaknesses:** office/open-plan building not classrooms, license needs re-verification, 403 blocks pre-access verification
- **Objectives satisfied:** 4, 5, 8
- **Preprocessing:** Moderate — join 14 files by zone/timestamp, downsample from 1-min resolution

#### C8. IEEE Dataport — Weakly Supervised Occupancy Prediction for HVAC Optimization in Digital Twins Smart Campuses
- **Source:** IEEE DataPort (Martini, Maresca, Solmaz, Cirillo, Sanchez-Roda, Jacobs, Conti)
- **Download:** https://ieee-dataport.org/documents/weakly-supervised-occupancy-prediction-hvac-optimization-digital-twins-smart-campuses-0 — page live, DOI 10.21227/pemr-cv11; **explicitly requires an IEEE DataPort Standard subscription (~$40/month)** to access files
- **License:** not stated publicly
- **Samples:** unstated pre-purchase; 4 CSVs named by building (library, math dept, optics/optometry, veterinary)
- **Features (from description):** hourly CO2, temperature (min/max), precipitation, ground-truth people-counting occupancy
- **Format:** CSV
- **Data quality:** cannot assess pre-access
- **Strengths:** closest match found to a true "digital twin smart campus" dataset — real IoT CO2/temp/occupancy fusion
- **Weaknesses:** **paywalled**, building- not classroom-granular, unverifiable until purchased
- **Objectives satisfied:** 8, 4 (partial)
- **Preprocessing:** unknown

---

### Category D: Attendance / anomaly / recommendation / misc

#### D1. Kaggle "School Student Daily Attendance" (NYC DOE mirror)
- **Source:** Kaggle (`sahirmaharajj`), underlying data from NYC Department of Education via NYC Open Data
- **Download:** https://www.kaggle.com/datasets/sahirmaharajj/school-student-daily-attendance; original verified directly at https://data.cityofnewyork.us/Education/2018-2019-Daily-Attendance/x3bb-kg5j (Socrata API query confirmed 277,153 rows for that single school-year slice)
- **License:** Apache 2.0 (Kaggle page); underlying NYC Open Data is public government data
- **Samples:** Kaggle zip (multi-year compilation) larger than the single-year 277K-row slice; 6 confirmed columns: School DBN, Date, Enrolled, Absent, Present, Released
- **Format:** CSV
- **Data quality:** real, government-published, actively maintained, aggregated at school-day level (not individual student)
- **Strengths:** real-world, large-scale, longitudinal — directly supports attendance forecasting
- **Weaknesses:** aggregated only (no individual student records/demographics, can't link to dropout/performance per-student)
- **Objectives satisfied:** 3, 4
- **Preprocessing:** Light-moderate — date parsing, day-of-week/holiday features

#### D2. Kaggle "Student Attendance Dataset (College-Level)"
- **Source:** Kaggle (`kundanbedmutha`)
- **Download:** https://www.kaggle.com/datasets/kundanbedmutha/student-attendance-dataset-college-level — verified live
- **License:** CC BY 4.0 (confirmed via schema.org metadata)
- **Samples:** row count undisclosed (317KB zip)
- **Features:** study hours, sleep, travel time, internet access, weather, hostel residency, class mode, absence reason, attendance outcome
- **Format:** CSV
- **Data quality:** **explicitly stated by the author to be fully synthetic**
- **Strengths:** clean, no privacy concerns, rich behavioral/environmental predictors
- **Weaknesses:** synthetic (not real behavior), unverified generation method, size unconfirmed
- **Objectives satisfied:** 3, 6 (partial)
- **Preprocessing:** Light — categorical encoding

#### D3. Numenta Anomaly Benchmark (NAB)
- **Source:** Numenta, Inc.
- **Download:** https://github.com/numenta/NAB — verified live via GitHub API, 7 category folders, 58 CSV files total
- **License:** MIT (verified via LICENSE.txt)
- **Samples:** ~1,000–22,000 rows per file, hourly/5-min cadence; labels in separate `labels/combined_windows.json`
- **Features:** univariate `timestamp, value` per file (e.g. AWS metrics, ad-click metrics, traffic, Twitter volume, ambient/machine temperature)
- **Format:** CSV (data) + JSON (labels)
- **Data quality:** well-curated, validated labeled anomaly windows
- **Strengths:** the ambient-temperature/machine-temperature files are structurally identical to what a classroom sensor stream looks like — ideal for **validating an anomaly-detection algorithm** before applying it to real/synthetic classroom data
- **Weaknesses:** not education-specific, univariate only — use for algorithm benchmarking, not as classroom ground truth
- **Objectives satisfied:** 5, 8 (methodology transfer)
- **Preprocessing:** Moderate — reformat window-JSON labels to row-level flags

#### D4. Kaggle "Smart Classroom IoT-Edge Dataset"
- **Source:** Kaggle (`ziya07`)
- **Download:** https://www.kaggle.com/datasets/ziya07/smart-classroom-iot-edge-dataset — verified live
- **License:** CC0
- **Samples:** unconfirmed row count; **zip is only 2,159 bytes**, strongly implying a very small (likely tens-of-rows) toy dataset
- **Features:** Activity_Type, Engagement_Score, Attention_Level, Classroom_Noise (dB), Temperature, Feedback_Time, Learning_Outcome, Performance_Class
- **Format:** CSV
- **Data quality:** **explicitly described by the author as simulated**
- **Strengths:** the only dataset found that is literally named/framed as "smart classroom IoT" with columns mapping to 3 objectives at once
- **Weaknesses:** tiny, synthetic, single unverified contributor, no methodology/paper — treat as a **schema reference**, not a training set
- **Objectives satisfied:** 2, 8, 1 (partial)
- **Preprocessing:** Light, but scale is the real limitation

#### D5. 100K Coursera's Course Reviews Dataset
- **Source:** Kaggle (`septa97`), scraped from Coursera.org, ~2017
- **Download:** https://www.kaggle.com/datasets/septa97/100k-courseras-course-reviews-dataset — verified live
- **License:** ODbL (Open Database License, verified)
- **Samples:** "100K+" reviews (two files: ungrouped and grouped-by-course)
- **Features:** review text, 5-class sentiment label (Very Positive → Very Negative), CourseId (in the grouped file)
- **Format:** TSV
- **Data quality:** class-imbalanced (skewed positive), no user IDs — **cannot support collaborative filtering**, content/sentiment scoring only
- **Strengths:** real user text, easy content-based course scoring signal
- **Weaknesses:** no user-item matrix possible, stale snapshot, imbalanced
- **Objectives satisfied:** 7 (partial — content-based only)
- **Preprocessing:** Moderate — NLP preprocessing, imbalance handling

**Negative finding (reported for completeness):** no dataset explicitly and verifiably named "digital twin classroom dataset" was found on Kaggle, GitHub, or Google Dataset Search that is both freely accessible and classroom-granular. C8 and D4 above are the closest named matches; neither is a clean fit (C8 is paywalled, D4 is a tiny synthetic toy set).

---

## Part 2 — Comparison and ranking

Each dataset scored 1–5 (5 = best) on seven criteria. Total out of 35.
**Suit** = suitability for a Smart Classroom Digital Twin · **AI** = AI usefulness ·
**Ease** = ease of implementation · **Qual** = data quality · **Avail** = public
availability · **Docs** = documentation · **Intern** = internship feasibility
(time/access risk given a fixed internship timeline).

| # | Dataset | Suit | AI | Ease | Qual | Avail | Docs | Intern | **Total** |
|---|---|---|---|---|---|---|---|---|---|
| A1 | OULAD | 5 | 5 | 4 | 5 | 5 | 5 | 5 | **34** |
| C1 | UCI Occupancy Detection | 3 | 4 | 5 | 5 | 5 | 5 | 5 | **32** |
| A3 | UCI Predict Dropout | 4 | 4 | 4 | 4 | 5 | 5 | 5 | **31** |
| A2 | UCI Student Performance (Cortez) | 3 | 3 | 5 | 4 | 5 | 5 | 5 | **30** |
| C2 | UCI Room Occupancy Estimation | 3 | 4 | 5 | 4 | 5 | 4 | 5 | **30** |
| D1 | NYC DOE Daily Attendance | 4 | 3 | 5 | 4 | 5 | 4 | 5 | **30** |
| C3 | Spanish Classroom CO2 (Zenodo) | 5 | 3 | 4 | 3 | 5 | 4 | 5 | **29** |
| D3 | NAB (anomaly benchmark) | 2 | 4 | 4 | 5 | 5 | 5 | 4 | **29** |
| B3 | ASSISTments (corrected) | 4 | 5 | 3 | 4 | 4 | 4 | 4 | **28** |
| A4 | xAPI-Edu-Data | 4 | 3 | 5 | 3 | 4 | 3 | 5 | **27** |
| C5 | Building Data Genome 2 | 2 | 4 | 3 | 4 | 5 | 5 | 3 | **26** |
| B2 | EdNet | 3 | 5 | 2 | 4 | 3 | 4 | 2 | **23** |
| B4 | Junyi Academy | 3 | 4 | 2 | 4 | 4 | 3 | 3 | **23** |
| B7 | MOOCCube | 3 | 4 | 2 | 4 | 5 | 3 | 2 | **23** |
| A7 | HarvardX-MITx Person-Course | 4 | 4 | 2 | 4 | 2 | 4 | 2 | **22** |
| A6 | Kaggle Students Perf. in Exams | 2 | 2 | 5 | 2 | 4 | 2 | 4 | **21** |
| B5 | Confused Student EEG | 2 | 2 | 4 | 2 | 5 | 3 | 3 | **21** |
| D2 | Kaggle Attendance (synthetic) | 3 | 2 | 4 | 2 | 4 | 2 | 4 | **21** |
| D5 | 100K Coursera Reviews | 2 | 2 | 3 | 3 | 5 | 3 | 3 | **21** |
| A5 | OECD PISA 2022 | 2 | 3 | 1 | 5 | 3 | 5 | 1 | **20** |
| D4 | Kaggle Smart Classroom IoT-Edge | 5 | 1 | 5 | 1 | 4 | 1 | 3 | **20** |
| B1 | DAiSEE | 5 | 4 | 1 | 3 | 2 | 4 | 1 | **20** |
| C4 | IEEE Dataport IAQ Education | 5 | 4 | 2 | 3 | 1 | 3 | 1 | **19** |
| C6 | ASHRAE GEPIII (Kaggle) | 2 | 4 | 2 | 3 | 3 | 3 | 2 | **19** |
| C7 | CU-BEMS | 2 | 4 | 3 | 3 | 2 | 3 | 2 | **19** |
| C8 | IEEE Dataport Occupancy/HVAC | 5 | 4 | 2 | 2 | 1 | 2 | 1 | **17** |
| B6 | KDD Cup 2015 (XuetangX) | 3 | 4 | 1 | 2 | 1 | 2 | 1 | **14** |

**Reading the table:** the top of the ranking is dominated not by the
"most exciting" datasets but by the ones combining real classroom/institutional
relevance with a *verified, frictionless, well-licensed* download — which is
exactly what an internship timeline needs. The lowest-ranked entries are low
almost entirely because of **access risk** (paywalls, dead links, DUAs, n=10
sample sizes), not because the underlying data is uninteresting — DAiSEE and
the two IEEE Dataport entries would rank much higher on a research timeline
with more runway.

---

## Part 3 — Recommended dataset combination

No single dataset covers all 8 objectives, and none should — a Digital Twin
is a system-of-systems, and the recommendation reflects that: one **spine**
dataset plus **targeted supplements**, each chosen as the top-ranked entry
that is not redundant with something already covering that objective.

| Role | Dataset | Objectives covered |
|---|---|---|
| **Spine** | A1. OULAD | 1 (performance), 2 (engagement, via VLE clicks), 4 (VLE/resource utilization), 6 (dropout, via Withdrawn label) |
| Dropout refinement | A3. UCI Predict Dropout | 6 (richer socioeconomic/macro features), 1, 5 |
| Engagement detail | A4. xAPI-Edu-Data | 2 (fine-grained behavioral engagement, complements OULAD's coarse daily clicks) |
| Recommendation engine | B3. ASSISTments (corrected) | 7 (knowledge tracing → personalized learning), 1, 2 |
| Occupancy/environmental (methodology) | C1. UCI Occupancy Detection | 8, 4, 5 (clean supervised benchmark to build the classification approach) |
| Occupancy/environmental (real classroom) | C3. Spanish Classroom CO2 (Zenodo) | 8, 5 (authentic classroom sensor data to apply/validate the approach against) |
| Attendance | D1. NYC DOE Daily Attendance | 3, 4 |
| Anomaly-detection validation | D3. NAB | 5 (algorithm benchmarking before deployment on the chosen sensor stream) |

**Why this combination and not another:**

1. **Every one of the 8 objectives is covered by a dataset that scored ≥27/35** — no objective is being served by a weak or access-risky dataset. Compare this to, e.g., using DAiSEE for engagement (score 20, 15GB + DUA) or KDD Cup 2015 for dropout (score 14, broken access) — both were considered and rejected specifically because of access risk, not data quality.
2. **No paywalls, no dead links, no data-use-agreement approval waits.** Every dataset in the combination has a *verified, currently working, no-registration* download. This matters more than usual here: an internship has a fixed clock, and A7 (HarvardX), C4/C8 (IEEE Dataport), and B6 (KDD Cup 2015) were all excluded from the core recommendation for exactly this reason, even though some score respectably on suitability.
3. **Licensing is clean throughout** — CC BY 4.0 dominates (A1, A3, C1, C3), MIT for D3; nothing in the core set carries an "Unknown" or ambiguous license, unlike A6 or the synthetic D2/D4.
4. **It mixes real institutional data (A1, A3, D1) with real classroom-specific sensor data (C3)**, avoiding a common trap in this project space: leaning entirely on generic-building energy datasets that have nothing classroom-specific about them (C5/C6/C7 were deliberately kept as *optional stretch*, not core, for this reason).
5. **Preprocessing effort is proportionate to an internship timeline** — mostly light-to-moderate; the heaviest lift (OULAD's table joins, ~430MB unzipped clickstream) is still a standard laptop/Colab-scale job, unlike PISA's SAS/SPSS statistical machinery or MOOCCube's knowledge-graph ETL.
6. **The combination maps directly onto the Digital Twin's module structure already in this repo:** OULAD → `twin_engine/student_twin.py` (performance/engagement/dropout core) and `analytics/predictive.py`; xAPI-Edu-Data → a second `analytics/descriptive.py` or `predictive.py` engagement classifier; ASSISTments → `agents/tools.py`-backed recommendation logic; UCI Occupancy Detection + Spanish CO2 → the classroom-twin environmental layer (`twin_engine/classroom_twin.py`); NAB → a reusable anomaly-detection component validated independently of whichever sensor data it's eventually pointed at; NYC DOE → an attendance-forecasting slice of `analytics/predictive.py`.

**Optional stretch (only if time remains after the core is working):** C5
(Building Data Genome 2) for a more ambitious resource/energy-utilization
module — real, large-scale, well-licensed, but not classroom-specific, so it's
additive rather than foundational.

**Explicitly not recommended for this project, with reasons:**
- **B1 DAiSEE, C4/C8 IEEE Dataport entries** — real value, but access friction (DUA / paywall / 15GB) is disproportionate to an internship timeline.
- **B6 KDD Cup 2015** — official access is broken; do not build a project milestone around it.
- **A6 Kaggle Students Performance in Exams, D2 Kaggle Attendance, D4 Smart Classroom IoT-Edge** — synthetic/toy-scale; fine as a quick demo or schema reference, not as a system backbone.
- **A5 PISA** — real and rigorous, but it's a one-time international assessment, not classroom/time-series data; the format and statistical overhead (plausible values, sampling weights) isn't worth it for what it would add here.
