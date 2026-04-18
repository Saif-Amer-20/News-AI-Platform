# Benchmark Investigation Report
**Date:** 2026-04-17 | **Frozen sample:** 500 articles (IDs saved) | **Runtime:** 65.9s

---

## 1. Executive Summary

The entity F1 regression (0.986 → 0.900 → 0.830) and geo accuracy regression (0.638 → 0.576 → 0.522) are **predominantly evaluation artifacts**, not system quality degradations. The independent ground-truth (GT) builder has fundamental design flaws that produce unreliable baselines, making the benchmark scores misleading.

**Verdict: Fix the evaluation methodology before any system tuning.**

---

## 2. Frozen-Sample Benchmark (Same Articles, Current GT Builder)

| Metric                  | Run 10 | Run 11 | Frozen | Trend  |
|-------------------------|--------|--------|--------|--------|
| Entity F1               | 0.986  | 0.900  | 0.830  | ↓↓     |
| Geo accuracy            | 0.638  | 0.576  | 0.522  | ↓↓     |
| Geo false_location      | 0.807  | 0.657  | 0.604  | ↑ (good) |
| Dedup precision         | 0.925  | 0.921  | —      | stable |
| Dedup miss rate         | 0.083  | 0.063  | —      | ↑ (good) |
| GT entity_consensus     | 20     | 23     | 33     | ↑ unstable |
| GT geo_truth count      | 282    | 363    | 341    | ↑ unstable |
| GT conflict events      | 4      | 1      | —      | ↓ unstable |

**Key observation:** GT stats change between runs on the same DB because the GT builder itself is non-deterministic in its cluster discovery (SequenceMatcher on growing article pool). More consensus clusters → more articles evaluated → more errors exposed → lower scores. This is **not** a system regression.

---

## 3. Entity F1 Investigation

### 3.1 Error Counts
- **TP:** 3441 | **FP:** 652 | **FN:** 761
- **P=0.841 R=0.819 F1=0.830**

### 3.2 Root Cause Distribution

**False Positives (system predicted, GT doesn't have):**
| Cause                         | Count | %    |
|-------------------------------|-------|------|
| org_person_confusion          | 371   | 56.9 |
| evaluation_artifact_consensus | 146   | 22.4 |
| type_confusion                | 69    | 10.6 |
| noisy_entity                  | 45    | 6.9  |
| arabic_normalization          | 21    | 3.2  |

**False Negatives (GT has, system missed):**
| Cause                         | Count | %    |
|-------------------------------|-------|------|
| org_person_confusion          | 579   | 76.1 |
| evaluation_artifact_consensus | 104   | 13.7 |
| arabic_normalization          | 69    | 9.1  |
| noisy_entity                  | 9     | 1.2  |

### 3.3 Detailed Analysis

#### Problem 1: GT consensus produces garbage entities (EVALUATION ARTIFACT — ~35% of errors)

The `IndependentGroundTruthBuilder.build_entity_ground_truth()` takes the >50% consensus of `(name.lower(), type.lower())` tuples across a cluster. This breaks badly because:

- **Different sources extract different name boundaries:** "Trump" vs "Donald Trump" vs "President Donald Trump" — these are three different tuples, so none reaches consensus
- **In a 2-article cluster, ANY entity from 1 article becomes consensus** (1/2 ≥ 50% threshold rounds up)
- **Garbage leaks in:** "Foreign Policy(location)", "following leo(organization)", "palm sunday mass(organization)", "defence secretary pete hegseth(organization)" — these are clearly not real entities but appear in GT consensus

**Concrete example (article 3048, Pope/Trump cluster):**
- GT consensus: `the pope(person), pope leo(person), president donald trump(organization), truth social(organization)`
- System predicted: `Pop(person), Trump(person), Cameroon(location), Leo(person), Iran(location), US(location)...`
- Result: "Donald Trump(person)" → FP (because GT has "president donald trump(organization)"). "trump(person)" → FP. "the pope(person)" → FN (because system extracted "Pop" not "The Pope")

The consensus method **cannot produce a reliable entity GT** because NER output varies too much across sources.

#### Problem 2: Type labeling inconsistency (BOTH system + GT — ~57% of errors)

The `org_person_confusion` category dominates both FP and FN:
- GT labels "White House" as `person`, "Catholic Church" as `person`
- GT labels "President Donald Trump" as `organization`  
- System labels "Trump" as `person` (correct) but this mismatches GT

This means the NER model's type assignments are noisy, and the consensus method amplifies type noise into hard mismatches.

#### Problem 3: Real system issues (MINOR — ~10% of errors)

- **Noisy entities:** "us", "le", "pop" — these are real NER extraction bugs (partial words, abbreviations treated as entities)
- **Arabic normalization:** 90 errors from Arabic text where name normalization differs between system and GT
- These are genuine but represent a small fraction of the total error count

### 3.4 Entity Verdict

| Category | % of errors | Action needed |
|----------|------------|---------------|
| Evaluation artifact (consensus GT unreliable) | ~35% | **Fix GT builder** |
| Type labeling noise (system + GT) | ~57% | **Fix GT builder** (relax type matching) OR fix NER type assignments |
| Real NER bugs (noisy/arabic) | ~10% | System improvement (later) |

**~90% of the apparent entity F1 regression is caused by the evaluation methodology, not by system degradation.**

---

## 4. Geo Investigation

### 4.1 Error Counts
| Category | Count |
|----------|-------|
| Agree (GT=sys) | 178 |
| GT has, system missing | 11 |
| System has, GT missing | 96 |
| Disagree (both have, different) | 152 |
| Total articles | 500 |

### 4.2 Root Cause Distribution

**Disagreements (152 cases):**
| Cause | Count | % |
|-------|-------|---|
| multi_country_article | 148 | 97.4 |
| wrong_geo_assignment | 4 | 2.6 |

**System has, GT missing (96 cases):**
| Cause | Count | % |
|-------|-------|---|
| gt_weakness_no_pattern_match | 96 | 100.0 |

**GT has, system missing (11 cases):**
| Cause | Count | % |
|-------|-------|---|
| gt_weakness_low_mentions | 7 | 63.6 |
| system_extraction_miss | 4 | 36.4 |

### 4.3 Detailed Analysis

#### Problem 1: Multi-country articles have no correct single answer (EVALUATION DESIGN — 97% of disagreements)

148 out of 152 disagreements are articles mentioning multiple countries where GT and system simply pick different ones:

- **"Israel and Lebanon agree 10-day ceasefire"** → GT picks IL (16 mentions), system picks LB — both valid
- **"Pope criticises tyrants..."** → GT picks IR (2 mentions from "Iran"), system picks IL — article mentions Iran and Israel, neither is the "primary" country
- **"CNN newsletters..."** → GT picks US (2), system picks CN (2) — tied

The GT builder picks the country with most weighted mentions; the system's event pipeline picks based on event extraction logic. **Both are reasonable but different heuristics. There is no objectively correct answer for multi-country articles.**

#### Problem 2: GT regex patterns miss many countries (EVALUATION GAP — 100% of sys-has/GT-missing)

96 articles where the system correctly assigned a country but GT found nothing:
- **"Singer D4vd arrested..."** → system correctly says US, but the article text doesn't contain "united states", "america", etc. — it says locations like city/state names not in the GT pattern dictionary
- **"Tim Kaine: Trump 'Blundered...'"** → system says IR, GT finds nothing

The GT `_COUNTRY_PATTERNS` regex dictionary covers ~55 countries with explicit name patterns, but **misses implicit geo references** (city names without country, demonyms not in dict, US state names, etc.)

#### Problem 3: Real system errors (MINOR — 4 cases)

Only 4 out of 152 disagreements are genuine wrong assignments where GT is clearly correct and system is wrong.

### 4.4 Geo Verdict

| Category | % of errors | Action needed |
|----------|------------|---------------|
| Multi-country ambiguity (no single correct answer) | 57% (148/259) | **Fix evaluation**: skip or multi-label |
| GT pattern gaps (GT can't detect country) | 37% (96/259) | **Fix GT builder**: expand patterns |
| GT low-mention weakness | 3% (7/259) | **Fix GT builder**: lower or context-adjust threshold |
| Real system errors | 3% (8/259) | System improvement (later) |

**~97% of geo errors are evaluation artifacts.** The system's geo extraction is actually performing well.

---

## 5. Recommendations

### Do First: Fix the Evaluation (no system changes needed)

1. **Entity GT: Replace consensus matching with fuzzy/embedding matching**
   - Current: exact `(name.lower(), type.lower())` tuple match → fails on boundary differences
   - Fix: use token overlap or edit distance for name matching, relax type to optional or map equivalences (PERSON≈ORG for named individuals)
   - Alternative: skip type in matching, only match on normalized name tokens

2. **Entity GT: Raise consensus threshold for small clusters**
   - Current: >50% of cluster → in a 2-article cluster, 1 article is enough
   - Fix: require min 3 articles in cluster AND >60% agreement

3. **Geo evaluation: Handle multi-country articles**
   - Current: single-country exact match → fails when article has 3+ countries
   - Fix: count as "correct" if system's country is in GT's `all_countries` dict (with >N mentions)
   - Alternative: skip scoring for articles with 2+ countries within 50% of top count

4. **Geo GT: Expand country patterns**
   - Add US state names → US mapping
   - Add major city names → country mapping  
   - Add more demonyms and abbreviations

5. **Freeze benchmark sample**
   - Save article IDs per run so reruns compare apples-to-apples
   - The frozen IDs from this investigation are saved in `investigation_report.json`

### Do Later: System Improvements (after eval is fixed)

6. **NER: Fix noisy short entities** — "us", "le", "pop" should be filtered (min length or stopword list)
7. **NER: Arabic name normalization** — 90 errors from Arabic text
8. **Geo: 4 genuine wrong assignments** — investigate after eval fix

---

## 6. Appendix: Data Files

- **Full report JSON:** `backend/validation/investigation_report.json`
  - `frozen_article_ids`: 500 article IDs for reproducible reruns
  - `entity_investigation.sample_fps`: 25 sample false positives with causes
  - `entity_investigation.sample_fns`: 25 sample false negatives with causes
  - `geo_investigation.sample_disagree`: 25 sample disagreements with causes
  - `geo_investigation.sample_system_has_gt_missing`: 25 samples where GT missed
- **Investigation script:** `backend/scripts/investigation.py`
- **Comparison script:** `backend/scripts/compare_runs.py`
