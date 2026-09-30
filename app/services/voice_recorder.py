"""ضبط مستقیم صدای میکروفن به فایل WAV موقت."""

from __future__ import annotations

import struct
import tempfile
import wave
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSource, QMediaDevices


class VoiceRecorderError(RuntimeError):
    """خطای دسترسی یا ضبط میکروفن."""


def _to_mono_pcm16(raw: bytes, audio_format: QAudioFormat) -> bytes:
    """نمونه‌های خام دستگاه را به PCM شانزده‌بیتی تک‌کاناله تبدیل می‌کند."""
    sample_format = audio_format.sampleFormat()
    channel_count = audio_format.channelCount()
    bytes_per_sample = audio_format.bytesPerSample()
    frame_size = bytes_per_sample * channel_count
    usable_length = len(raw) - len(raw) % frame_size
    if usable_length == 0:
        return b""

    if sample_format == QAudioFormat.SampleFormat.Int16:
        samples = struct.iter_unpack("<h", raw[:usable_length])
        convert = lambda value: value[0]
    elif sample_format == QAudioFormat.SampleFormat.UInt8:
        samples = ((value,) for value in raw[:usable_length])
        convert = lambda value: (value[0] - 128) << 8
    elif sample_format == QAudioFormat.SampleFormat.Int32:
        samples = struct.iter_unpack("<i", raw[:usable_length])
        convert = lambda value: value[0] >> 16
    elif sample_format == QAudioFormat.SampleFormat.Float:
        samples = struct.iter_unpack("<f", raw[:usable_length])
        convert = lambda value: round(max(-1.0, min(1.0, value[0])) * 32767)
    else:
        raise VoiceRecorderError("قالب صدای میکروفن پشتیبانی نمی‌شود.")

    converted = [convert(sample) for sample in samples]
    output = bytearray()
    for offset in range(0, len(converted), channel_count):
        mono = round(sum(converted[offset : offset + channel_count]) / channel_count)
        output.extend(struct.pack("<h", max(-32768, min(32767, mono))))

    return bytes(output)


class MicrophoneRecorder(QObject):
    """ضبط صدای میکروفن پیش‌فرض و تحویل فایل WAV برای transcription."""

    recording_changed = Signal(bool)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._source: QAudioSource | None = None
        self._input = None
        self._format: QAudioFormat | None = None
        self._raw_audio = bytearray()
        self._recording = False

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start_recording(self) -> None:
        """ضبط را با قالب PCM استاندارد آغاز می‌کند."""
        if self._recording:
            return

        device = QMediaDevices.defaultAudioInput()
        if device.isNull():
            raise VoiceRecorderError("میکروفنی برای ضبط پیدا نشد.")

        requested_format = QAudioFormat()
        requested_format.setSampleRate(16_000)
        requested_format.setChannelCount(1)
        requested_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        preferred_format = device.preferredFormat()
        formats = [requested_format, preferred_format]
        if not device.isFormatSupported(requested_format):
            formats = [preferred_format]

        source = None
        audio_format = None
        last_error = QAudio.Error.NoError
        for candidate in formats:
            if not candidate.isValid():
                continue
            for use_explicit_device in (True, False):
                candidate_source = (
                    QAudioSource(device, candidate, self)
                    if use_explicit_device
                    else QAudioSource(candidate, self)
                )
                candidate_source.setBufferSize(
                    max(candidate.bytesPerFrame() * 4096, 8192)
                )
                candidate_source.stateChanged.connect(self._on_source_state_changed)
                candidate_input = candidate_source.start()
                candidate_error = candidate_source.error()
                if candidate_input is not None and candidate_error == QAudio.Error.NoError:
                    source = candidate_source
                    audio_format = candidate
                    self._input = candidate_input
                    break

                last_error = candidate_error
                candidate_source.stop()
                candidate_source.deleteLater()

            if source is not None:
                break

        if source is None or audio_format is None or self._input is None:
            self._input = None
            error_name = getattr(last_error, "name", str(last_error))
            raise VoiceRecorderError(
                f"دسترسی به میکروفن ممکن نشد ({device.description()}، خطای {error_name}). "
                "مجوز میکروفن و اتصال دستگاه را بررسی کنید."
            )

        self._raw_audio.clear()
        self._format = audio_format
        self._source = source

        self._recording = True
        self._input.readyRead.connect(self._read_audio)
        self.recording_changed.emit(True)

    def stop_recording(self) -> Path:
        """ضبط را متوقف و صدای ثبت‌شده را در WAV موقت ذخیره می‌کند."""
        if not self._recording or self._source is None or self._format is None:
            raise VoiceRecorderError("ضبط فعالی برای توقف وجود ندارد.")

        source = self._source
        self._recording = False
        source.stop()
        self._read_audio()
        source.deleteLater()
        self._source = None
        self._input = None
        audio_format = self._format
        self._format = None
        self.recording_changed.emit(False)

        path: Path | None = None
        try:
            pcm_data = _to_mono_pcm16(bytes(self._raw_audio), audio_format)
            if not pcm_data:
                raise VoiceRecorderError("صدایی ضبط نشد؛ دوباره تلاش کنید.")

            temporary = tempfile.NamedTemporaryFile(
                prefix="ai-desktop-assistant-voice-",
                suffix=".wav",
                delete=False,
            )
            path = Path(temporary.name)
            temporary.close()
            with wave.open(str(path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(audio_format.sampleRate())
                output.writeframes(pcm_data)
            return path
        except (OSError, wave.Error) as error:
            if path is not None:
                path.unlink(missing_ok=True)
            raise VoiceRecorderError(f"ذخیره صدای ضبط‌شده ممکن نشد: {error}") from error
        finally:
            self._raw_audio.clear()

    def cancel(self) -> None:
        """ضبط جاری را بدون ساخت فایل لغو می‌کند."""
        was_recording = self._recording
        self._recording = False
        if self._source is not None:
            self._source.stop()
            self._source.deleteLater()
        self._source = None
        self._input = None
        self._format = None
        self._raw_audio.clear()
        if was_recording:
            self.recording_changed.emit(False)

    def _read_audio(self) -> None:
        if self._input is not None and self._input.bytesAvailable():
            self._raw_audio.extend(bytes(self._input.readAll()))

    def _on_source_state_changed(self, _state: QAudio.State) -> None:
        source = self._source
        if (
            self._recording
            and source is not None
            and source.state() == QAudio.State.StoppedState
            and source.error() != QAudio.Error.NoError
        ):
            self.cancel()
            self.failed.emit(
                "ضبط از میکروفن متوقف شد؛ دسترسی یا اتصال میکروفن را بررسی کنید."
            )