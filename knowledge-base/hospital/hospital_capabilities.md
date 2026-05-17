# Hospital Capability Registry — Seattle / King County Metro
## Category: Hospital | Audience: 911 Dispatcher | Region: Seattle, WA

---

## Quick Reference — When to Choose Which Hospital

| Condition | Best Hospital |
|-----------|--------------|
| Major trauma / penetrating injury | Harborview Medical Center |
| Burns (any significant) | Harborview Medical Center — only burn center in WA |
| Cardiac (STEMI / cath lab needed) | Harborview, UW Medical Center, or Swedish First Hill |
| Stroke — acute | Harborview or UW Medical Center |
| Pediatric emergency | Seattle Children's Hospital |
| Psychiatric crisis | Harborview (psychiatric ED), or UW Medical Center |
| Obstetric / high-risk delivery | UW Medical Center or Swedish First Hill |
| Spinal cord injury | Harborview |
| Multiple trauma victims (MCI) | Distribute: Harborview + UW + Swedish |
| East side / Bellevue / Redmond | Overlake Medical Center (Bellevue) |
| Everett / North King County | Providence Regional Medical Center |

---

## Hospital Records

### H001 — Harborview Medical Center
- **Trauma Level:** 1 (Level 1 for WA, AK, ID, MT — 5-state region)
- **Location:** 325 9th Ave, Seattle, WA 98104
- **Coordinates:** 47.6027, -122.3209
- **Neighborhood:** First Hill / Capitol Hill
- **ER Status:** Accepting
- **Average Drive from Downtown Seattle:** 5 minutes
- **Capabilities:** trauma_bay, icu, burn_unit, cardiac_cath, stroke_team, psychiatric, spinal
- **Trauma Bays:** 10 total
- **Notes:** Only Level 1 trauma center for the entire Pacific Northwest. Only regional burn center in WA state. 24/7 neurosurgery and cardiac cath. All major trauma should go here when possible.

### H002 — UW Medical Center (Montlake)
- **Trauma Level:** 2
- **Location:** 1959 NE Pacific St, Seattle, WA 98195
- **Neighborhood:** University District
- **Coordinates:** 47.6498, -122.3072
- **ER Status:** Accepting
- **Average Drive from Downtown Seattle:** 10 minutes
- **Capabilities:** trauma_bay, icu, cardiac_cath, stroke_team, neonatal
- **Trauma Bays:** 8 total
- **Notes:** Major academic medical center. Level 2 trauma. Strong cardiac and neuro. NICU for high-risk newborns. When Harborview is overwhelmed, UW is primary overflow for serious trauma.

### H003 — Swedish Medical Center — First Hill
- **Trauma Level:** 2
- **Location:** 747 Broadway, Seattle, WA 98122
- **Neighborhood:** First Hill
- **Coordinates:** 47.6085, -122.3218
- **ER Status:** Accepting
- **Average Drive from Downtown Seattle:** 6 minutes
- **Capabilities:** trauma_bay, icu, cardiac_cath, stroke_team, neonatal
- **Trauma Bays:** 6 total
- **Notes:** Strong cardiac surgery and cath lab. Good choice for chest pain / cardiac calls when Harborview is at capacity. Stroke team 24/7.

### H004 — Seattle Children's Hospital
- **Trauma Level:** 1 (Pediatric only)
- **Location:** 4800 Sand Point Way NE, Seattle, WA 98105
- **Neighborhood:** Laurelhurst
- **Coordinates:** 47.6632, -122.2973
- **ER Status:** Accepting
- **Average Drive from Downtown Seattle:** 15 minutes
- **Capabilities:** pediatric_er, pediatric_icu, neonatal, pediatric_trauma, pediatric_burn
- **Notes:** All pediatric emergencies (under 18) should go here unless patient is too unstable to bypass Harborview. Best pediatric cardiac, neuro, and cancer care in region.

### H005 — Overlake Medical Center
- **Trauma Level:** 3
- **Location:** 1035 116th Ave NE, Bellevue, WA 98004
- **Neighborhood:** Downtown Bellevue
- **Coordinates:** 47.6138, -122.1969
- **ER Status:** Accepting
- **Average Drive from Bellevue/Redmond:** 8 minutes
- **Capabilities:** trauma_bay, icu, cardiac_cath, stroke_team
- **Notes:** Primary hospital for Eastside (Bellevue, Redmond, Kirkland, Issaquah). Level 3 trauma — stabilize and transfer to Harborview for complex trauma. Good cardiac care for East King County calls.

---

## Hospital Capacity Thresholds

| Capacity Ratio | Status | Dispatcher Action |
|----------------|--------|-------------------|
| < 60% full | Accepting | Normal pre-alert |
| 60–85% full | Preparing | Add 2–3 min setup note to pre-alert |
| > 85% full | Redirected | Route to next qualified hospital |
| 100% | Divert | Do NOT send — use alternate |

---

## Pre-Alert Information to Include

- Patient age and sex
- Chief complaint / suspected diagnosis
- Estimated vitals if available from caller
- ETA in minutes from current unit location
- Resources likely needed (trauma bay, burn unit, cath lab, pediatric, psychiatric hold)
- ALS or BLS unit responding

---

## Regional Overflow — If Multiple Seattle Hospitals at Capacity

| Hospital | Distance from Seattle | Trauma Level |
|----------|-----------------------|--------------|
| Providence Regional Medical Center, Everett | 25 miles north | 2 |
| Valley Medical Center, Renton | 12 miles south | 2 |
| MultiCare Auburn Medical Center | 20 miles south | 2 |
| St. Francis Hospital, Federal Way | 25 miles south | 2 |

Activate Regional Mutual Aid when: Harborview + UW both diverting, or MCI with 10+ patients.
