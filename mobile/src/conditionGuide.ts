// The server's advice per condition (src/hemlock_sentinel/api/diseases.py CONDITIONS + GENERAL_ADVICE), for
// phone-only Insights. Generated from the Python; tests/integration/test_phone_analysis.py checks it is the same.
export default {
  "conditions": {
    "hwa": {
      "name": "Hemlock woolly adelgid (HWA)",
      "recommendations": [
        "Confirm by checking twig undersides on several branches (Nov-June is easiest); photograph a close-up.",
        "Treat valuable trees with a systemic insecticide applied by a licensed applicator: imidacloprid (soil or trunk; slow to act on large trees, protects for several years) or dinotefuran (basal bark spray; acts within weeks, shorter protection). Often combined: dinotefuran first, imidacloprid for long-term protection. Follow the label; no soil applications near streams or wet soils.",
        "Ask about biological control releases (Laricobius beetles, silver flies) through the Georgia Forestry Commission or Save Georgia's Hemlocks for larger stands.",
        "Prioritize trees with healthy crowns: heavily declined trees (more than ~50% crown loss) respond poorly.",
        "Avoid moving hemlock branches or nursery stock from infested areas; avoid nitrogen fertilizer (it favors the adelgid)."
      ],
      "confirm": "Look at the underside of the outer twigs on several low branches, ideally November-June when the white wool is present. Wool at needle bases = HWA (spider egg sacs and spittle are found elsewhere and wipe off differently). Report new finds to the Georgia Forestry Commission."
    },
    "ehs": {
      "name": "Elongate hemlock scale (EHS)",
      "recommendations": [
        "Confirm with a hand lens or send a sample to your county extension office.",
        "Dinotefuran (systemic) is generally more effective against EHS than imidacloprid; horticultural oil sprays can be used on small reachable trees. Use a licensed applicator for large trees.",
        "If HWA is also present, choose a treatment that covers both (ask the applicator)."
      ],
      "confirm": "Turn branches over: brown, elongated covers about 1.5-2 mm (females) and smaller white waxy covers (males) on needle undersides, with yellow bands on the needle tops. A hand lens helps; an extension office can confirm from a sample."
    },
    "drought_stress": {
      "name": "Drought stress and secondary decline (root rot, borers)",
      "recommendations": [
        "Water high-value trees during drought: a slow, deep soak over the root zone about every 1-2 weeks.",
        "Mulch 5-10 cm over the root zone, kept off the trunk; avoid compaction, root damage and grade changes.",
        "Do not apply soil insecticides to drought-stressed trees: water first, treat when soil is moist.",
        "No nitrogen fertilizer.",
        "If root rot or borers are found, or a dying tree stands near trails or buildings, call an ISA-certified arborist: dead hemlocks fail quickly.",
        "Re-check soil moisture on the next visits; one dry reading is not a diagnosis."
      ],
      "confirm": "Repeated low soil-moisture readings in a dry season with whole-crown dulling, and no insects on the twigs. Check the trunk base for fungal fans/mushrooms and the bark for small exit holes. Samples can go to the UGA Plant Disease Clinic through your county extension office. The app alone can never confirm this."
    }
  },
  "general_advice": [
    "Confirm any suspected pest with a 10x hand lens and report new finds to the Georgia Forestry Commission or your UGA Extension county office; Save Georgia's Hemlocks offers treatment guidance and volunteer help.",
    "The app never gives pesticide doses: follow the product label and use a licensed applicator, especially near streams (imidacloprid is highly toxic to aquatic life) and for trees over ~15 in DBH.",
    "Don't move hemlock branches, firewood or nursery stock from infested areas; visit infested trees last and clean gear (birds, deer and people carry crawlers in spring)."
  ]
};
