"""Voice endpoint: audio -> VAD -> STT -> agent -> TTS."""

from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, HTTPException

from app import dependencies
from app.schemas import VoiceProcessRequest, VoiceProcessResponse
from voice.pipeline import NeedsRepetitionError

router = APIRouter()


@router.post("/api/voice/process", response_model=VoiceProcessResponse)
async def process_voice(request: VoiceProcessRequest) -> VoiceProcessResponse:
    """Process one voice turn.

    Two input modes: raw ``audio_base64`` (16-bit PCM frames) run through
    the full pipeline, or a pre-transcribed ``transcript`` (client-side STT
    / testing) which still passes the confidence gate.
    """
    pipeline = dependencies.get_voice_pipeline()
    settings = dependencies.get_settings()
    threshold = settings.stt_confidence_threshold

    transcript = ""
    confidence = 0.0
    try:
        if request.audio_base64:
            try:
                raw = base64.b64decode(request.audio_base64)
            except binascii.Error as exc:
                raise HTTPException(status_code=400, detail="invalid base64 audio") from exc
            # One frame per 20ms at 16kHz mono 16-bit = 640 bytes.
            frames = [raw[i : i + 640] for i in range(0, len(raw), 640) if raw[i : i + 640]]
            transcript, confidence = await pipeline.transcribe_frames(frames)
        elif request.transcript is not None:
            transcript = request.transcript
            confidence = request.confidence if request.confidence is not None else 1.0
        else:
            raise HTTPException(
                status_code=400, detail="provide audio_base64 or transcript"
            )
    except NeedsRepetitionError as exc:
        return VoiceProcessResponse(
            transcript="", confidence=0.0, needs_repetition=True, reply=str(exc)
        )

    if confidence < threshold or not transcript.strip():
        return VoiceProcessResponse(
            transcript=transcript,
            confidence=confidence,
            needs_repetition=True,
            reply="I couldn't hear that clearly — please repeat.",
        )

    agent = dependencies.get_agent()
    result = await agent.handle(transcript, actor=request.actor or "user")
    audio = await pipeline.synthesize_reply(result.reply)
    return VoiceProcessResponse(
        transcript=transcript,
        confidence=confidence,
        needs_repetition=False,
        reply=result.reply,
        audio_base64=base64.b64encode(audio).decode() if audio else "",
    )
