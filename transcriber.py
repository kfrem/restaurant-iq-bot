"""
Voice transcription using faster-whisper (runs locally, no API cost).
The model is loaded once on first use and cached for subsequent calls.

Set WHISPER_LANGUAGE in .env to force a specific language (e.g. "en", "es", "fr").
Leave unset (default) to enable automatic language detection.
"""

from config import WHISPER_MODEL_SIZE, WHISPER_LANGUAGE

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel  # imported lazily to avoid slow startup
        print(f"Loading Whisper '{WHISPER_MODEL_SIZE}' model (first time only)...")
        _model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
        print("Whisper model ready.")
    return _model


def transcribe_audio(file_path: str) -> str:
    """
    Transcribe a voice note or audio file to text.
    Returns the full transcript as a single string.

    Language is auto-detected unless WHISPER_LANGUAGE is set in .env.
    """
    model = _get_model()
    segments, info = model.transcribe(
        file_path,
        language=WHISPER_LANGUAGE,  # None = auto-detect; "en" = force English
        beam_size=3,
    )
    text = " ".join(seg.text.strip() for seg in segments)
    if WHISPER_LANGUAGE is None and hasattr(info, "language"):
        print(f"Detected language: {info.language} (probability: {info.language_probability:.2f})")
    return text.strip()
