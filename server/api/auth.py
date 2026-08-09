from fastapi import APIRouter
from server.services.face_auth_service import authenticate_face

router = APIRouter()

@router.get("/face")
async def face_auth():
    result = await authenticate_face()
    return result
