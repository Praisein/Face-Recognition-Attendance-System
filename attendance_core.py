import json
import os
import pickle
import numpy as np
import cv2
import face_recognition
from datetime import datetime
import tempfile
import shutil

# File paths
ENCODE_FILE = "EncodeFile.p"
ATTENDANCE_RECORDS_JSON = 'attendance_records.json'
STUDENT_DATA_JSON = 'student_data.json'
CURRENT_STUDENT_JSON = "current_student.json"
CURRENT_TEACHER_JSON = "current_teacher.json"


# ============================================================================
# CORE ATTENDANCE FUNCTIONS (Used by both laptop and mobile)
# ============================================================================

def load_attendance_records():
    """Load attendance records from JSON"""
    try:
        with open(ATTENDANCE_RECORDS_JSON, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {'records': {}}
    except Exception as e:
        print(f"[ERROR] Failed to load attendance records: {e}")
        return {'records': {}}


def save_attendance_records(data):
    """Save attendance records to JSON (atomic write)"""
    try:
        atomic_write_json(ATTENDANCE_RECORDS_JSON, data)
    except Exception as e:
        print(f"[ERROR] Failed to save attendance records: {e}")


def atomic_write_json(path, data):
    """Atomic JSON file write"""
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


def load_student_data():
    """Load student data from JSON - handles batch structure"""
    try:
        with open(STUDENT_DATA_JSON, 'r', encoding='utf-8') as f:
            data = json.load(f)

            # Normalize batch structure
            if isinstance(data, dict):
                # Check if batch-style structure
                def looks_like_student_dict(d):
                    if not isinstance(d, dict) or not d:
                        return False
                    first = next(iter(d.values()))
                    return isinstance(first, dict) and ('name' in first or 'year' in first)

                batch_like = any(looks_like_student_dict(v) for v in data.values())

                if batch_like:
                    # Flatten batch structure
                    all_students = {}
                    for batch_key, students in data.items():
                        if isinstance(students, dict):
                            for student_id, student_info in students.items():
                                if isinstance(student_info, dict):
                                    student_info.setdefault('batch', batch_key)
                                    student_info.setdefault('student_id', student_id)
                                    all_students[student_id] = student_info
                    return all_students

                # Wrapper format {'students': {...}}
                if 'students' in data and isinstance(data['students'], dict):
                    all_students = {}
                    for student_id, student_info in data['students'].items():
                        if isinstance(student_info, dict):
                            student_info.setdefault('student_id', student_id)
                            all_students[student_id] = student_info
                    return all_students

                # Already flat
                if all(isinstance(v, dict) and ('name' in v or 'year' in v) for v in data.values()):
                    all_students = {}
                    for student_id, student_info in data.items():
                        if isinstance(student_info, dict):
                            student_info.setdefault('student_id', student_id)
                            all_students[student_id] = student_info
                    return all_students

            return {}
    except FileNotFoundError:
        print(f"[WARN] {STUDENT_DATA_JSON} not found")
        return {}
    except Exception as e:
        print(f"[ERROR] Failed to load student data: {e}")
        return {}


def save_student_data(students_dict):
    """Save student data (preserves batch structure if present)"""
    try:
        existing = None
        if os.path.exists(STUDENT_DATA_JSON):
            try:
                with open(STUDENT_DATA_JSON, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            except Exception:
                existing = None

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
            new_data = dict(existing)
            for k in list(new_data.keys()):
                if not isinstance(new_data[k], dict):
                    new_data[k] = {}

            for sid, sinfo in students_dict.items():
                batch = sinfo.get('batch')
                target = None
                if batch and batch in new_data:
                    target = batch
                else:
                    for bkey, bval in new_data.items():
                        if isinstance(bval, dict) and sid in bval:
                            target = bkey
                            break

                if not target:
                    if len(new_data) > 0:
                        target = next(iter(new_data.keys()))
                    else:
                        target = 'students'
                        new_data[target] = {}

                entry = {k: v for k, v in sinfo.items() if k not in ('batch', 'student_id')}
                new_data.setdefault(target, {})[sid] = entry

            atomic_write_json(STUDENT_DATA_JSON, new_data)
            return

        atomic_write_json(STUDENT_DATA_JSON, {'students': students_dict})
    except Exception as e:
        print(f"[ERROR] Failed to save student data: {e}")


def get_current_lecture():
    """Get current lecture/subject from teacher data"""
    try:
        with open(CURRENT_TEACHER_JSON, "r", encoding='utf-8') as f:
            teacher_data = json.load(f)
            return teacher_data.get('lecture', 'Default')
    except:
        return 'Default'


def get_subject_year(subject_name):
    """Find which year a subject belongs to from curriculum"""
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


def update_attendance_in_database(student_id, student_name, lecture, status='Present'):
    """
    CORE FUNCTION: Mark attendance for a student
    Used by BOTH laptop and mobile attendance systems
    """
    today = datetime.now().strftime("%Y-%m-%d")
    current_time = datetime.now().strftime("%H:%M:%S")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        # Load attendance records
        records = load_attendance_records()
        key = f"{today}_{lecture}"
        rec = records.get('records', {}).get(key, {
            'present': [],
            'absent': [],
            'time': current_time
        })

        was_present = student_id in rec.get('present', [])
        was_absent = student_id in rec.get('absent', [])

        # Update attendance status
        if status == 'Present':
            if student_id not in rec['present']:
                rec['present'].append(student_id)
            if student_id in rec['absent']:
                try:
                    rec['absent'].remove(student_id)
                except ValueError:
                    pass
        else:  # Absent
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

        # Update student's total attendance count
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

        print(f"[SUCCESS] ✅ Marked {student_id} ({student_name}) as {status} for {lecture}")
        return True

    except Exception as e:
        print(f"[ERROR] Failed to update attendance for {student_id}: {e}")
        import traceback
        traceback.print_exc()
        return False


def recognize_face_and_mark_attendance(image, source="unknown"):
    """
    UNIFIED FACE RECOGNITION: Works for both laptop and mobile
    
    Args:
        image: numpy array (BGR format from OpenCV)
        source: "laptop" or "mobile" (for logging)
    
    Returns:
        dict: {
            'success': bool,
            'student_id': str or None,
            'student_name': str or None,
            'message': str,
            'status': 'present'|'not_found'|'error'
        }
    """
    try:
        print(f"[INFO] Processing face recognition from {source}")
        
        # Load face encodings
        if not os.path.exists(ENCODE_FILE):
            return {
                'success': False,
                'student_id': None,
                'student_name': None,
                'message': 'Face encodings not trained. Please train the system first.',
                'status': 'error'
            }
        
        with open(ENCODE_FILE, "rb") as f:
            encodeListKnown, studentIds = pickle.load(f)
        
        if len(encodeListKnown) == 0:
            return {
                'success': False,
                'student_id': None,
                'student_name': None,
                'message': 'No student encodings available',
                'status': 'error'
            }
        
        # Convert image to RGB
        if len(image.shape) == 3 and image.shape[2] == 3:
            img_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        else:
            img_rgb = image
        
        # Ensure image is contiguous
        if not img_rgb.flags['C_CONTIGUOUS']:
            img_rgb = np.ascontiguousarray(img_rgb)
        
        # Detect faces
        face_locations = face_recognition.face_locations(img_rgb, model="hog")
        
        if len(face_locations) == 0:
            return {
                'success': False,
                'student_id': None,
                'student_name': None,
                'message': 'No face detected in image',
                'status': 'not_found'
            }
        
        # Get face encodings
        face_encodings = face_recognition.face_encodings(img_rgb, face_locations)
        
        if len(face_encodings) == 0:
            return {
                'success': False,
                'student_id': None,
                'student_name': None,
                'message': 'Could not encode face',
                'status': 'error'
            }
        
        # Use the first detected face
        encode_face = face_encodings[0]
        
        # Compare with known faces
        face_distances = face_recognition.face_distance(encodeListKnown, encode_face)
        match_index = int(np.argmin(face_distances))
        distance = float(face_distances[match_index])
        
        print(f"[DEBUG] Best match: index={match_index}, distance={distance:.3f}")
        
        # Check if match is within tolerance
        TOLERANCE = 0.65
        if distance > TOLERANCE:
            return {
                'success': False,
                'student_id': None,
                'student_name': None,
                'message': f'Face not recognized (distance: {distance:.3f})',
                'status': 'not_found'
            }
        
        # Match found!
        student_id = studentIds[match_index]
        
        # Get student info
        students = load_student_data()
        student_info = students.get(student_id)
        
        if not student_info:
            return {
                'success': False,
                'student_id': student_id,
                'student_name': None,
                'message': f'Student {student_id} not found in database',
                'status': 'error'
            }
        
        student_name = student_info.get('name', 'Unknown')
        
        # Get current lecture and validate year
        current_lecture = get_current_lecture()
        subject_year = get_subject_year(current_lecture)
        student_year = student_info.get('year')
        
        if not subject_year:
            print(f"[WARN] Could not determine year for subject '{current_lecture}'")
        elif student_year != subject_year:
            return {
                'success': False,
                'student_id': student_id,
                'student_name': student_name,
                'message': f'{student_name} is in {student_year}, but {current_lecture} is for {subject_year}',
                'status': 'wrong_year'
            }
        
        # Mark attendance
        success = update_attendance_in_database(
            student_id, 
            student_name, 
            current_lecture, 
            'Present'
        )
        
        if success:
            # Save current student info
            try:
                with open(CURRENT_TEACHER_JSON, 'r', encoding='utf-8') as f:
                    teacher_info = json.load(f)
            except:
                teacher_info = {'name': '', 'lecture': current_lecture}
            
            save_current_student_json(student_info, teacher_info)
            
            return {
                'success': True,
                'student_id': student_id,
                'student_name': student_name,
                'message': f'{student_name} marked present',
                'status': 'present'
            }
        else:
            return {
                'success': False,
                'student_id': student_id,
                'student_name': student_name,
                'message': 'Failed to update database',
                'status': 'error'
            }
    
    except Exception as e:
        print(f"[ERROR] Face recognition failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            'success': False,
            'student_id': None,
            'student_name': None,
            'message': f'Error: {str(e)}',
            'status': 'error'
        }


def save_current_student_json(student_info, teacher_info):
    """Save current student info to JSON"""
    try:
        student_id = student_info.get('student_id')
        
        data = {
            'student_id': student_id,
            'name': student_info.get('name', ''),
            'batch': student_info.get('batch', ''),
            'year': student_info.get('year', ''),
            'selective': student_info.get('Selective', []),
            'image_path': f'static/student_images/{student_id}.png',
            'total_attendance': student_info.get('total_attendance', 0),
            'last_attendance_time': student_info.get('last_attendance_time', ''),
            'teacher_name': teacher_info.get('name', ''),
            'lecture': teacher_info.get('lecture', '')
        }
        
        atomic_write_json(CURRENT_STUDENT_JSON, data)
        print(f"[SUCCESS] Saved current_student.json for {student_id}")
        
    except Exception as e:
        print(f"[ERROR] Failed to save current student JSON: {e}")