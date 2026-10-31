"""Safety constants and blocking vocabulary; no model-controlled settings."""

INBOUND_FUZZY_THRESHOLD = 88
CHECKIN_WORD_LIMIT = 120
DIRECTIVE_WINDOW = 40
NUMBER_WORDS = {
    "zero": 0,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "dozen": 12,
    "half": 0.5,
}
MEDICINE_WORDS = (
    "medication",
    "medicine",
    "prescription",
    "supplement",
    "dose",
    "tablet",
    "pill",
    "insulin",
    "metformin",
    "sertraline",
    "amitriptyline",
    "amoxicillin",
    "atorvastatin",
    "aspirin",
    "ibuprofen",
    "antihistamine",
)
