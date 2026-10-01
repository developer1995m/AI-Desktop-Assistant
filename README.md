# AI Desktop Assistant

A modular Windows desktop assistant built with Python and PySide6.

Current release: **0.1.7**

The `v0.1.7` GitHub release provides a portable ZIP, the updater executable, and a Windows
Setup installer with the standard location and shortcut wizard.

## Core features

* Persian desktop chat with streaming responses through OpenAI-compatible APIs.
* In-app microphone recording and speech-to-text in Chat and PDF.
* Local conversations, notes, tasks, memories, global search, reminders, and backups.
* PDF extraction and question answering across one or more open documents.
* Light, dark, and system appearance modes.
* Windows tray reminders, persistent window state, keyboard shortcuts, and a packaged executable.

## Windows requirements

The packaged application targets supported 64-bit Windows systems and does not require Python.

The source-development workflow requires Python 3.14, a writable user-data directory, and an
internet connection only when using a remote AI provider or installing dependencies.

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

The requirements file pins the tested dependency versions so a release build is reproducible.

For optional semantic PDF retrieval, install `requirements-embeddings.txt` as well. Without it,
the app uses its built-in multilingual lexical retrieval.

## Configuration

The chat page works with any OpenAI-compatible API. Configure the values in the app's Settings
page. For source development, the same values may be supplied in a `.env` file in the project
root:

```
OPENAI_API_KEY=your-key

OPENAI_MODEL=gpt-4o-mini       # optional

OPENAI_BASE_URL=https://...    # optional, for proxies or compatible services

OPENAI_TIMEOUT=60              # optional, seconds (5-600)

OPENAI_MAX_RETRIES=2           # optional (0-5)

OPENAI_TEMPERATURE=0.7         # optional (0-2)
```

System environment variables take priority over values from `.env`.

The API key is stored locally when saved through Settings (in the source `.env`, or in the
packaged app's user-data `.env`). It is not included in JSON backups. Change it by saving a new
value in Settings; remove it by clearing the API key field and saving. Never share the `.env`
file or its contents.

## Privacy and data use

The application stores conversations, notes, tasks, memories, UI state, and backups locally on
the user's computer. When an AI feature is used, relevant data is sent to the configured AI
provider: recorded microphone audio is sent for transcription, chat messages are sent for chat
responses, active memories may be included as context, and PDF text or selected PDF chunks may
be sent for PDF questions. Temporary microphone recordings are deleted after transcription. The application does not send
all local data automatically; for example, unrelated notes, tasks, and disabled memories are not
part of a chat request. JSON backups may contain sensitive conversations, notes, tasks, and
memories. Backups are local files and are not encrypted by this application.

## Release files

The authoritative application version is `0.1.10`. See [CHANGELOG.md](CHANGELOG.md) for the
current release summary. Optional semantic PDF retrieval is installed separately with
`requirements-embeddings.txt`; without it, multilingual lexical retrieval remains available.

The Windows ZIP is portable: extract it and run `AI Desktop Assistant.exe`; it does not show an
installation wizard. The Setup installer is the option for selecting an installation location,
creating shortcuts, and adding the app to Windows' installed-app list. Releases include
`AI-Desktop-Assistant-Setup.exe`, `AI-Desktop-Assistant-Windows-x64.zip` (the complete
PyInstaller onedir folder), and `AI-Desktop-Assistant-Updater.exe`. GitHub's asset API
SHA-256 digests are required for the ZIP and updater. The updater replaces the application
bundle only; user data remains under `%APPDATA%`.

## First run and network behaviour

Until a key is saved, the chat page shows a setup banner with a button that jumps straight to
Settings. The Settings page also has a **test connection** button that checks the values
currently in the form — even unsaved ones — and writes nothing to disk. Invalid numbers are
rejected with the reason instead of being saved.

Failures are translated into plain-language messages: a rejected key, an unknown model, an
exhausted quota, a timeout and a dropped connection each get their own hint instead of the raw
SDK text, and secret values never show up in those messages.

`OPENAI_TIMEOUT` bounds how long one request may take, and `OPENAI_MAX_RETRIES` how often
transient failures are retried; a 503 from the service is retried that many times with
backoff, and a request that stalls is cut at the configured deadline.

Window size and position are remembered in `data/ui_state.json` (inside the user data folder
for a packaged build). A saved position that no longer lands on a connected screen is ignored,
so the window can never open off-screen.

When `OPENAI_BASE_URL` points at a service on this machine (`127.0.0.1`, `localhost`, `::1`),
the app skips the system HTTP proxy for that request. Windows-based proxy/VPN clients are
otherwise applied to every address, and a locally served model (Ollama, LM Studio) would fail
with an unrelated 503.

## Tests

```bash
.venv\Scripts\python.exe -m pytest tests
```

Tests run headlessly through the Qt `offscreen` platform.

## Build a Windows executable

```bat
build.bat
```

The script runs the tests, packages the app with PyInstaller and verifies the result. It also
builds the standalone updater and creates the complete update assets under `release\`:
`AI-Desktop-Assistant-Windows-x64.zip` and `AI-Desktop-Assistant-Updater.exe`. If Inno Setup is
installed, it also creates `installer\AI-Desktop-Assistant-Setup.exe`; this is the Windows
installer with the location and shortcut wizard. To package the application manually:

```bash
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean ai_desktop_assistant.spec
```

`main.py --self-check` builds the window, opens a generated PDF and prints `self-check: OK`
without showing any UI; it is what verifies a packaged build (and works in CI).

To publish an update, set `APP_VERSION` in `app/version.py`, commit the change, then push a
matching `v<version>` tag (for example, `v0.2.0`). The Windows Release workflow runs tests,
builds the app and updater, creates the full onedir bundle and Setup installer, then publishes
all three assets.
The updater check and install action are available only in the frozen Windows application.

When the app runs from a bundle, the folder next to the executable may be read-only, so the
database and `.env` move to the user data folder (`%APPDATA%\AI Desktop Assistant\`). Runs from
source keep using the project folder, so tests and development are unaffected.

## Local data

Conversations are stored in a local SQLite database at `data/assistant.db`, and the last
conversation is restored the next time the app starts. While the chat page is open, the
sidebar lists recent chats: pick one to reopen it, or use `×` to delete it for good.

## PDF Assistant

The PDF page reads documents with PyMuPDF (up to 80 pages and 120,000 characters of text
each), shows 6,000 characters of the extracted text next to the conversation, and answers
your questions from every document you have open. **Add PDF** takes one file or several at
once; each open document gets a tab above the preview, where clicking switches the preview
and `✕` closes it. Short documents go to the model in full; a longer one is split into
overlapping chunks and only the parts whose words match your question are sent — the status
line says so while the answer streams. A generic question (like **summarise this**) has nothing
to match, so evenly spread excerpts from the whole document are sent instead. With several
documents open the text budget is divided between them, each document arrives in its own
labelled block, and a document that contains none of the question's words is replaced by a
one-line note instead of wasting the budget on unrelated text.

Encrypted, image-only and unreadable files are reported instead of failing silently, and a
PDF that fails to open leaves the documents already open untouched. PDF questions are kept in
memory only and never mixed into the saved chat history.

On a generated 60-page, 120,000-character document, asking about one topic sent 2,300
characters (2.3% of the file) and never included the unrelated sections. With two 12,000
character PDFs open, a question about one of them sent 6,300 characters instead of 24,100 and
reduced the unrelated document to its 132-character note.

Word matching happens in the language of the document: a Persian question about an English
PDF finds no matching section, so the whole document (or spread excerpts) is sent as a
fallback. Semantic retrieval is enabled when `sentence-transformers` and its multilingual
model are available. The model is loaded lazily on the first long-document query; when the
package or model is unavailable, the existing multilingual lexical retrieval is used. Set
`PDF_EMBEDDING_MODEL` to select another compatible model.

## Search

`Ctrl+K` (or the button in the header) opens one search box over everything stored locally:

conversations and their messages, notes, tasks and memories. Results are grouped per section
with a short snippet around the match, and picking one opens it — the conversation, the note in
its editor, or the tasks/memory page. `%` and `_` are treated as plain text instead of SQL
wildcards, and each section is capped so the list stays readable.

## Backup and restore

The Settings page has a **Data** section: **Back up** writes every conversation, note, task and
memory into one JSON file (versioned with the format name, so an alien file is rejected instead
of half-imported). **Restore** shows what the file contains and asks for confirmation before it
replaces the current data; the whole import runs in a single transaction, so a broken file
leaves the database untouched. After a restore the sidebar, dashboard, chat, notes, tasks and
memory pages reload from the database.

Closing the app also writes an automatic backup into a `backups/` folder next to the database
(`data/backups/` for source runs, inside the user data folder for packaged ones). Only the five
newest copies are kept, and an empty database produces no file at all. A failing backup never
blocks the app from closing.

Notes, tasks and memories live in the same database. Memory holds durable facts about you
(up to 400 characters each): every enabled memory is appended to the system prompt of each
request, so the model keeps that context without you repeating it. Disabled memories are
stored but never sent, and the chat page shows a chip with the current count.

## Task reminders

Tasks can carry a due date. The chat page header shows a chip while any task is due today or
overdue, clicking it opens the Tasks page, and a tray reminder repeats every 15 minutes while
the app runs. The system notification is only raised when the window is not the active one —
no popup while you are already looking at the app — and the same summary is never notified
twice in a row. If Windows reports no system tray, the app skips the tray entirely instead of
crashing (asking Qt for tray state without an application instance faults on Windows, so the
answer is only requested when it is safe).

Note tags filter the Notes page, and the Tasks page filters by due state (overdue / today /
soon / later) with nearest due date sorting first regardless of priority.

## Progress

* Phase 1: project foundation and the first application window.
* Phase 2: main window, sidebar and page routing.
* Phase 3: AI chat page with streaming replies, stop and a new-conversation action.
* Phase 4: conversation history persisted in SQLite and restored on startup.
* Phase 5: recent chats listed in the sidebar with switching and deletion.
* Phase 6: live dashboard with conversation stats and recent-chat shortcuts.
* Phase 7: settings page for API key, model and base URL, saved to `.env`.
* Phase 8: Notes page with create, edit and delete backed by the same SQLite store.
* Phase 9: Tasks page with priorities, completion state and status filters.
* Phase 10: Memory page whose enabled facts are injected into every chat prompt.
* Phase 11: PDF Assistant that extracts a document's text and answers questions about it.
* Phase 12: PyInstaller packaging with a self-check mode and per-user data paths.
* Phase 13: JSON backup and restore of every data type, with confirmation and validation.
* Phase 14: global search across conversations, notes, tasks and memories.
* Phase 15: automatic rotating backups on exit, plus GitHub Actions CI.
* Phase 16: PDF answers built from relevance-selected excerpts instead of the whole file.
* Phase 17: several PDFs open at once with tabs and questions spanning all of them.
* Phase 18: first-run guidance, explained network errors, connection test, request timeout
  and retries, remembered window geometry and an application icon.
* Phase 19: note tags with filtering, task due dates with overdue/today filters and header
  reminder chip, system-tray reminder notifications, markdown export of a conversation,
  selectable/copyable chat bubbles, navigation shortcuts, temperature and a model picker,
  fully Persian UI, Inno Setup installer, and TF-IDF weighted PDF excerpt ranking.

## Project layout

```text
main.py                     entry point (and --self-check mode)

app/services/               settings, chat, PDF, storage, backup, paths, ui_state

app/ui/pages/               dashboard, chat, notes, tasks, pdf, memory, settings

app/ui/widgets/             sidebar, conversation list, chat bubbles, search dialog, document tabs

app/ui/tray.py              system-tray reminder with deduplicated notifications

app/ui/workers.py           background workers: streaming replies and the connection test

assets/app_icon.ico         app/window/executable icon

assets/app_icon.png         256px preview of the same icon

tools/make_icon.py          draws the icon (so the asset is reproducible, not a mystery binary)

tests/                      pytest suite running headlessly on the offscreen platform

ai_desktop_assistant.spec   PyInstaller recipe

installer.iss               Inno Setup installer script (menu + desktop shortcuts, clean uninstall)

build.bat                   tests + build + self-check (+ installer when Inno Setup is installed)
```

## Continuous integration

`.github/workflows/ci.yml` runs the test suite on Windows and then packages the app with
PyInstaller, verifying the artifact through `--self-check` before uploading it as a build
artifact.
