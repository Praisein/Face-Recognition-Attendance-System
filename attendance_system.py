import json
import os
import pickle
import numpy as np
import cv2
import face_recognition
from datetime import datetime

try:
    from ultralytics import YOLO
except Exception:
    YOLO = None
import tempfile
import shutil
import time

# -----------------------------
# SECTION: Constants & file paths
# (locations for student images, encoded data, JSON records)
# -----------------------------

STUDENT_IMAGES_FOLDER = os.path.join("static", "student_images")
ENCODE_FILE = "EncodeFile.p"
CURRENT_STUDENT_JSON = "current_student.json"
ATTENDANCE_RECORDS_JSON = 'attendance_records.json'
STUDENT_DATA_JSON = 'student_data.json'

# Frame transfer control
TRANSFER_EVERY_N_FRAMES = 5
ATTENDANCE_DURATION = 300  #  in seconds (changed from 300)


# -----------------------------
# SECTION: Attendance records I/O
# (load/save attendance from/to JSON storage)
# -----------------------------

def load_attendance_records():
    try:
        with open(ATTENDANCE_RECORDS_JSON, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {'records': {}}
    except Exception as e:
        print(f"[ERROR] Failed to load {ATTENDANCE_RECORDS_JSON}: {e}")
        return {'records': {}}


def save_attendance_records(data):
    try:
        atomic_write_json(ATTENDANCE_RECORDS_JSON, data)
    except Exception as e:
        print(f"[ERROR] Failed to save {ATTENDANCE_RECORDS_JSON}: {e}")


# -----------------------------
# SECTION: Curriculum helpers
# (functions that inspect curriculum.json to map subjects to years)
# -----------------------------

def get_subject_year(subject_name):
    """Find which year the given subject belongs to from curriculum.json"""
    try:
        with open("curriculum.json", "r", encoding="utf-8") as f:
            curriculum = json.load(f)

        for year, year_data in curriculum.items():
            for sem_name, sem_data in year_data.get("Semesters", {}).items():
                all_subjects = sem_data.get("Theory", []) + sem_data.get("Practicals", [])
                if subject_name in all_subjects:
                    return year
    except Exception as e:
        print(f"[ERROR] Could not determine year for subject '{subject_name}': {e}")

    return None


# -----------------------------
# SECTION: Student data I/O & normalization
# (load/save student_data.json and normalize batch/wrapper formats)
# -----------------------------

def load_student_data():
    """Load student data from JSON file - FIXED for batch structure"""
    try:
        with open(STUDENT_DATA_JSON, 'r', encoding='utf-8') as f:
            data = json.load(f)

            # Normalize into a flat mapping: student_id -> student_info
            if isinstance(data, dict):
                # Case 1: batch-style top-level keys mapping to student dicts
                # e.g. { "2324": { "BSCIT-000": {...}, ... }, ... }
                def looks_like_student_dict(d):
                    if not isinstance(d, dict) or not d:
                        return False
                    first = next(iter(d.values()))
                    return isinstance(first, dict) and ('name' in first or 'year' in first)

                # detect batch-style
                batch_like = any(looks_like_student_dict(v) for v in data.values())

                if batch_like:
                    all_students = {}
                    for batch_key, students in data.items():
                        if isinstance(students, dict):
                            for student_id, student_info in students.items():
                                if isinstance(student_info, dict):
                                    student_info.setdefault('batch', batch_key)
                                    student_info.setdefault('student_id', student_id)
                                    all_students[student_id] = student_info
                    return all_students

                # Case 2: wrapper {'students': { ... }}
                if 'students' in data and isinstance(data['students'], dict):
                    all_students = {}
                    for student_id, student_info in data['students'].items():
                        if isinstance(student_info, dict):
                            student_info.setdefault('student_id', student_id)
                            all_students[student_id] = student_info
                    return all_students

                # Case 3: already flat mapping student_id -> info
                if all(isinstance(v, dict) and ('name' in v or 'year' in v) for v in data.values()):
                    all_students = {}
                    for student_id, student_info in data.items():
                        if isinstance(student_info, dict):
                            student_info.setdefault('student_id', student_id)
                            all_students[student_id] = student_info
                    return all_students

            # Fallback: return empty mapping
            return {}
    except FileNotFoundError:
        print(f"[WARN] {STUDENT_DATA_JSON} not found")
        return {}
    except Exception as e:
        print(f"[ERROR] Failed to load {STUDENT_DATA_JSON}: {e}")
        return {}


def save_student_data(students_dict):
    try:
        # Try to preserve the on-disk format. Read existing file to detect style.
        existing = None
        if os.path.exists(STUDENT_DATA_JSON):
            try:
                with open(STUDENT_DATA_JSON, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            except Exception:
                existing = None

        # Helper to detect batch-style existing structure
        def is_batch_style(d):
            if not isinstance(d, dict) or not d:
                return False
            for v in d.values():
                if isinstance(v, dict):
                    first = next(iter(v.values())) if v else None
                    if isinstance(first, dict) and ('name' in first or 'year' in first):
                        return True
            return False

        if existing and is_batch_style(existing):
            # Preserve batch keys. Merge/update entries into appropriate batches.
            new_data = dict(existing)

            # Ensure all batch keys are dicts
            for k in list(new_data.keys()):
                if not isinstance(new_data[k], dict):
                    new_data[k] = {}

            # Place each student into its batch (prefer explicit 'batch' in info)
            for sid, sinfo in students_dict.items():
                batch = sinfo.get('batch')
                target = None
                if batch and batch in new_data:
                    target = batch
                else:
                    # try to find existing batch that already contains this sid
                    for bkey, bval in new_data.items():
                        if isinstance(bval, dict) and sid in bval:
                            target = bkey
                            break

                if not target:
                    # fallback: put into first batch key if exists, else create 'students'
                    if len(new_data) > 0:
                        target = next(iter(new_data.keys()))
                    else:
                        target = 'students'
                        new_data[target] = {}

                # copy sinfo without transient keys
                entry = {k: v for k, v in sinfo.items() if k not in ('batch', 'student_id')}
                new_data.setdefault(target, {})[sid] = entry

            atomic_write_json(STUDENT_DATA_JSON, new_data)
            return

        # If existing is wrapper style {'students': {...}} or None, write as {'students': ...}
        atomic_write_json(STUDENT_DATA_JSON, {'students': students_dict})
    except Exception as e:
        print(f"[ERROR] Failed to save {STUDENT_DATA_JSON}: {e}")


# -----------------------------
# SECTION: Atomic file write helper
# (safe write to JSON using a temporary file then move)
# -----------------------------

def atomic_write_json(path, data):
    dirpath = os.path.dirname(path) or "."
    os.makedirs(dirpath, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dirpath)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        shutil.move(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


# -----------------------------
# SECTION: Image helpers
# (normalize images to RGB uint8 contiguous arrays)
# -----------------------------

def fix_image_format(img):
    if img is None:
        return None
    if not isinstance(img, np.ndarray):
        img = np.array(img)
    if img.size == 0:
        return None
    if len(img.shape) == 3:
        if img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2RGB)
        elif img.shape[2] == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    elif len(img.shape) == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    if img.dtype != np.uint8:
        img = (img * 255).astype(np.uint8) if img.max() <= 1.0 else img.astype(np.uint8)
    if not img.flags['C_CONTIGUOUS']:
        img = np.ascontiguousarray(img)
    return img


# -----------------------------
# SECTION: Attendance update logic
# (update attendance records and student totals in JSON storage)
# -----------------------------

def update_attendance_in_database(student_id, student_name, lecture, status='Present'):
    """Update attendance using JSON storage"""
    today = datetime.now().strftime("%Y-%m-%d")
    current_time = datetime.now().strftime("%H:%M:%S")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        records = load_attendance_records()
        key = f"{today}_{lecture}"
        rec = records.get('records', {}).get(key, {'present': [], 'absent': [], 'time': current_time})

        was_present = student_id in rec.get('present', [])
        was_absent = student_id in rec.get('absent', [])

        if status == 'Present':
            if student_id not in rec['present']:
                rec['present'].append(student_id)
            if student_id in rec['absent']:
                try:
                    rec['absent'].remove(student_id)
                except ValueError:
                    pass
        else:
            if student_id not in rec['absent']:
                rec['absent'].append(student_id)
            if student_id in rec['present']:
                try:
                    rec['present'].remove(student_id)
                except ValueError:
                    pass

        rec['time'] = current_time
        if 'records' not in records:
            records['records'] = {}
        records['records'][key] = rec
        save_attendance_records(records)

        students = load_student_data()
        s = students.get(student_id, {})
        prev_total = int(s.get('total_attendance', 0)) if s.get('total_attendance') is not None else 0

        if status == 'Present' and not was_present:
            s['total_attendance'] = prev_total + 1
            s['last_attendance_time'] = timestamp
        elif status != 'Present' and 'total_attendance' not in s:
            s['total_attendance'] = prev_total

        if student_id in students:
            students[student_id].update(s)
        else:
            students[student_id] = {
                'student_id': student_id,
                'name': student_name,
                'total_attendance': s.get('total_attendance', prev_total),
                'last_attendance_time': s.get('last_attendance_time', '')
            }
        save_student_data(students)

        return True

    except Exception as e:
        print(f"[ERROR] Failed to update attendance for {student_id}: {e}")
        return False


def mark_all_students_absent(lecture):
    """
    DEPRECATED - This function is no longer used in the new logic.
    Students are now marked absent only after 1 hour if they haven't scanned.
    """
    print("[INFO] mark_all_students_absent is deprecated - using new 1-hour logic")
    return False


def get_current_lecture():
    try:
        with open("current_teacher.json", "r", encoding='utf-8') as f:
            teacher_data = json.load(f)
            return teacher_data.get('lecture', 'Default')
    except:
        return 'Default'


def get_student_info_from_database(student_id):
    """Get student info from student_data.json"""
    students = load_student_data()
    student_info = students.get(student_id)
    if student_info:
        # Ensure student_id is included in the returned dict
        student_info['student_id'] = student_id
    return student_info


def save_student_info_to_json(info, teacher_info=None):
    """Save current student info – image_path built from student_id ONLY"""
    try:
        students = load_student_data()
        student_id = info.get('student_id')
        
        if not student_id:
            print("[ERROR] No student_id provided")
            return
        
        student_data = students.get(student_id, {})
        if not student_data:
            print(f"[WARN] Student {student_id} not found in database")
            return
        
        total_attendance = student_data.get('total_attendance', 0)

        data = {
            'student_id': student_id,
            'name': student_data.get('name', ''),
            'batch': student_data.get('batch', ''),
            'year': student_data.get('year', ''),
            'selective': student_data.get('Selective', []),
            'image_path': f'static/student_images/{student_id}.png',
            'total_attendance': total_attendance,
            'last_attendance_time': student_data.get('last_attendance_time', ''),
            'teacher_name': teacher_info.get('name', '') if teacher_info else '',
            'lecture': teacher_info.get('lecture', '') if teacher_info else ''
        }
        
        atomic_write_json(CURRENT_STUDENT_JSON, data)
        print(f"[SUCCESS] Saved current_student.json → {student_id}.png")
        
    except Exception as e:
        print(f"[ERROR] Failed to save current student JSON: {e}")


def mark_present(student_id, lecture, marked_by="system"):
    try:
        students = load_student_data()
        student = students.get(student_id, {})
        student_name = student.get('name', 'Unknown')

        success = update_attendance_in_database(student_id, student_name, lecture, 'Present')

        if success:
            print(f"[SUCCESS] Marked {student_id} as present for {lecture}")
        else:
            print(f"[WARNING] Failed to mark {student_id} as present")

        return success
    except Exception as e:
        print(f"[ERROR] Failed to mark present: {e}")
        return False


def detect_spoofing(img, model, threshold, classNames):
    if model is None:
        return True
    try:
        results = model(img, stream=True, verbose=False)
        max_real_conf = 0.0
        max_fake_conf = 0.0
        
        for r in results:
            for box in r.boxes:
                conf = float(box.conf[0])
                cls = int(box.cls[0])
                if classNames[cls] == 'real':
                    max_real_conf = max(max_real_conf, conf)
                else:
                    max_fake_conf = max(max_fake_conf, conf)
        
        if max_real_conf == 0 and max_fake_conf == 0:
            return True
            
        if max_fake_conf > 0.7 and max_real_conf < 0.3:
            return False
            
        return True
            
    except Exception as e:
        print(f"[ERROR] Spoofing detection failed: {e}")
        return True


# -----------------------------
# SECTION: Face encoding training
# (generate face encodings from images in student_images folder)
# -----------------------------

def train_encodings():
    """Train face encodings from student images"""
    imgList = []
    studentIds = []

    if not os.path.exists(STUDENT_IMAGES_FOLDER):
        print(f"[WARN] Student images folder not found: {STUDENT_IMAGES_FOLDER}")
        return

    for filename in os.listdir(STUDENT_IMAGES_FOLDER):
        if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            path = os.path.join(STUDENT_IMAGES_FOLDER, filename)
            img = cv2.imread(path)
            if img is not None:
                imgList.append(img)
                studentIds.append(os.path.splitext(filename)[0])

    if not imgList:
        print("[WARN] No student images found for training")
        return

    encodeList = []
    for i, img in enumerate(imgList):
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        encodes = face_recognition.face_encodings(img_rgb)
        if encodes:
            encodeList.append(encodes[0])
            print(f"[INFO] Encoded face {i + 1}/{len(imgList)}: {studentIds[i]}")
        else:
            print(f"[WARN] No face found in image: {studentIds[i]}")

    with open(ENCODE_FILE, "wb") as f:
        pickle.dump([encodeList, studentIds], f)
    print(f"[SUCCESS] Encoded {len(encodeList)} faces and saved to {ENCODE_FILE}")


# -----------------------------
# SECTION: Main attendance runtime loop
# (camera capture, spoof detection, recognition, marking logic)
# -----------------------------

def main(shared_data):
    print("[INFO] Attendance system started with 1-HOUR attendance logic.")
    frame_counter = 0

    # Initialize camera
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[ERROR] Camera not opened.")
        shared_data['running'] = False
        return
    
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    # Load encodings
    if not os.path.exists(ENCODE_FILE):
        print("[INFO] Encode file not found. Training...")
        train_encodings()

    try:
        with open(ENCODE_FILE, "rb") as f:
            encodeListKnown, studentIds = pickle.load(f)
        print(f"[INFO] Loaded {len(studentIds)} encoded faces: {studentIds}")
    except Exception as e:
        print(f"[ERROR] Failed loading EncodeFile.p: {e}")
        shared_data['running'] = False
        cap.release()
        return

    # Load spoof detection model
    try:
        spoofModel = YOLO("models/l_version_1_214.pt") if YOLO is not None else None
        if spoofModel:
            print("[INFO] Spoof detection model loaded")
    except Exception as e:
        print("[WARN] Could not load YOLO model:", e)
        spoofModel = None

    classNames = ["fake", "real"]

    # Load teacher info
    try:
        with open("current_teacher.json", "r", encoding='utf-8') as f:
            teacher_info = json.load(f)
        print(f"[INFO] Loaded teacher info: {teacher_info.get('name')} - {teacher_info.get('lecture')}")
    except Exception as e:
        print(f"[WARN] Could not load teacher info: {e}")
        teacher_info = {"username": "", "name": "", "lecture": "Unknown"}

    # NEW LOGIC: No initial marking - students start unmarked
    current_lecture = get_current_lecture()
    print(f"[INFO] Starting attendance session for {current_lecture} - 1 hour duration")
    print("[INFO] Students will be marked PRESENT when they scan their faces")
    print("[INFO] After 1 hour, unmarked students will be marked ABSENT")

    # Reset absence marking flag for new session
    shared_data['absence_marked'] = False

    # Start 1-hour timer and initialize recognition state
    attendance_active = True
    start_time = time.time()
    recognition_cooldown = 8  # seconds between recognizing the same student
    recently_recognized = {}

    try:
        while shared_data.get('running', True) and cap.isOpened():
            success, frame = cap.read()
            if not success or frame is None:
                time.sleep(0.01)
                continue

            frame_counter += 1

            elapsed_time = time.time() - start_time
            attendance_active = elapsed_time < ATTENDANCE_DURATION

            should_transfer_frame = False
            display_frame = frame.copy()

            # Show timer on screen
            remaining_time = max(0, ATTENDANCE_DURATION - elapsed_time)
            minutes = int(remaining_time // 60)
            seconds = int(remaining_time % 60)
            timer_text = f"Time: {minutes:02d}:{seconds:02d}"
            timer_color = (0, 255, 0) if attendance_active else (0, 0, 255)
            cv2.putText(display_frame, timer_text, (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, timer_color, 2)

            if not attendance_active:
                cv2.putText(display_frame, "ATTENDANCE CLOSED", (10, 60),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

            # Only process faces if attendance is still active
            if attendance_active and frame_counter % 2 == 0:
                is_real = True

                # Spoof detection (less frequent)
                if spoofModel is not None and frame_counter % 6 == 0:
                    try:
                        is_real = detect_spoofing(frame, spoofModel, 0.5, classNames)

                        current_time = time.time()
                        if 'last_spoof_check' not in shared_data:
                            shared_data['last_spoof_check'] = current_time
                            shared_data['recent_spoof_results'] = []

                        if current_time - shared_data['last_spoof_check'] >= 0.5:
                            shared_data['last_spoof_check'] = current_time
                            shared_data['recent_spoof_results'].append(is_real)
                            if len(shared_data['recent_spoof_results']) > 5:
                                shared_data['recent_spoof_results'].pop(0)

                            real_count = sum(1 for x in shared_data['recent_spoof_results'] if x)
                            is_real = real_count >= len(shared_data['recent_spoof_results']) // 2

                    except Exception as e:
                        print("[ERROR] Spoof detection pipeline:", e)
                        is_real = True

                if not is_real:
                    cv2.putText(display_frame, "SPOOF DETECTED!", (50, 100),
                                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                    should_transfer_frame = True

                # Face detection and recognition
                if is_real:
                    small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
                    small_frame = fix_image_format(small_frame)

                    if small_frame is not None:
                        face_locations = face_recognition.face_locations(small_frame, model="hog")

                        if len(face_locations) > 0:
                            should_transfer_frame = True

                            face_encodings = face_recognition.face_encodings(small_frame, face_locations)

                            for (top, right, bottom, left), encode_face in zip(face_locations, face_encodings):
                                if len(encodeListKnown) == 0:
                                    continue

                                face_distances = face_recognition.face_distance(encodeListKnown, encode_face)
                                if len(face_distances) == 0:
                                    continue

                                match_index = int(np.argmin(face_distances))
                                distance = float(face_distances[match_index])
                                candidate_id = studentIds[match_index] if match_index < len(studentIds) else None
                                print(f"[DEBUG] Best candidate: idx={match_index}, id={candidate_id}, distance={distance:.3f}")

                                # Accept match if within tolerance
                                if distance <= 0.65:
                                    student_id = candidate_id
                                else:
                                    # Draw unknown and continue
                                    t, r, b, l = top * 4, right * 4, bottom * 4, left * 4
                                    cv2.rectangle(display_frame, (l, t), (r, b), (0, 165, 255), 2)
                                    cv2.putText(display_frame, f"Unknown ({distance:.2f})", (l, t - 10),
                                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2)
                                    print(f"[DEBUG] No match within tolerance: min_distance={distance:.3f}, tol=0.65")
                                    continue

                                current_time = time.time()

                                # Check cooldown
                                if student_id in recently_recognized and current_time - recently_recognized[student_id] < recognition_cooldown:
                                    t, r, b, l = top * 4, right * 4, bottom * 4, left * 4
                                    student_info = get_student_info_from_database(student_id) or {}
                                    student_name = student_info.get('name', 'Unknown')
                                    cv2.rectangle(display_frame, (l, t), (r, b), (0, 200, 0), 2)
                                    cv2.putText(display_frame, f"{student_name} (Already marked)",
                                                (l, t - 10),
                                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 0), 2)
                                    continue

                                recently_recognized[student_id] = current_time

                                try:
                                    student_info = get_student_info_from_database(student_id)
                                    if not student_info:
                                        print(f"[WARN] Student ID {student_id} not found in database")
                                        continue

                                    print(f"[INFO] Recognized student: {student_id} - {student_info.get('name')}")

                                    # Save current student info immediately
                                    current_lecture = get_current_lecture()
                                    current_teacher = {
                                        'username': teacher_info.get('username', ''),
                                        'name': teacher_info.get('name', ''),
                                        'lecture': current_lecture
                                    }
                                    try:
                                        save_student_info_to_json(student_info, current_teacher)
                                    except Exception:
                                        print(f"[WARN] Failed to write current_student.json for {student_id}")

                                    teacher_subject = current_lecture
                                    subject_year = get_subject_year(teacher_subject)

                                    if not subject_year:
                                        print(f"[WARN] Could not find year for subject {teacher_subject}")
                                        continue

                                    success = False
                                    if student_info.get("year") == subject_year:
                                        success = mark_present(student_id, teacher_subject, teacher_info.get('username', ''))
                                        if success:
                                            print(f"[INFO] ✅ Marked {student_id} ({student_info.get('name')}) present for {teacher_subject}")
                                    else:
                                        print(f"[SKIP] {student_id} ({student_info.get('name')}) is in {student_info.get('year')} not {subject_year}")

                                    if success:
                                        save_student_info_to_json(student_info, current_teacher)

                                    # Draw rectangle on face
                                    t, r, b, l = top * 4, right * 4, bottom * 4, left * 4

                                    if success:
                                        cv2.rectangle(display_frame, (l, t), (r, b), (0, 200, 0), 3, cv2.LINE_AA)
                                        cv2.rectangle(display_frame, (l + 4, t + 4), (r - 4, b - 4), (0, 255, 0), 2, cv2.LINE_AA)
                                        cv2.putText(display_frame, f"Present: {student_info.get('name')}",
                                                    (l, t - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                                        cv2.putText(display_frame, f"ID: {student_id}",
                                                    (l, t - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                                    else:
                                        cv2.rectangle(display_frame, (l, t), (r, b), (0, 255, 255), 2, cv2.LINE_AA)
                                        cv2.putText(display_frame, f"Recog: {student_info.get('name')}",
                                                    (l, t - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

                                except Exception as e:
                                    print(f"[ERROR] Operation failed for {student_id}: {e}")
                                    import traceback
                                    traceback.print_exc()

            # Periodic transfer
            if frame_counter % TRANSFER_EVERY_N_FRAMES == 0:
                should_transfer_frame = True

            # Only encode and transfer if needed
            if should_transfer_frame:
                ret, jpg_buf = cv2.imencode('.jpg', display_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 65])
                if ret:
                    shared_data['frame_jpeg'] = jpg_buf.tobytes()
                    shared_data['frame_updated'] = time.time()

            # Cleanup cooldowns
            if frame_counter % 30 == 0:
                current_time = time.time()
                recently_recognized = {k: v for k, v in recently_recognized.items()
                                       if current_time - v < recognition_cooldown * 2}

            # NEW: Check if 1 hour has passed and mark remaining students absent
            if not attendance_active:
                # First time attendance becomes inactive (1 hour passed)
                if not shared_data.get('absence_marked', False):
                    shared_data['absence_marked'] = True
                    
                    try:
                        # Get all students for this subject/year
                        students = load_student_data()
                        subject_year = get_subject_year(current_lecture)
                        
                        if subject_year:
                            # Load current attendance records
                            records = load_attendance_records()
                            today = datetime.now().strftime("%Y-%m-%d")
                            key = f"{today}_{current_lecture}"
                            
                            # Get list of students already marked present
                            present_students = set(records.get('records', {}).get(key, {}).get('present', []))
                            
                            marked_absent_count = 0
                            for student_id, student_data in students.items():
                                # Only process students in the same year as the subject
                                if student_data.get('year') == subject_year:
                                    # If not in present list, mark as absent
                                    if student_id not in present_students:
                                        student_name = student_data.get('name', 'Unknown')
                                        success = update_attendance_in_database(
                                            student_id, student_name, current_lecture, 'Absent'
                                        )
                                        if success:
                                            marked_absent_count += 1
                            
                            print(f"[SUCCESS] ✅ Marked {marked_absent_count} students as absent after 1 hour")
                            print("[INFO] 📊 Attendance session ended. System will continue running for live view.")
                        else:
                            print(f"[WARN] Could not determine year for subject '{current_lecture}'")
                    
                    except Exception as e:
                        print(f"[ERROR] Failed to mark absent students after timeout: {e}")
                        import traceback
                        traceback.print_exc()

    except Exception as e:
        print(f"[ERROR] Main loop error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        cap.release()
        shared_data['running'] = False
        print("[INFO] Attendance system stopped.")


# -----------------------------
# SECTION: Deprecated utilities
# (older helper functions kept for compatibility / backward info)
# -----------------------------

def sync_all_totals():
    print("[INFO] sync_all_totals is deprecated")


def mark_absent_for_unmarked(lecture, marked_by="system"):
    print("[INFO] mark_absent_for_unmarked is deprecated - use automatic 1-hour logic")