import os
import json

def register_user(name: str):
    try:
        import cv2
        import face_recognition
        import numpy as np
    except ImportError:
        print("Required libraries (cv2, face_recognition) are not installed.")
        return

    cap = cv2.VideoCapture(0)
    print("Looking for face... please look at the camera.")
    ret, frame = cap.read()
    cap.release()

    if not ret:
        print("Error: Could not read from webcam.")
        return

    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    face_locations = face_recognition.face_locations(rgb_frame)

    if not face_locations:
        print("Error: No face detected.")
        return

    face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)
    
    if not face_encodings:
        print("Error: Could not extract face encoding.")
        return

    encoding = face_encodings[0].tolist()

    data_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data")
    os.makedirs(data_dir, exist_ok=True)
    file_path = os.path.join(data_dir, "face_encodings.json")

    data = {}
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            data = json.load(f)
            
    data[name] = encoding
    
    with open(file_path, "w") as f:
        json.dump(data, f)
        
    print(f"Success: Face registered for {name}!")

if __name__ == "__main__":
    name = input("Enter your name: ")
    register_user(name)
