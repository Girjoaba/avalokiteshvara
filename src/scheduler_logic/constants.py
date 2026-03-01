"""Factory BOM data, phase configuration, and working-hours constants.

Source: NovaBoard hackathon factory spec.
One production line, 480 min/day, 08:00-16:00, 7 days/week, sequential batch processing.
"""

PHASE_DURATIONS: dict[str, dict[str, int]] = {
    "PCB-IND-100": {"SMT": 30, "Reflow": 15, "THT": 45, "AOI": 12, "Test": 30, "Coating": 9,  "Pack": 6},
    "MED-300":     {"SMT": 45, "Reflow": 30, "THT": 60, "AOI": 30, "Test": 90, "Coating": 15, "Pack": 9},
    "IOT-200":     {"SMT": 18, "Reflow": 12, "THT": 0,  "AOI": 9,  "Test": 18, "Coating": 0,  "Pack": 6},
    "AGR-400":     {"SMT": 30, "Reflow": 15, "THT": 30, "AOI": 12, "Test": 45, "Coating": 12, "Pack": 0},
    "PCB-PWR-500": {"SMT": 24, "Reflow": 12, "THT": 0,  "AOI": 9,  "Test": 24, "Coating": 0,  "Pack": 6},
}

PHASES_ORDER = ["SMT", "Reflow", "THT", "AOI", "Test", "Coating", "Pack"]

MINUTES_PER_DAY = 480
DAY_START_HOUR = 8
DAY_END_HOUR = 16

PHASE_COLORS = {
    "SMT":     "#4fc3f7",
    "Reflow":  "#81c784",
    "THT":     "#ffb74d",
    "AOI":     "#ba68c8",
    "Test":    "#f06292",
    "Coating": "#4db6ac",
    "Pack":    "#aed581",
}
