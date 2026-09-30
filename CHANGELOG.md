# Changelog

All notable changes for this project are documented here.

## [0.1.6] - 2026-09-30

### Fixed

- Microphone recording now retries with Qt's default audio source when a packaged Windows backend returns an empty input with `NoError`.

### Testing

- Added regression coverage for the empty-input fallback path.

## [0.1.5] - 2026-09-29

### Fixed

- Microphone startup now falls back to the device's preferred audio format when the requested format cannot be opened.
- Microphone errors now include the detected device and backend error instead of one generic message.

### Testing

- Added coverage for preferred-format fallback.

## [0.1.4] - 2026-09-29

### Added

- In-app microphone recording with speech-to-text in Chat and PDF; no external audio-file selection is required.
- Temporary microphone recordings are removed after transcription.

### Testing

- Added tests for PCM conversion, WAV recording, temporary-file cleanup, and both page integrations.

## [0.1.3] - 2026-09-29

### Fixed

- Help page tabs, cards, and text now follow the selected theme, including dark mode.

### Testing

- Full test suite passes, including pixel-level verification of dark-mode help cards.

## [0.1.2] - 2026-09-28

### Added

- GitHub Windows releases now include an Inno Setup installer with a location and shortcut wizard.

### Fixed

- Memory editing uses a dedicated dialog with working save and cancel actions.
- Help and Settings text now use readable colors in dark mode.
- Chat and Dashboard layouts remain accessible in smaller windows.
- The updater supports custom installation folders and preserves Inno Setup uninstall files.
- Update-check failures explain when a private GitHub repository blocks anonymous access.

### Testing

- Full test suite passes, including Windows installation-path and updater regression tests.

## [0.1.1] - Current Release

### Added

- Voice-to-text transcription for selected audio files in both chat and PDF pages.
- Clear validation for unsupported audio formats before a transcription request is sent.
- Offline local PDF search fallback when the AI backend is unavailable, while preserving the missing API-key error in the correct order.

### Changed

- The PDF assistant now keeps the explicit missing-key message ahead of any fallback response.
- Release metadata and packaging version were updated to match the latest feature set.

### Testing

- End-to-end validation for chat and PDF UI flows, plus the full automated project suite.

## [0.1.0]

### Added

- Persian desktop UI for chat, dashboard, notes, tasks, memory, PDF questions, search, and settings.
- Streaming responses through OpenAI-compatible APIs.
- Local SQLite storage for conversations, notes, tasks, and memories.
- PDF text extraction, multi-document questions, lexical excerpt retrieval, and optional semantic retrieval.
- JSON backup and restore, including rotating automatic backups on application close.
- Task reminders with optional Windows system-tray notifications.
- Light, dark, and system theme selection with persistent UI state.
- Window geometry persistence, application icon, and keyboard shortcuts.

### Changed

- Request timeout, retry count, temperature, model, and compatible Base URL are configurable.
- Long PDF questions send selected excerpts instead of the whole document when appropriate.
- Packaged builds store application data under the user's application-data directory.
- Optional semantic PDF retrieval is separated from the base installation.

### Security

- API keys are read from the settings form, environment variables, or the local `.env` file and are not included in JSON backups.
- User-facing API errors avoid displaying the raw authentication error that may contain a key.
- AI output is displayed as text and is not executed as an operating-system command.

### Packaging

- Windows builds are produced with PyInstaller.
- The executable includes the application icon and version metadata for `0.1.0`.
- The repository includes an Inno Setup configuration for creating a Windows installer.

### Testing

- The project includes a Qt offscreen test suite covering storage, migrations, UI pages, themes, PDF handling, backups, reminders, API error handling, local streaming, and packaged self-check behavior.
