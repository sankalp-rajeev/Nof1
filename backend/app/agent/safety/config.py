"""Safety constants and blocking vocabulary; no model-controlled settings."""

INBOUND_FUZZY_THRESHOLD = 88
CHECKIN_WORD_LIMIT = 120
DIRECTIVE_WINDOW = 40
ACKNOWLEDGEMENT_WORDS = frozenset(
    "i ive we weve you youve your my our the a an and or as at on for to with about "
    "have has had been was were is are it its that thats this these those "
    "saved logged recorded noted just now today yesterday successfully also "
    "note notes entry entries event events check in checkin update updates "
    "rating ratings score scores symptom symptoms episode episodes "
    "intake intakes dose doses taken consumed consumption done skipped "
    "day days time times change changes point points one all".split()
)
PERSISTENCE_ACK_WORDS = ACKNOWLEDGEMENT_WORDS | frozenset(
    "added updated marked stored captured entered written filed registered "
    "got put took down file timeline log records complete completed finished "
    "everything of new s".split()
)
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
    "twice": 2,
    "thrice": 3,
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
    "vitamin",
    "mineral",
    "probiotic",
    "prebiotic",
)
