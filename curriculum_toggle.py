import json
import re
from typing import Dict


CURRICULUM_PATH = 'curriculum.json'


def _read_curriculum() -> Dict:
    try:
        with open(CURRICULUM_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _write_curriculum(data: Dict):
    # simple atomic write: write to temp and replace
    tmp = CURRICULUM_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
    import os
    os.replace(tmp, CURRICULUM_PATH)


def _sem_is_odd(sem_name: str) -> bool:
    # Expect sem_name like 'Sem-1' or 'Sem-2' - extract number
    m = re.search(r"(\d+)", sem_name)
    if not m:
        return True
    try:
        return int(m.group(1)) % 2 == 1
    except Exception:
        return True


def detect_current_side() -> str:
    """Return 'odd' if odd semesters are currently marked True more often than even,
    otherwise 'even'."""
    data = _read_curriculum()
    odd_true = 0
    even_true = 0
    for year, ydata in (data or {}).items():
        semesters = ydata.get('Semesters', {})
        for sem_name, sem_data in semesters.items():
            current = bool(sem_data.get('Current', False))
            if _sem_is_odd(sem_name):
                if current:
                    odd_true += 1
            else:
                if current:
                    even_true += 1

    # default to odd if tie or no data
    return 'odd' if odd_true >= even_true else 'even'


def get_state() -> Dict:
    return {'current_side': detect_current_side()}


def toggle_curriculum() -> Dict:
    """Flip the Current boolean for every semester in curriculum.json and return new state."""
    data = _read_curriculum()
    if not data:
        return get_state()

    for year, ydata in data.items():
        semesters = ydata.get('Semesters', {})
        for sem_name, sem_data in semesters.items():
            # Only flip if the key exists and is a boolean-like value
            sem_data['Current'] = not bool(sem_data.get('Current', False))

    _write_curriculum(data)

    return get_state()
import json
import os
from typing import Dict

try:
    # reuse atomic write helper if available
    from attendance_system import atomic_write_json
except Exception:
    atomic_write_json = None


CURRICULUM_PATH = os.path.join(os.path.dirname(__file__), 'curriculum.json')


def _load(path: str = CURRICULUM_PATH) -> Dict:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def _save(data: Dict, path: str = CURRICULUM_PATH):
    if atomic_write_json:
        try:
            atomic_write_json(path, data)
            return
        except Exception:
            pass

    # fallback simple write
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def detect_current_side(path: str = CURRICULUM_PATH) -> str:
    """Return 'odd' or 'even' depending on which parity has more Current=True entries.

    If tie or no flags, defaults to 'odd'.
    """
    data = _load(path)
    odd_true = 0
    even_true = 0

    for year, ydata in data.items():
        sems = ydata.get('Semesters', {})
        for sem_name, sem in sems.items():
            cur = sem.get('Current', False)
            # parse number from sem_name like 'Sem-1'
            try:
                num = int(''.join(ch for ch in sem_name if ch.isdigit()))
            except Exception:
                continue
            if num % 2 == 1:
                if cur:
                    odd_true += 1
            else:
                if cur:
                    even_true += 1

    if odd_true >= even_true:
        return 'odd'
    return 'even'


def set_side(side: str, path: str = CURRICULUM_PATH) -> str:
    """Set `Current` True for semesters matching side ('odd'|'even') and False otherwise.

    Returns the side set.
    """
    side = side.lower()
    if side not in ('odd', 'even'):
        raise ValueError('side must be "odd" or "even"')

    data = _load(path)
    changed = False

    for year, ydata in data.items():
        sems = ydata.get('Semesters', {})
        for sem_name, sem in sems.items():
            try:
                num = int(''.join(ch for ch in sem_name if ch.isdigit()))
            except Exception:
                continue
            want = (num % 2 == 1) if side == 'odd' else (num % 2 == 0)
            if sem.get('Current', False) != want:
                sem['Current'] = bool(want)
                changed = True

    if changed:
        _save(data, path)

    return side


def toggle(path: str = CURRICULUM_PATH) -> str:
    current = detect_current_side(path)
    new = 'even' if current == 'odd' else 'odd'
    return set_side(new, path)


def get_state(path: str = CURRICULUM_PATH) -> Dict:
    data = _load(path)
    odd_true = 0
    even_true = 0
    semesters_total = 0
    for year, ydata in data.items():
        sems = ydata.get('Semesters', {})
        for sem_name, sem in sems.items():
            semesters_total += 1
            try:
                num = int(''.join(ch for ch in sem_name if ch.isdigit()))
            except Exception:
                continue
            if sem.get('Current', False):
                if num % 2 == 1:
                    odd_true += 1
                else:
                    even_true += 1

    return {
        'current_side': detect_current_side(path),
        'odd_true': odd_true,
        'even_true': even_true,
        'semesters_total': semesters_total
    }


if __name__ == '__main__':
    # CLI: show state or toggle
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--toggle', action='store_true')
    args = parser.parse_args()
    if args.toggle:
        new = toggle()
        print('Toggled curriculum to', new)
    else:
        print(get_state())
