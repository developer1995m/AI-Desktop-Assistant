"""تست ضبط مستقیم میکروفن و آماده‌سازی فایل WAV برای transcription."""

import struct
import wave

from PySide6.QtCore import QObject, Signal
from PySide6.QtMultimedia import QAudio, QAudioFormat

from app.services import voice_recorder
from app.services.voice_recorder import MicrophoneRecorder, _to_mono_pcm16
from app.ui.workers import VoiceTranscriptionWorker


def audio_format(sample_format, channels):
    result = QAudioFormat()
    result.setSampleRate(48_000)
    result.setChannelCount(channels)
    result.setSampleFormat(sample_format)
    return result


def test_float_stereo_audio_converts_to_clamped_mono_pcm16():
    stereo = struct.pack("<ffff", -1.0, 1.0, 0.25, 0.75)

    converted = _to_mono_pcm16(
        stereo,
        audio_format(QAudioFormat.SampleFormat.Float, 2),
    )

    assert struct.unpack("<hh", converted) == (0, 16_384)


def test_recorder_writes_valid_mono_wav_from_microphone(qt_app, monkeypatch, tmp_path):
    fmt = audio_format(QAudioFormat.SampleFormat.Int16, 2)
    captured_input = struct.pack("<hhhh", 1000, 3000, -1000, 1000)

    class FakeDevice:
        def isNull(self):
            return False

        def isFormatSupported(self, _format):
            return False

        def preferredFormat(self):
            return fmt

    class FakeInput(QObject):
        readyRead = Signal()

        def __init__(self):
            super().__init__()
            self.data = captured_input

        def bytesAvailable(self):
            return len(self.data)

        def readAll(self):
            data, self.data = self.data, b""
            return data

    class FakeSource(QObject):
        stateChanged = Signal(object)

        def __init__(self, *_args):
            super().__init__()
            self.input = FakeInput()

        def setBufferSize(self, _size):
            pass

        def start(self):
            return self.input

        def error(self):
            return QAudio.Error.NoError

        def stop(self):
            pass

        def deleteLater(self):
            pass

    monkeypatch.setattr(
        voice_recorder.QMediaDevices,
        "defaultAudioInput",
        staticmethod(lambda: FakeDevice()),
    )
    monkeypatch.setattr(voice_recorder, "QAudioSource", FakeSource)

    recorder = MicrophoneRecorder()
    recorder.start_recording()
    assert recorder.is_recording

    path = recorder.stop_recording()
    try:
        with wave.open(str(path), "rb") as recorded:
            assert recorded.getnchannels() == 1
            assert recorded.getsampwidth() == 2
            assert recorded.getframerate() == 48_000
            assert struct.unpack("<hh", recorded.readframes(2)) == (2000, 0)
    finally:
        path.unlink(missing_ok=True)


def test_recorder_falls_back_to_preferred_device_format(monkeypatch):
    preferred = audio_format(QAudioFormat.SampleFormat.Int16, 2)

    class FakeDevice:
        def isNull(self):
            return False

        def isFormatSupported(self, audio_format):
            return audio_format.sampleRate() == 16_000

        def preferredFormat(self):
            return preferred

        def description(self):
            return "Test microphone"

    class FakeInput:
        class _Signal:
            def connect(self, _callback):
                pass

        readyRead = _Signal()

    class FakeSource:
        def __init__(self, _device, audio_format, _parent):
            self.audio_format = audio_format
            self.input = FakeInput()

        def setBufferSize(self, _size):
            pass

        def start(self):
            return None if self.audio_format.sampleRate() == 16_000 else self.input

        def error(self):
            return QAudio.Error.OpenError if self.audio_format.sampleRate() == 16_000 else QAudio.Error.NoError

        def stop(self):
            pass

        def deleteLater(self):
            pass

        class _Signal:
            def connect(self, _callback):
                pass

        stateChanged = _Signal()

    monkeypatch.setattr(
        voice_recorder.QMediaDevices,
        "defaultAudioInput",
        staticmethod(lambda: FakeDevice()),
    )
    monkeypatch.setattr(voice_recorder, "QAudioSource", FakeSource)

    recorder = MicrophoneRecorder()
    recorder.start_recording()

    assert recorder.is_recording
    assert recorder._format == preferred


def test_transcription_worker_deletes_recording_after_failure(tmp_path):
    path = tmp_path / "recording.wav"
    path.write_bytes(b"temporary audio")

    class FailingVoiceService:
        def transcribe_file(self, _path):
            raise RuntimeError("transcription failed")

    errors = []
    worker = VoiceTranscriptionWorker(FailingVoiceService(), path)
    worker.failed.connect(errors.append)

    worker.run()

    assert errors == ["transcription failed"]
    assert not path.exists()