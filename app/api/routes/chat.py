"""
app/api/routes/chat.py

Mode 2 chat helpers — message ack and file upload.
"""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.utils.file_parser import extract_text_from_file

router = APIRouter(prefix="/chat", tags=["Chat"])


class ChatMessage(BaseModel):
    role: str
    text: str


class ChatMessageRequest(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list)


@router.post("/message", status_code=status.HTTP_200_OK, summary="Acknowledge Mode 2 chat message")
async def chat_message(body: ChatMessageRequest) -> dict[str, str]:
    user_messages = [m.text.strip() for m in body.messages if m.role == "user" and m.text.strip()]
    if not user_messages:
        return {"reply": "Tell me about your business idea — product, audience, and region."}

    latest = user_messages[-1]
    preview = latest if len(latest) <= 180 else f"{latest[:177]}..."

    return {
        "reply": (
            f"Got it — I've noted: \"{preview}\". "
            "Add more detail if you like, then click **Generate Blueprint** to run the 3 AI agents."
        )
    }


@router.post("/upload", status_code=status.HTTP_200_OK, summary="Upload a file and extract text for chat")
async def chat_upload_file(file: UploadFile = File(...)) -> dict[str, str]:
    try:
        content = await file.read()
        text = await extract_text_from_file(content, file.filename or "upload")
        return {"text": text}
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
