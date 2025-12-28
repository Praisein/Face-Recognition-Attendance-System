import json
import os
import re
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

CURRICULUM_PATH = os.path.join(os.path.dirname(__file__), "curriculum.json")


# ---------- helpers ----------

def _load() -> Dict[str, Any]:
    try:
        with open(CURRICULUM_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"Curriculum file not found: {CURRICULUM_PATH}")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode curriculum JSON: {e}")
        return {}


def _save(data: Dict[str, Any]):
    try:
        tmp = CURRICULUM_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, CURRICULUM_PATH)
    except Exception as e:
        logger.error(f"Failed to save curriculum data: {e}")
        raise


def _sem_number(sem_name: str) -> Optional[int]:
    m = re.search(r"\d+", sem_name)
    return int(m.group()) if m else None


# ---------- core logic ----------

def detect_current_side() -> str:
    """
    Detect whether odd or even semesters are currently active.
    Defaults to 'odd' if unclear or no semesters are marked as current.
    """
    data = _load()
    odd_true = 0
    even_true = 0

    try:
        for year in data.values():
            if not isinstance(year, dict):
                continue
            for sem_name, sem in year.get("Semesters", {}).items():
                if not isinstance(sem, dict) or not sem.get("Current"):
                    continue

                num = _sem_number(sem_name)
                if not num:
                    continue

                if num % 2 == 1:
                    odd_true += 1
                else:
                    even_true += 1
    except (AttributeError, TypeError) as e:
        logger.error(f"Error parsing curriculum data structure: {e}")
        return "odd"

    # If no current semesters found, default to 'odd'
    if odd_true == 0 and even_true == 0:
        return "odd"
    
    return "odd" if odd_true >= even_true else "even"


def set_side(side: str) -> Dict[str, Any]:
    """
    Activate either odd or even semesters.
    """
    side = side.lower()
    if side not in ("odd", "even"):
        raise ValueError("side must be 'odd' or 'even'")

    data = _load()

    try:
        for year in data.values():
            if not isinstance(year, dict):
                continue
            for sem_name, sem in year.get("Semesters", {}).items():
                if not isinstance(sem, dict):
                    continue
                    
                num = _sem_number(sem_name)
                if not num:
                    continue

                sem["Current"] = (
                    num % 2 == 1 if side == "odd" else num % 2 == 0
                )
    except (AttributeError, TypeError) as e:
        logger.error(f"Error updating curriculum data: {e}")
        raise

    _save(data)
    return get_state()


def toggle() -> Dict[str, Any]:
    """
    Toggle between odd and even semesters.
    """
    current = detect_current_side()
    new_side = "even" if current == "odd" else "odd"
    return set_side(new_side)


def get_state() -> Dict[str, Any]:
    return {
        "current_side": detect_current_side()
    }
