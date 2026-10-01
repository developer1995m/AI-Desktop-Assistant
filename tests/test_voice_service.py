import base64
from types import SimpleNamespace

from app.services.settings import AppSettings
from app.services.voice_service import VoiceService


def make_settings(tmp_path, monkeypatch, *, base_url, model="gemini-2.5-flash"):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text(
        f"OPENAI_API_KEY=test-key\nOPENAI_BASE_URL={base_url}\nOPENAI_MODEL={model}\n",
        encoding="utf-8",
    )
    return AppSettings(env_path)


def test_gemini_transcription_sends_audio_to_configured_chat_model(
    tmp_path, monkeypatch
):
    audio_path = tmp_path / "recording.wav"
    audio_bytes = b"test wav audio"
    audio_path.write_bytes(audio_bytes)
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        message = SimpleNamespace(content="سلام، این متن تشخیص داده شد.")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    monkeypatch.setattr("app.services.voice_service.OpenAI", lambda **_kwargs: client)
    service = VoiceService(
        make_settings(
            tmp_path,
            monkeypatch,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
    )

    transcript = service.transcribe_file(audio_path)

    assert transcript == "سلام، این متن تشخیص داده شد."
    assert calls[0]["model"] == "gemini-2.5-flash"
    assert "Persian (Farsi)" in calls[0]["messages"][0]["content"][0]["text"]
    assert "Persian script" in calls[0]["messages"][0]["content"][0]["text"]
    audio_part = calls[0]["messages"][0]["content"][1]
    assert audio_part["type"] == "input_audio"
    assert audio_part["input_audio"] == {
        "data": base64.b64encode(audio_bytes).decode("ascii"),
        "format": "wav",
    }


def test_other_providers_keep_whisper_transcription_endpoint(tmp_path, monkeypatch):
    audio_path = tmp_path / "recording.wav"
    audio_path.write_bytes(b"test wav audio")
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text="recognized speech")

    client = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create))
    )
    monkeypatch.setattr("app.services.voice_service.OpenAI", lambda **_kwargs: client)
    service = VoiceService(
        make_settings(
            tmp_path,
            monkeypatch,
            base_url="https://api.openai.com/v1",
            model="gpt-4o-mini",
        )
    )

    transcript = service.transcribe_file(audio_path)

    assert transcript == "recognized speech"
    assert calls[0]["model"] == "whisper-1"
    assert calls[0]["file"][0] == "recording.wav"