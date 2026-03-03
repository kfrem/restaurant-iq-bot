"""
Voice transcription using faster-whisper (runs locally, no API cost).
The model is loaded once on first use and cached for subsequent calls.
"""

from faster_whisper import WhisperModel
from config import WHISPER_MODEL_SIZE

_model = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        print(f"Loading Whisper '{WHISPER_MODEL_SIZE}' model (first time only)...")
        _model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
        print("Whisper model ready.")
    return _model


def transcribe_audio(file_path: str) -> str:
    """
    Transcribe a voice note or audio file to text.
    Returns the full transcript as a single string.
    """
    model = _get_model()
    segments, _info = model.transcribe(file_path, language="en", beam_size=3)
    text = " ".join(seg.text.strip() for seg in segments)
    return text.strip()
