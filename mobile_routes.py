"""
Mobile Attendance Routes
=========================
Handles mobile face recognition and attendance marking.

Author: AI Assistant
Version: 2.0 (Simplified)
Routes: Only 2 routes - mobile_attendance page and mobile_recognize API
"""

from flask import render_template, request, jsonify
from functools import wraps
import cv2
import numpy as np
import face_recognition
import json
import os
from datetime import datetime

# ============================================================================
# DECORATOR - Mobile Access Required
# ============================================================================

def mobile_access_required(f):
    """
    Decorator to ensure mobile access is enabled.
    Note: This is redundant since middleware already handles it,
    but kept for extra security layer.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from ip_access_control import check_mobile_access
        
        client_ip = request.remote_addr
        allowed, reason = check_mobile_access(client_ip)
        
        if not allowed:
            return jsonify({
                'success': False,
                'message': 'Mobile access is disabled',
                'reason': reason
            }), 403
        
        return f(*args, **kwargs)
    return decorated_function


# ============================================================================
# DATA LOADING FUNCTIONS
# ============================================================================

def load_student_encodings():
    """
    Load pre-computed face encodings from pickle file.
    
    Returns:
        tuple: (encode_list, student_ids) or None if file doesn't exist
    
    File Structure:
        EncodeFile.p contains:
        [
            [encoding1, encoding2, ...],  # List of face encodings
            ['IT-01', 'IT-02', ...]       # Corresponding student IDs
        ]
    """
    try:
        import pickle
        if os.path.exists('EncodeFile.p'):
            with open('EncodeFile.p', 'rb') as file:
                return pickle.load(file)
        print("[WARN] EncodeFile.p not found")
        return None
    except Exception as e:
        print(f"[ERROR] Failed to load encodings: {e}")
        return None


def load_student_data():
    """
    Load student information from JSON database.
    
    Returns:
        dict: Student data keyed by student_id
    
    Example:
        {
            "IT-01": {
                "name": "John Doe",
                "year": "2024",
                "subjects": ["Python", "DBMS"],
                ...
            }
        }
    """
    try:
        with open('student_data.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("[WARN] student_data.json not found")
        return {}
    except Exception as e:
        print(f"[ERROR] Failed to load student data: {e}")
        return {}


def load_attendance_records():
    """
    Load attendance records from JSON database.
    
    Returns:
        dict: Attendance records with structure:
        {
            "records": {
                "2024-01-15_Python": {
                    "present": ["IT-01", "IT-02"],
                    "absent": ["IT-03"],
                    "time": "10:30:00"
                }
            }
        }
    """
    try:
        with open('attendance_records.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("[WARN] attendance_records.json not found")
        return {'records': {}}
    except Exception as e:
        print(f"[ERROR] Failed to load attendance: {e}")
        return {'records': {}}


def save_attendance_records(data):
    """
    Save attendance records to JSON (atomic write).
    
    Args:
        data (dict): Attendance records to save
    
    Returns:
        bool: True if save successful
    """
    try:
        from attendance_system import atomic_write_json
        atomic_write_json('attendance_records.json', data)
        return True
    except Exception as e:
        print(f"[ERROR] Failed to save attendance: {e}")
        return False


# ============================================================================
# ATTENDANCE MARKING LOGIC
# ============================================================================

def mark_attendance(student_id, lecture):
    """
    Mark student as present in attendance records.
    
    Args:
        student_id (str): Student ID (e.g., "IT-01")
        lecture (str): Lecture/subject name
    
    Returns:
        tuple: (success: bool, message: str)
    
    Logic:
        1. Create key: "YYYY-MM-DD_LectureName"
        2. Check if already marked present today
        3. Remove from absent list if present
        4. Add to present list
        5. Save atomically
    """
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        current_time = datetime.now().strftime("%H:%M:%S")
        key = f"{today}_{lecture}"
        
        # Load current attendance
        attendance = load_attendance_records()
        
        # Initialize today's record if doesn't exist
        if key not in attendance.get('records', {}):
            attendance.setdefault('records', {})[key] = {
                'present': [],
                'absent': [],
                'time': current_time
            }
        
        record = attendance['records'][key]
        
        # Check if already marked present
        if student_id in record.get('present', []):
            return False, "Already marked present today"
        
        # Remove from absent if present there
        if student_id in record.get('absent', []):
            record['absent'].remove(student_id)
        
        # Add to present list
        if student_id not in record.get('present', []):
            record.setdefault('present', []).append(student_id)
        
        # Save changes
        if save_attendance_records(attendance):
            print(f"[SUCCESS] Marked {student_id} present for {lecture}")
            return True, "Attendance marked successfully"
        
        return False, "Failed to save attendance"
        
    except Exception as e:
        print(f"[ERROR] Mark attendance failed: {e}")
        return False, str(e)


# ============================================================================
# ROUTE REGISTRATION FUNCTION
# ============================================================================

def register_mobile_routes(app):
    """
    Register mobile attendance routes with Flask app.
    Called from app.py during initialization.
    """
    
    # ========================================================================
    # ROUTE 1: Mobile Attendance Page (HTML Interface)
    # ========================================================================
    
    @app.route('/mobile_attendance')
    @mobile_access_required
    def mobile_attendance():
        """
        Display mobile attendance page with camera interface.
        Students access this page to mark their attendance.
        
        Features:
        - Camera capture
        - Photo upload
        - Face recognition
        - Attendance confirmation
        """
        try:
            # Load current teacher/lecture info
            teacher_info = {}
            try:
                with open('current_teacher.json', 'r', encoding='utf-8') as f:
                    teacher_info = json.load(f)
            except:
                pass
            
            teacher_name = teacher_info.get('name', 'Teacher')
            lecture = teacher_info.get('lecture', 'Unknown')
            
            # Get server IP for display
            from ip_access_control import get_lan_ip
            server_ip = get_lan_ip()
            
            return render_template('mobile_attendance.html',
                                 teacher_name=teacher_name,
                                 lecture=lecture,
                                 server_ip=server_ip,
                                 client_ip=request.remote_addr)
        except Exception as e:
            print(f"[ERROR] Mobile attendance page failed: {e}")
            return f"Error loading page: {str(e)}", 500
    
    # ========================================================================
    # ROUTE 2: Face Recognition API (Backend Processing)
    # ========================================================================
    
    @app.route('/mobile_recognize', methods=['POST'])
    @mobile_access_required
    def mobile_recognize():
        """
        Process uploaded photo and recognize face.
        Called by mobile_attendance page when student submits photo.
        
        Request:
            - Content-Type: multipart/form-data
            - Field: 'image' (file)
        
        Response JSON:
            {
                "success": bool,
                "recognized": bool,
                "student_id": str,
                "student_data": dict,
                "confidence": float,
                "message": str,
                "attendance_status": str
            }
        
        Processing Steps:
            1. Validate image upload
            2. Decode image
            3. Detect faces
            4. Extract face encoding
            5. Compare with database
            6. Mark attendance if recognized
            7. Return result
        """
        try:
            # ================================================================
            # STEP 1: Validate Image Upload
            # ================================================================
            if 'image' not in request.files:
                return jsonify({
                    'success': False,
                    'message': 'No image uploaded'
                }), 400
            
            file = request.files['image']
            
            if file.filename == '':
                return jsonify({
                    'success': False,
                    'message': 'No image selected'
                }), 400
            
            # ================================================================
            # STEP 2: Decode Image
            # ================================================================
            image_bytes = file.read()
            nparr = np.frombuffer(image_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if img is None:
                return jsonify({
                    'success': False,
                    'message': 'Invalid image format'
                }), 400
            
            # Convert BGR to RGB (OpenCV uses BGR, face_recognition uses RGB)
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            
            # ================================================================
            # STEP 3: Detect Faces
            # ================================================================
            face_locations = face_recognition.face_locations(img_rgb)
            
            # No face detected
            if len(face_locations) == 0:
                return jsonify({
                    'success': True,
                    'recognized': False,
                    'message': 'No face detected in image. Please try again with better lighting.',
                    'student_id': 'No face detected',
                    'confidence': 0.0
                })
            
            # Multiple faces detected
            if len(face_locations) > 1:
                return jsonify({
                    'success': True,
                    'recognized': False,
                    'message': 'Multiple faces detected. Please ensure only one face is visible.',
                    'student_id': 'Multiple faces',
                    'confidence': 0.0
                })
            
            # ================================================================
            # STEP 4: Extract Face Encoding
            # ================================================================
            face_encodings = face_recognition.face_encodings(img_rgb, face_locations)
            
            if len(face_encodings) == 0:
                return jsonify({
                    'success': True,
                    'recognized': False,
                    'message': 'Could not encode face. Please try again.',
                    'student_id': 'Encoding failed',
                    'confidence': 0.0
                })
            
            encode_test = face_encodings[0]
            
            # ================================================================
            # STEP 5: Load Known Encodings
            # ================================================================
            data = load_student_encodings()
            
            if data is None:
                return jsonify({
                    'success': False,
                    'message': 'Face database not available. Please contact teacher.'
                }), 500
            
            encode_list_known = data[0]
            student_ids = data[1]
            
            # ================================================================
            # STEP 6: Compare Faces
            # ================================================================
            matches = face_recognition.compare_faces(
                encode_list_known, 
                encode_test, 
                tolerance=0.5  # 0.5 is good balance
            )
            face_distances = face_recognition.face_distance(
                encode_list_known, 
                encode_test
            )
            
            if len(face_distances) == 0:
                return jsonify({
                    'success': True,
                    'recognized': False,
                    'message': 'No matches found in database',
                    'student_id': 'Unknown',
                    'confidence': 0.0
                })
            
            # Find best match
            match_index = np.argmin(face_distances)
            confidence = 1.0 - face_distances[match_index]
            
            # ================================================================
            # STEP 7: Verify Match Quality
            # ================================================================
            if matches[match_index] and confidence > 0.5:
                student_id = student_ids[match_index]
                
                # Load student info
                student_data = load_student_data()
                student_info = student_data.get(student_id, {})
                
                # Get current lecture
                teacher_info = {}
                try:
                    with open('current_teacher.json', 'r', encoding='utf-8') as f:
                        teacher_info = json.load(f)
                except:
                    pass
                
                lecture = teacher_info.get('lecture', 'Unknown')
                
                # ================================================================
                # STEP 8: Mark Attendance
                # ================================================================
                success, message = mark_attendance(student_id, lecture)
                
                return jsonify({
                    'success': True,
                    'recognized': True,
                    'student_id': student_id,
                    'student_data': student_info,
                    'confidence': float(confidence),
                    'message': message if success else f'Recognized but {message}',
                    'attendance_status': 'Marked Present' if success else 'Already Present'
                })
            else:
                # Low confidence or no match
                return jsonify({
                    'success': True,
                    'recognized': False,
                    'message': f'Face not recognized (confidence: {confidence:.1%}). Please try again.',
                    'student_id': 'Unknown',
                    'confidence': float(confidence)
                })
                
        except Exception as e:
            print(f"[ERROR] Mobile recognize failed: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': f'Recognition error: {str(e)}'
            }), 500
    
    # ========================================================================
    # Registration Complete
    # ========================================================================
    print("[INFO] ✅ Mobile routes registered successfully")
    print("[INFO]    → /mobile_attendance (HTML page)")
    print("[INFO]    → /mobile_recognize (API endpoint)")


# ============================================================================
# END OF MOBILE ROUTES
# ============================================================================