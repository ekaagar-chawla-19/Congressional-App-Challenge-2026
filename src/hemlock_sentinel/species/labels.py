"""Species label registry.

Re-identification is only supported for species in ``REID_SUPPORTED``. Other
known species are classified (so the UI can say "this is a red maple") but are
never given an individual ID. New species are added here plus a retrained head.
Tree ID prefixes are per species so IDs stay readable (H-017, P-003).
"""

from __future__ import annotations

# Species present in the current training data (BarkNet 1.0 codes in comments).
SPECIES = [
    "tsuga_canadensis",      # PRU  Eastern hemlock
    "pinus_strobus",         # PIB  Eastern white pine
    "pinus_resinosa",        # PIR
    "pinus_rigida",          # PID
    "fagus_grandifolia",     # HEG  American beech
    "acer_rubrum",           # ERR  red maple
    "acer_platanoides",      # ERB
    "populus_grandidentata", # PEG
]

COMMON_NAMES = {
    "tsuga_canadensis": "Eastern hemlock",
    "pinus_strobus": "Eastern white pine",
    "pinus_resinosa": "Red pine",
    "pinus_rigida": "Pitch pine",
    "fagus_grandifolia": "American beech",
    "acer_rubrum": "Red maple",
    "acer_platanoides": "Norway maple",
    "populus_grandidentata": "Bigtooth aspen",
    "unknown": "Unknown / unsupported",
}

REID_SUPPORTED = {"tsuga_canadensis"}

ID_PREFIX = {"tsuga_canadensis": "H"}

BARKNET_CODES = {
    "PRU": "tsuga_canadensis", "PIB": "pinus_strobus", "PIR": "pinus_resinosa",
    "PID": "pinus_rigida", "HEG": "fagus_grandifolia", "ERR": "acer_rubrum",
    "ERB": "acer_platanoides", "PEG": "populus_grandidentata",
    # Held out entirely from species training to test "unknown" rejection:
    "THO": "thuja_occidentalis", "EPR": "picea_rubens",
}
HELD_OUT_SPECIES = {"thuja_occidentalis", "picea_rubens"}
