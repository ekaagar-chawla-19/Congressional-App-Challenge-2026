<!-- Research report used for src/hemlock_sentinel/api/diseases.py. Items marked [UNVERIFIED] were not re-checked against the source; thresholds marked heuristic are engineering choices, not published standards. -->

# Eastern Hemlock Health Threats in North Georgia: Research Report for the Rules Engine

**Method and confidence.** I ran only two live web searches: HWA cold tolerance (USFS/MSU sources) and elongate hemlock scale ID (NC State, Penn State, UMass, Virginia Tech). Everything else comes from established extension and USFS literature I already knew, and I did not re-check it this session. Items marked **[UNVERIFIED]** should be checked against the cited source, especially product label rates, before they go into recommendation text.

---

## Ranking and justification
1. **Hemlock woolly adelgid (HWA), *Adelges tsugae*** (insect). Present in all North Georgia hemlock counties since about 2003 (Rabun was first). Untreated trees in the southern Appalachians often die in **4–10 years**, much faster than the 10–20+ years seen in the North, because mild winters allow two generations a year with little winter mortality.
2. **Elongate hemlock scale (EHS), *Fiorinia externa*** (insect). It is established in western NC and eastern TN (Lambdin et al. studies around Asheville and Knoxville) and is spreading in GA nurseries and landscapes. It often occurs alongside HWA. Imidacloprid does not control it well, and imidacloprid use can trigger scale outbreaks. It is the most common "second pest" that causes treated trees to keep declining.
3. **Drought / abiotic stress, plus secondary root rot (*Armillaria*) and borers** (abiotic, then fungal or insect). Hemlock is shallow-rooted and needs moisture. The 2007–08 and 2016 droughts in the southern Appalachians made HWA decline worse and caused mortality. Drought stress also lowers how much systemic insecticide the tree takes up. It ranks above the alternatives because it affects every tree and it is the one threat your sensors can actually measure.

Not top-3: Fabrella needle blight and other needle rusts (occasional, mostly cosmetic); hemlock looper (outbreaks are mostly northern); spruce spider mite (a landscape problem in hot, dry summers; worth a "mention" rule); hemlock borer (*Phaeno drillis fulvicornis*, secondary on stressed trees); Phytophthora (mostly on nursery and wet sites). **[Ranking of #2 vs #3 is judgment, not from a published ranked list.]**

---

## 1. Hemlock woolly adelgid

### 1.1 Basics and seasonality (southern Appalachians)
- Two asexual generations a year on hemlock. **Sistens** (overwintering generation): first-instar crawlers settle in early summer and go dormant through summer (**aestivation**, roughly **June–October**). They resume feeding around **October–November**, lay eggs **February–April**, and produce **progrediens** crawlers in **March–May**.
- **Most visible: about November to June**, when white wool ovisacs are present and conspicuous. Peak is **late winter to spring (Feb–Apr)**, when ovisacs reach about **3 mm** across.
- **Summer (Jul–Sep)**: settled nymphs are tiny (<1 mm), black, with a thin white fringe of wax. Easy to miss, and summer surveys underestimate infestation. The rules engine should lower confidence for a "not detected" result from summer surveys.

### 1.2 Signs and symptoms
- **Sign (diagnostic):** white, cottony, round wool masses about **1–3 mm** (cotton-swab tip size). They sit **at the base of needles, on the underside of twigs**, mostly on current and previous year's growth. The wool comes off as a waxy mass. Crushing one reveals a dark purplish-black adelgid and amber eggs.
- **Symptoms, in progression:**
  - Needles go from dark green to **grayish or dull gray-green**.
  - Needles drop early.
  - **New shoot growth fails** (no spring flush), which is a key early crown symptom.
  - Crown thins, with dieback that usually starts in the **lower crown and moves upward** (lower branches first). Crown transparency increases.
  - Advanced trees have only a tuft of foliage near the top.
  - Death follows, often hastened by drought and borers.
- **Look-alikes:**
  - *Spittlebug*: wet, frothy foam, mostly in spring. Not dry wool.
  - *Spider egg sacs and webbing*: silky, can be peeled off, often on needle tips. No insect inside.
  - *EHS*: flat, elongate, brown or white covers on the **needle underside**, not at the needle base on the twig.
  - *Pine bark adelgid*: occurs on white pine bark, not on hemlock.
  - *Hemlock rust mite / spruce spider mite*: stippling, no wool.
  - *Pine resin or bird droppings*: hard, not wool.

### 1.3 Photo detection
- **Trunk-bark photos cannot detect HWA.** HWA feeds on twigs, not bark. A trunk-bark view is only useful as a tree ID/re-identification fingerprint and for spotting borer holes, bark cracks or fungal conks. The app should never output a "no HWA" conclusion from bark photos.
- **Twig-underside close-up (most important):**
  - Take it from **10–30 cm**, phone macro or 2x zoom, with the twig underside turned toward the camera.
  - Ovisacs of 1–3 mm need roughly ≥10 px each, so frame about 10–15 cm of twig at 12 MP. **[engineering estimate]**
  - Shoot several branches: lower crown, all aspects. Ideally use the same branches as the 100-tip count (see 1.5).
- **Crown photo:** taken from about **10–30 m**, with sky behind, from a repeatable standpoint. It shows transparency, gray color and missing new growth. It is not specific to HWA.
- **Published detection work:**
  - Landsat/MODIS time series have mapped hemlock decline in the southern Appalachians (e.g., Vogelmann et al.; work in Great Smoky Mountains NP).
  - Hyperspectral (AVIRIS, Hyperion) and leaf spectroscopy separate infested from healthy trees, with reported accuracies around **70–90%** at stand or crown level for **moderate–severe decline**. Early infestation is poorly detected. **[UNVERIFIED specific numbers]**
  - I found no validated smartphone ML classifier for HWA ovisacs. Treat any model you build as experimental and require human confirmation.
  - Citizen-science reporting apps exist (EDDMapS / "Outsmart" and similar). They are reporting tools, not detectors.

### 1.4 What the sensors can and cannot tell
- **Cold mortality:**
  - Sistens supercooling points cluster around **−18 °C**. Substantial mortality occurs at **≤ −20 °C**, and very high mortality (>90%) at **−25 to −30 °C**. Some cold-tolerant individuals persist (USFS, Costa et al. 2008; Parker et al. 1999).
  - North Georgia winters rarely go below about −15 °C. Expect low winter mortality, so do not build "winter will save it" messaging.
  - A DHT11 is rated only 0–50 °C ±2 °C, so **it cannot measure these lows**. Use the NOAA station minimum instead, or replace it with a DHT22/DS18B20.
- **Aestivation/activity:** Sistens aestivate when summer temperatures are high (roughly **>20–25 °C** sustained). Development occurs at about **5–20 °C** **[approximate; see Limbu et al. 2022, Env. Entomol. 51(6)]**. Temperature can set a "season/visibility" flag, for example "summer — wool sparse, survey confidence low".
- **Drought:** Drought plus HWA speeds decline, and dry soil lowers systemic insecticide uptake. Hemlock sites are typically moist. Calibrate a soil-moisture alert per sensor. The thresholds below are **heuristic/engineering, not from the literature**:
  - **Alert** when volumetric water content stays below about **15% VWC**, or about **50% of field-capacity reading**, for ≥2 consecutive visits.
  - **Warn** below about **20–25% VWC**.
  - Better: pull the regional **US Drought Monitor** category. **D1+ = elevated risk**; D2+ = recommend watering.
- **Humidity/light:**
  - High humidity does not change HWA risk in any meaningful way.
  - Lux can track **canopy openness over time**. Rising understory light at the same spot and time suggests crown thinning, but this signal is noisy (sun, clouds, time of day). Use it only as a weak trend signal.
- **State this rule explicitly:** sensors give risk or stress context only. They **never diagnose** a pest.

### 1.5 Confirmation and rating scales
- Hand lens (10x) on twig undersides. Extension or Georgia Forestry Commission confirmation for new locations.
- **Standard sampling method (Costa & Onken 2006, USFS FHTET):** examine branch tips in the lower crown and record the **% of tips with ≥1 HWA**. One common protocol: 2 branches per tree × 50 tips, or 100 tips.
- **Crown ratings:**
  - USFS FIA crown condition: live crown ratio, density, transparency (5% classes), dieback %.
  - **Hemlock vigor scale** (Onken & Keena): 1 = healthy, full crown → 5 = dead/nearly dead, based on % foliage loss.
- **Suggested mapping to your 0–3 scale (combine signs and crown):**
  - **0** = no wool on ≥100 tips, crown transparency <25%, new growth present.
  - **1** = 1–10% of tips infested and/or transparency 25–40%.
  - **2** = 10–50% of tips, transparency 40–60%, little new growth.
  - **3** = >50% of tips, transparency >60%, dieback, or vigor 4–5.
  - **[Breakpoints are a proposal, not a published standard.]**

### 1.6 Management
- **Systemics (main tool):**
  - **Imidacloprid** by soil drench, soil injection, tablets or trunk injection. It moves slowly: 6 months to 2+ years to reach full effect in large trees. Protection lasts about **4–7 years**.
  - **Dinotefuran** as a basal bark spray. It moves fast (weeks) and is used for heavily infested or declining trees, often combined with imidacloprid. Protection lasts 1–2 years.
  - Dose scales with **DBH**; label rates are per inch DBH. **Use the product label, not app text.**
  - Avoid treating in drought or on saturated or frozen soil. Spring and fall are typical timings.
  - **Near water:** imidacloprid is highly toxic to aquatic invertebrates. Many programs use stem injection or basal bark application, not soil application, near streams. Typical buffers are about 50 ft. Check the label and GA rules. **[UNVERIFIED exact buffer]**
  - Tree size limit for homeowner treatment: the label may cap total annual active ingredient per acre.
- **Horticultural oil / insecticidal soap:** for small trees only, when you can cover all foliage completely.
- **Biological control:**
  - *Laricobius nigrinus* and *L. osakensis* beetles feed on sistens in fall and winter.
  - Silver flies *Leucotaraxis argenticollis* / *L. piniperda* (formerly *Leucopis*) feed on the progrediens.
  - Released in GA, NC and the Smokies. These are long-term tools for forests, not rescue for individual trees. They are often paired with strategic chemical treatment (an "integrated" approach).
- **Silvicultural:**
  - Water trees during drought.
  - Mulch the root zone and avoid root and soil compaction.
  - **Do not fertilize with nitrogen**, because it boosts HWA populations (McClure).
  - Thinning competition helps only cautiously; sudden exposure can stress hemlocks.
- **Sanitation:**
  - Don't move infested branches, nursery stock or firewood.
  - Birds, deer, wind and people carry crawlers in spring. Work around infested trees last, and clean clothing and gear.
  - Bird feeders under hemlocks are a known spread route.
- **Reporting and help:**
  - **Georgia Forestry Commission** forest health program.
  - UGA Extension county office.
  - **Save Georgia's Hemlocks** (nonprofit: treatment guidance and volunteer help).
  - GA Dept. of Agriculture for nursery stock.
  - For parks: the USFS Chattahoochee-Oconee NF.
- **Call a professional when:**
  - The tree has a DBH over about 15 in, or is near water.
  - Crown rating is 2–3 (needs dinotefuran plus imidacloprid).
  - There are hazard trees near structures.
  - A restricted-use product or trunk injection is required.

---

## 2. Elongate hemlock scale (EHS)

### 2.1 Basics
- Armored scale insect. Hosts are Eastern/Carolina hemlock, fir and spruce. It is common on Fraser fir in western NC (NC State).
- Has **1–2+ overlapping generations a year**, so all life stages are present year-round. Crawler peaks are roughly **May–June** and **Aug–Sept** **[timing approximate for GA]**.
- **Visible year-round**, but easiest to see in **late summer to winter**.

### 2.2 Signs and symptoms
- **Females:** elongate, flat, **brown to yellow-brown cover about 1.5 mm**, darker at one end, on the **underside of needles**. Best seen with a hand lens (Penn State, VT).
- **Males:** smaller, white, waxy, elongate covers. Heavy infestations give needle undersides a **whitish, "frosty" coat** (VT). Adult males may look like tiny wasps.
- **Symptoms:**
  - **Yellow banding or chlorotic flecks on the upper needle surface** above where the scales feed.
  - Needle drop.
  - Thinning that starts in the **lower crown**.
  - Branch dieback over years.
  - Slower to kill than HWA, but it seriously weakens trees and works with HWA.
- **Look-alikes:**
  - *HWA*: round wool at the **needle base on the twig**. EHS sits **on the needle**, flat and elongate.
  - *Hemlock scale (Abgrallaspis ithacae)*: round, black, also on needle undersides.
  - *Cryptomeria scale*: similar. Needs microscope or lab ID.
  - Fungal spots don't lift off. Scale covers can be flicked off with a fingernail.

### 2.3 Photos
- **Needle-underside close-up (macro, about 5–15 cm):** needed to see 1.5 mm covers. A regular twig photo at 20–30 cm shows only the "white coat" in heavy infestations.
- **Upper-needle photo:** shows yellow flecking.
- **Crown photo:** non-specific thinning only.
- **Trunk bark: useless for EHS.**
- No published ML/remote-sensing EHS detection found.

### 2.4 Sensors
- Hot, dry conditions and stressed trees favor scales. There are no established temperature or humidity thresholds for EHS.
- Cold limits its northern range. GA winters do not limit it.
- Sensors provide general stress context only.

### 2.5 Confirmation and rating
- Hand lens. Extension ID for species, since several scales look alike.
- Rate as **% of needles or shoots with live scales** on a sample of 10–20 shoots from the lower crown. Flip covers to check for live (yellow, soft) vs dead/parasitized bodies.
- Suggested 0–3 scale: 0 none; 1 occasional scales; 2 scales common on many shoots with chlorosis; 3 needles white-coated, needle drop, dieback. **[proposal]**

### 2.6 Management
- **Dinotefuran (basal bark or soil) is the systemic of choice for EHS.** Imidacloprid is weak against it, and its use has been tied to EHS and spider-mite increases.
- **Horticultural oil** (dormant or summer rate) targets crawlers. Time sprays to crawler activity; double-sided tape bands can monitor crawlers.
- Natural enemies include *Encarsia citrina*, a parasitoid. Avoid broad-spectrum sprays such as pyrethroids.
- Don't fertilize with nitrogen, and don't move infested nursery stock.
- Call a professional for large trees or trees with both HWA and EHS (combined program).

---

## 3. Drought / abiotic stress, plus secondary root rot and borers

### 3.1 Basics
- Hemlock is shallow-rooted and found on moist coves and streamsides. Drought causes needle loss, poor shoot growth and cambial stress, and it raises HWA impact.
- Stressed trees are attacked by **hemlock borer** and ***Armillaria*** root rot.
- **Season:** late summer to fall in drought years. Symptoms lag stress by months to a year.

### 3.2 Signs and symptoms
- **Drought:**
  - Uniform, **whole-crown** dulling and yellowing.
  - Needle drop from the inner/older needles.
  - Shoots short or missing.
  - Often top dieback ("flagging" at the top).
  - **No insects found on twigs.**
- **Armillaria:**
  - **White mycelial fans under the bark** at the root collar.
  - Black shoestring-like rhizomorphs.
  - Honey-colored mushrooms at the base in fall.
  - Resin flow at the base.
  - Overall crown decline.
- **Hemlock borer:** small **D-shaped (oval) exit holes about 3–5 mm** in the bark, woodpecker flaking, and galleries under the bark.
- **Sunscald/winter burn:** browning on the south or west side after exposure or a cold snap.
- **Distinguishing:** absence of HWA/EHS on twigs plus a dry sensor record plus a whole-crown pattern suggests abiotic stress. **This can never be confirmed by the app alone.**

### 3.3 Photos
- **Trunk bark (your current view) is useful here:**
  - Borer exit holes, bark flaking from woodpeckers, resin streaks, cracks and conks.
  - Photograph the trunk at chest height and **add a root-collar/base photo**.
  - Take bark photos at 0.5–1 m distance. To catch 3–5 mm holes, use a close-up at about 20–30 cm.
- **Crown photo:** shows whole-crown color and transparency.
- The Landsat/MODIS drought-decline literature applies only at stand scale.

### 3.4 Sensors (the strongest use case)
- **Soil moisture:**
  - Trend-based alerts, as described in 1.4: about <15% VWC, or <50% of the wet baseline, for ≥2 visits = "drought stress risk"; recommend watering.
  - Hobby capacitive sensors need calibration per soil type. Thresholds are **heuristic**.
- **Regional drought:** US Drought Monitor D1–D4, or a Palmer/SPEI value at or below −1 (moderate drought), as the authoritative input.
- **Temperature + RH:**
  - Compute **VPD**. A VPD over about **1.5–2 kPa** on hot days means high evaporative demand **[general plant physiology, not hemlock-specific]**.
  - Temperatures above about 32 °C plus low RH plus dry soil = acute stress flag.
- **Humidity and fungi:**
  - Long periods of leaf wetness or high RH (>90%) favor needle blights and rusts.
  - Low priority in this region. A DHT11 (±5% RH) is not precise enough for disease modeling.
- **Light:** sudden higher lux at the same spot can mean nearby canopy loss (sunscald or exposure risk).

### 3.5 Confirmation and rating
- Check twigs for HWA/EHS to rule them out. Inspect the root collar under the bark for Armillaria fans.
- Send samples to the UGA Plant Disease Clinic via county extension.
- Rate using FIA crown dieback % and transparency. On a 0–3 scale: 0 = <10% dieback; 1 = 10–25%; 2 = 25–50%; 3 = >50%. **[mapping proposal]**

### 3.6 Management
- **Watering:** soak deeply about every 7–14 days during drought (about 1 in of water over the root zone, slow soak). **[typical extension guidance]**
- **Mulch:** 2–4 in, kept off the trunk.
- **Protect roots:** avoid root damage, soil compaction and grade changes.
- **No nitrogen fertilizer.**
- Treat HWA as well, since drought plus HWA kills. But don't apply soil systemics to drought-stressed trees; water first.
- **Hazard and removal:** dead hemlocks fail quickly. Call an ISA-certified arborist for trees near people or structures, or when Armillaria or borers are confirmed.

---

## Rules-engine guardrails (summary)
- **Bark-only photos can only output "HWA/EHS status unknown", never "healthy".**
- Detection requires twig and needle underside close-ups. In Jun–Sep, a negative HWA survey gets lowered confidence.
- Sensors raise or lower **risk**, never diagnosis.
- DHT11 cannot read below 0 °C. Use station data for winter-kill thresholds (≤ −20 °C partial mortality, ≤ −25 to −30 °C high mortality), and expect little benefit in North Georgia.
- Every positive or suspected detection: tell the user to confirm with a hand lens and report it to the Georgia Forestry Commission or UGA Extension. Point to Save Georgia's Hemlocks for treatment help.
- Never output pesticide doses. Defer to the label and a licensed applicator, especially near water.

## Sources
- USDA FS NRS, Costa et al. 2008, HWA cold tolerance (symposium): https://www.nrs.fs.usda.gov/pubs/jrnl/2008/nrs_2008_costa_001.pdf
- Limbu et al. 2022, USFS NRS: https://fs.usda.gov/nrs/pubs/jrnl/2022/nrs_2022_limbu_001.pdf
- Estivation and post-estivation development of HWA, Environ. Entomol. 51(6): https://complete.bioone.org/journals/environmental-entomology/volume-51/issue-6/nvac089/Estivation-and-Postestivation-Development-of-Hemlock-Woolly-Adelgid-Adelges-tsugae/10.1093/ee/nvac089.full
- Parker et al. 1999, HWA cold exposure, Environ. Entomol. 28(6): https://academic.oup.com/ee/article/28/6/1085/449344
- McAvoy et al. 2017, HWA winter mortality modeling, Forests 8(12):497: https://www.mdpi.com/1999-4907/8/12/497
- USFS Treesearch HWA record: https://research.fs.usda.gov/treesearch/35156
- MSU thesis on HWA cold tolerance: https://d.lib.msu.edu/etd/51276
- NC State Extension, Elongate Hemlock Scale: https://content.ces.ncsu.edu/elongate-hemlock-scale
- Penn State Extension, Elongate Hemlock Scale: https://extension.psu.edu/elongate-hemlock-scale
- UMass, Fiorinia externa: https://www.umass.edu/agriculture-food-environment/landscape/fact-sheets/elongate-hemlock-scale
- Virginia Tech ENTO-552: https://pubs.ext.vt.edu/content/pubs_ext_vt_edu/en/ENTO/ento-552/ento-552.html
- Lambdin et al. 2008 (EHS genetics, TN/NC): https://scalenet.info/references/LambdiGrRe2008/
- Additional references cited from background knowledge, not fetched this session (verify before use):
  - Costa & Onken 2006, USFS FHTET-2006-16, HWA biocontrol/sampling
  - USFS FIA Crown Condition field guide
  - Georgia Forestry Commission forest health pages (gatrees.org)
  - Save Georgia's Hemlocks (savegeorgiashemlocks.org)
  - UGA Extension HWA publications
  - Vogelmann et al., Landsat hemlock decline
  - McClure (nitrogen fertilization and HWA)
