# mobile_camera.py - Mobile camera integration for face recognition
import cv2
import numpy as np
import base64
from io import BytesIO
from PIL import Image
import face_recognition
import pickle
import json
import os
from datetime import datetime


class MobileFaceRecognition:
    def __init__(self):
        self.known_face_encodings = []
        self.known_face_names = []
        self.load_encodings()

    def load_encodings(self):
        """Load face encodings from EncodeFile.p"""
        try:
            with open('EncodeFile.p', 'rb') as f:
                encode_list_known_with_ids = pickle.load(f)
                self.known_face_encodings, self.known_face_names = encode_list_known_with_ids
            print(f"[INFO] Loaded {len(self.known_face_names)} face encodings")
        except FileNotFoundError:
            print("[ERROR] EncodeFile.p not found. Please run train_images.py first")
        except Exception as e:
            print(f"[ERROR] Failed to load encodings: {e}")

    def process_image_from_base64(self, image_data):
        """Process base64 image data and return recognition results"""
        try:
            # Remove data URL prefix if present
            if ',' in image_data:
                image_data = image_data.split(',')[1]

            # Decode base64 image
            image_bytes = base64.b64decode(image_data)
            image = Image.open(BytesIO(image_bytes))

            # Convert to RGB if needed
            if image.mode != 'RGB':
                image = image.convert('RGB')

            # Convert PIL image to numpy array
            img_array = np.array(image)

            return self.recognize_faces_in_image(img_array)

        except Exception as e:
            print(f"[ERROR] Failed to process base64 image: {e}")
            return None

    def process_uploaded_file(self, file):
        """Process uploaded file and return recognition results"""
        try:
            # Read image file
            image = Image.open(file)

            # Convert to RGB if needed
            if image.mode != 'RGB':
                image = image.convert('RGB')

            # Convert PIL image to numpy array
            img_array = np.array(image)

            return self.recognize_faces_in_image(img_array)

        except Exception as e:
            print(f"[ERROR] Failed to process uploaded file: {e}")
            return None

    def recognize_faces_in_image(self, img_array):
        """Recognize faces in the given image array"""
        try:
            # Resize image for faster processing
            small_frame = cv2.resize(img_array, (0, 0), fx=0.25, fy=0.25)
            rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)

            # Find face locations and encodings
            face_locations = face_recognition.face_locations(rgb_small_frame)
            face_encodings = face_recognition.face_encodings(rgb_small_frame, face_locations)

            results = []

            for face_encoding in face_encodings:
                # Compare with known faces
                matches = face_recognition.compare_faces(self.known_face_encodings, face_encoding)
                face_distances = face_recognition.face_distance(self.known_face_encodings, face_encoding)

                if len(face_distances) > 0:
                    best_match_index = np.argmin(face_distances)

                    if matches[best_match_index] and face_distances[best_match_index] < 0.6:
                        student_id = self.known_face_names[best_match_index]
                        confidence = 1 - face_distances[best_match_index]

                        results.append({
                            'student_id': student_id,
                            'confidence': float(confidence),
                            'recognized': True
                        })
                    else:
                        results.append({
                            'student_id': 'Unknown',
                            'confidence': 0.0,
                            'recognized': False
                        })

            return results if results else [{'student_id': 'No face detected', 'confidence': 0.0, 'recognized': False}]

        except Exception as e:
            print(f"[ERROR] Face recognition failed: {e}")
            return [{'student_id': 'Error', 'confidence': 0.0, 'recognized': False}]


# Global instance
mobile_face_recognition = MobileFaceRecognition()