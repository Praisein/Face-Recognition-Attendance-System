import cv2
import face_recognition
import pickle
import os

# Folder containing student images (inside static/)
folderPath = os.path.join('static', 'student_images')
imgList = []
studentIds = []
imageData = []  # To store (id, path) pairs

# Process each image in the folder
for filename in os.listdir(folderPath):
    if filename.lower().endswith(('.jpg', '.jpeg', '.png')):
        img_path = os.path.join(folderPath, filename)
        img = cv2.imread(img_path)

        if img is None:
            print(f"⚠️ Skipping {filename} — unable to read image.")
            continue

        # Student ID will be the filename (without extension)
        student_id = os.path.splitext(filename)[0]
        print(f"🔹 Processing image for Student ID: {student_id}")

        imgList.append(img)
        studentIds.append(student_id)
        imageData.append((student_id, img_path))

# We no longer use a database for image paths - file system is the source of truth

# Generate face encodings
def findEncodings(images, ids):
    encodeList = []
    validIds = []

    for img, sid in zip(images, ids):
        rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        encodings = face_recognition.face_encodings(rgb_img)

        if len(encodings) > 0:
            encodeList.append(encodings[0])
            validIds.append(sid)
            print(f"✅ Face encoded for: {sid}")
        else:
            print(f"⚠️ No face detected for ID: {sid}")

    return encodeList, validIds


print("\n🚀 Encoding started...")
encodeListKnown, validIds = findEncodings(imgList, studentIds)
encodeListKnownWithIds = [encodeListKnown, validIds]

# Save encodings to a pickle file for later recognition
with open("EncodeFile.p", "wb") as f:
    pickle.dump(encodeListKnownWithIds, f)

print(f"\n✅ Encoding complete! Total encoded faces: {len(validIds)}")
print("🧠 Data saved successfully to EncodeFile.p")
