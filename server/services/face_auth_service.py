import os
import json
import asyncio

try:
    import cv2
    import face_recognition
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

PROFILE_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "face_encodings.json")

def load_known_faces():
    if not os.path.exists(PROFILE_DATA_PATH):
        return {}
    with open(PROFILE_DATA_PATH, "r") as f:
        data = json.load(f)
    return {name: np.array(enc) for name, enc in data.items()}

async def authenticate_face() -> dict:
    if not HAS_CV2:
        return {"authenticated": False, "error": "Face recognition libraries not installed."}

    known_faces = load_known_faces()
    if not known_faces:
        return {"authenticated": False, "error": "No registered faces. Please run register_face.py first."}

    loop = asyncio.get_event_loop()
    
    def _capture_and_check():
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return {"authenticated": False, "error": "Could not access webcam."}
            
        ret, frame = cap.read()
        cap.release()
        
        if not ret:
            return {"authenticated": False, "error": "Failed to capture image."}
            
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        face_locations = face_recognition.face_locations(rgb_frame)
        
        if not face_locations:
            return {"authenticated": False, "error": "No face detected in webcam."}
            
        face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)
        
        if not face_encodings:
            return {"authenticated": False, "error": "Could not extract face encoding."}
            
        unknown_encoding = face_encodings[0]
        
        for name, known_enc in known_faces.items():
            results = face_recognition.compare_faces([known_enc], unknown_encoding)
            if results[0]:
                return {"authenticated": True, "user": name}
                
        return {"authenticated": False, "error": "Face not recognized."}
        
    return await loop.run_in_executor(None, _capture_and_check)
