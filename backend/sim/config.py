"""Fixed simulator/evaluation definitions from PRD sections 9 and 10."""

from datetime import date

EXPOSURES = ("magnesium", "coffee", "dairy", "walk", "electrolytes", "alcohol")
OUTCOME = "fatigue"
START_DATE = date(2026, 1, 1)
DEV_SEED_MIN = 0
DEV_SEED_MAX = 9999
PATIENT_TYPES = ("null", "single_effect", "double_effect", "confounded_null")
PATIENT_WEIGHTS = (0.4, 0.4, 0.1, 0.1)
EFFECT_SIZES = (1.0, 1.5, 2.0, 3.0)
COHORT_A = range(1000)
COHORT_N = range(2000, 2300)
COHORT_V = range(3000, 3800)
REGRESSION_A = range(60)
REGRESSION_N = range(2000, 2100)
E1_MAX = 0.15
E2_MIN = 0.85
E3_MAX = 0.10
REGRESSION_RECALL_DROP = 0.05
REGRESSION_FALSE_POSITIVE_RISE = 0.03
ADHERENCE_P = 0.9
VERDICT_LABELS = ("helped", "worsened", "no_detectable_effect", "inconclusive")
COHORT_L = range(30)
CHAT_DAYS = 30
SEVERITY_NOISE_P = 0.3
DROPOUT_P = 0.01
COMPLIANCE_P = 0.9
MAX_FOLLOWUPS = 8
RENDER_ATTEMPTS = 3
RENDER_MAX_CHARS = 1200
LIVE_MAX_CALLS = 5000
E4_RUN2_MAX_SPEND_USD = "2.00"
E4_PERSONA_TIMEOUT_S = 120.0
E4_PERSONA_KEEP_ALIVE = "24h"
E4_PERSONA_RETRY_WAITS_S = (45.0, 45.0, 45.0, 45.0)
E4_READINESS_TIMEOUT_S = 3.0
E4_OLLAMA_BASE_URL = "http://127.0.0.1:11434/v1"
# Documented model input limits, including full system/schema input. Reservations
# deliberately avoid the production router's approximate character/token estimate.
GEMINI_MAX_INPUT_TOKENS = {
    "gemini:gemini-3.1-flash-lite": 1048576,
    "gemini:gemini-3.8-flash": 1048576,
}
FINAL_A = range(10000, 11000)
FINAL_N = range(10000, 10300)
FINAL_V = range(10300, 10700)
FINAL_L = range(10000, 10030)
