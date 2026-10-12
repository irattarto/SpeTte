# Changelog

## [Unreleased]

## [0.5.0] - 2026-10-12

SpeTte is a speech-to-text program only again. Text to speech and the live voice transform were removed; the older history of the project was squashed into one commit.

### Removed
- **Text to speech** (system voices, the XTTS-v2 voice engine, My voices, audition clips, saving speech as audio) and the **live voice transform** (Seed-VC and the test effect). The code is kept outside this repository.
- The settings of the removed parts (`tts_*`, `live_*`) are no longer read or written; old values stay unused in the settings file. The `soundfile` dependency and the Qt Multimedia module are no longer needed. If you installed the voice engines earlier, their folders (`voice-engine`, `seedvc-engine`, `my_voices`, `auditions`, `live_test`) in SpeTte's data folder are no longer used and can be deleted.

### Added
- Google recognition: a clear **warning** in Settings (the audio goes to Google; the free shared key can be limited or switched off at any time) and plain **error messages** that tell apart: no connection, too many requests, a refused key (the shared one or yours), and audio that could not be understood. Each suggests local Whisper.
- An **optional Google API key** field in Settings. The key is kept only in the system keyring (Windows Credential Manager, Linux Secret Service): never in the settings file, the log or an error message. Without a keyring the field is disabled instead of storing the key in a file. "Remove key" deletes it.

### Fixed
- If the microphone stops by itself during a recording (for example a USB microphone is unplugged), the result now says that the end may be missing, instead of silently using the shorter recording.
- The model is no longer unloaded by the idle timer right after you start a new recording.
- The recognised text is no longer written to the log file when a segment is dropped as noise.

### Security
- The GPU library download now checks the files against fixed versions, SHA-256 hashes and sizes built into the program (before, the hash came from the same PyPI answer as the download address), only accepts the download address from `files.pythonhosted.org`, and refuses a download or an unpacked file that is larger than expected.
- Build: a release must now match the version in the program however it is started (before, only version tags were checked); a failed release creation or upload now fails the build; the tag name is no longer pasted into a script; tests are no longer a runtime dependency (`requirements-dev.txt`).

