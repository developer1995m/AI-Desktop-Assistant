# Changelog

All notable changes for this project are documented here.

## [0.1.0] - Current Release

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
