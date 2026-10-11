# Changelog

## [Unreleased]

## [0.5.0-beta.2] - 2026-10-12

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

## [0.5.0-beta.1] - 2026-10-12

### Removed
- **Text to speech** (system voices, the XTTS-v2 voice engine, My voices, audition clips, saving speech as audio) and the **live voice transform** (Seed-VC and the test effect). SpeTte is a speech-to-text program only again. The removed code and its documentation are kept in the git tag `archive/tts-live-v0.4.0-beta.14` (branch `archive/tts-live`).
- The settings of the removed parts (`tts_*`, `live_*`) are no longer read or written; old values stay unused in the settings file. The `soundfile` dependency and the Qt Multimedia module are no longer needed; the lock files were regenerated with `uv`.

## [0.4.0-beta.14] - 2026-10-11

### Added
- Text to speech: **reading aloud starts with the first finished part** (XTTS voices): the text is made in parts, and each part is played as soon as it is ready while the next is made, so a long text no longer has to be finished first. The whole speech is still checked part by part as before; saving to a file is unchanged. If a part is not ready when the previous one ends, the playing waits for it.

## [0.4.0-beta.13] - 2026-10-11

### Added
- Text to speech: the **voice preparation is remembered** (last 8 voice samples, until the voice engine stops). The same sample always gives the same result, so a repeated speech no longer analyses it again (about 0.8 s saved per speech or per text part). A changed or replaced sample is analysed again.

## [0.4.0-beta.12] - 2026-10-11

### Added
- Text to speech: **faster speech generation** (experimental, graphics card only, on by default; Settings > Text to speech > Speech quality). The speech model's token-by-token decoding is redone with a fixed-size cache and recorded as a CUDA graph; sampling is the library's own (repetition penalty, temperature, top-k, top-p, in the same order). Tested on the processor against the library with a small random model: identical tokens, identical stop-token handling, identical filtered scores. On the graphics card it checks itself against the library's generation when the voice engine starts (greedy, same tokens) and falls back by itself; the speed test shows the times with and without it.
- Text to speech: **MP3** as a format for saving the speech (Settings > Text to speech > format, and in the Save audio dialog), next to WAV, FLAC and OGG. Variable bitrate, high quality, same sample rate as the speech.

## [0.4.0-beta.11] - 2026-10-11

### Added
- Text to speech: **Test speed...** (Settings > Text to speech > Speech quality). The voice engine makes a sentence a few times with the voice chosen in the main window and says how many seconds of speech it makes per second, where the time goes (preparing the voice, the speech model, the decoder, everything else), how many sound tokens per second the speech model writes, and how long the model needed to load. It is the measurement for deciding what to speed up.

## [0.4.0-beta.10] - 2026-10-11

### Fixed
- Seed-VC: loud moments of the converted voice had flat (clipped) tops, because the vocoder cuts its output at 0.99 and the soft limiter then only lowered that flat top. The vocoder's cut is lifted, and a block whose peak would be too high is turned down as a whole (smoothly), so there are no flat tops.

## [0.4.0-beta.9] - 2026-10-11

### Changed
- Seed-VC: the loudness of the converted voice now follows the loudness of the input a little (soft input such as a whisper or a laugh no longer comes out as loud as normal speech).

## [0.4.0-beta.8] - 2026-10-11

### Changed
- Live transform: it now changes into the voice chosen in the voice list of the main window (one list for speech and for the live transform). Your own voices use their sample; a built-in XTTS voice (about 50) uses its audition clip (press ▶ Audition once, or make the clips of all voices at once in Settings > Text to speech). Settings > Live transform can still set a different voice ("the voice chosen in the main window" is the default); an older plain voice name in the settings is converted.

## [0.4.0-beta.7] - 2026-10-10

### Fixed
- Seed-VC: in quiet moments the model turned background noise into loud speech-like babble (measured: input -93 dB, output -26 dB). Where the input block is only quiet noise (below about -44 dB, fully muted below -58 dB) the converted sound is now turned down smoothly.
- Seed-VC: the first moments after starting still held the warm-up noise (the gate was open and the buffers were not empty); the stream is now reset after the warm-up.

## [0.4.0-beta.6] - 2026-10-10

### Fixed
- Live transform: a stall at the first words (1.5 s of speech dropped): the first speech blocks were checked against the normal path, which costs a block's time each. The check now runs during the warm-up (it catches the same problems, because it runs after the graph is recorded), not while you speak.
- Loud peaks of the converted voice (the model can be louder than the input) are rounded off smoothly instead of being cut flat at full scale.

## [0.4.0-beta.5] - 2026-10-10

### Fixed
- Seed-VC faster mode produced loud, saturated noise that ignored the voice. Cause: the step sizes and the sequence length that the recorded CUDA graph reads were temporary variables that were freed after the recording, so later work overwrote their memory and the graph ran with garbage. They are kept for as long as the graph lives. (This was the real cause of the scraping sound; the drift fix of beta.4 was a separate, smaller problem.)
- The faster mode now computes the first three real speech blocks both ways and compares them. If the faster mode disagrees, it is switched off at once (with a message in the status bar) and the normal result is used, so a wrong graph can no longer produce garbage.

## [0.4.0-beta.4] - 2026-10-10

### Fixed
- Live transform: a continuous scraping sound with the faster mode. The clock-drift correction of the output stretched every 20 ms piece of sound on its own, which made a small jump 50 times a second (a pure tone came out only about 40 dB cleaner than the artifacts). It now stretches continuously across the pieces and only when the reserve is really off its target (a pure tone stays 60-100 dB above the artifacts).
- Seed-VC faster mode: the check at the start now also replays the graph with new input and refuses a graph that only repeats what it recorded.

### Added
- Live transform: **Save a test recording** (Settings > Live transform): keeps the first minute of what goes into the converter and what comes out, plus the settings, in the data folder (live_test), for finding sound problems.
- Seed-VC faster mode now also covers the speech encoder and the vocoder (measured on an RTX 4060 before this: model 543 -> about 35 ms, encoder about 25 ms and vocoder about 65 ms were left). The encoder normalises its input on the graphics card instead of copying it to the processor and back, and the vocoder no longer copies from the processor's memory or waits for the card (its inverse FFT is replaced by an equivalent that is checked against the original). Each part is recorded and checked separately and falls back by itself; the speed test says which parts are on.

## [0.4.0-beta.3] - 2026-10-10

### Fixed
- Settings: the window could become taller than the screen (the OK button out of reach). Every tab now scrolls and the window never opens taller than the screen.

### Added
- Seed-VC **Faster mode** (experimental, same quality): the diffusion loop is recorded as a CUDA graph and replayed, and a mask function that made the processor wait for the graphics card at every step is replaced. It checks itself against the normal result and falls back by itself; the speed test shows the times with and without it. Also no more progress-bar line per block in the worker log.

### Changed
- The Seed-VC speed test also shows the shortest block length each quality can comfortably handle.

## [0.4.0-beta.2] - 2026-10-10

### Fixed
- Live transform: gaps that happened even in silence (the microphone and the output device run on different clocks, so the waiting sound slowly ran out). The output keeps a reserve that grows after each gap and is held steady by playing a hair slower or faster.
- Live transform (Seed-VC): speech starts and ends were cut by the loudness gate, which is now much less strict (−62 dB, stays open 0.9 s).

### Added
- Live transform: **Speed / quality** (Fast, Balanced, Best) for Seed-VC and a **Test speed** button that measures the three on your graphics card, shows the time of each stage and selects the best one that is fast enough in real time.
- **Better XTTS speech:** long text is cut into short parts (XTTS swallows words beyond its per-sentence limit, 224 characters for Hungarian), every part is checked and made again with another seed when it sounds wrong, and the parts are joined with real pauses, short fades, an even volume and a peak limiter. New *Speech quality* settings: voice stability (very steady / steady / lively), the two helpers on or off, a *What sounds wrong?* guide that applies the matching settings, and *Make comparison clips...* to hear the three stability levels side by side.

## [0.4.0-beta.1] - 2026-10-10

### Added
- *Beta: the Seed-VC engine has only been tried with random weights so far; real-voice results on an NVIDIA card are still to be confirmed.*
- **Live transform with Seed-VC** (AI voice conversion without training): install it from Settings > Live transform > Install Seed-VC... (private Python environment with PyTorch, a few checksum-verified Seed-VC source files and the models, about 8 GB in all, NVIDIA graphics card needed). The live transform then changes your voice into one of your own voices with a delay of about half a second. Whisper and the XTTS engine only step aside from the graphics card if they would not fit together with it.

## [0.3.1] - 2026-10-10

### Fixed
- On silence or background noise (record, say nothing) the recognition no longer writes an invented phrase such as "thank you very much": text that Whisper itself rates as probably not speech is dropped
- Windows: the test run no longer aborts (a reference cycle around the single-instance sockets), and the voice-engine info file is replaced reliably when Windows briefly refuses
- Switching between speech to text and text to speech reloaded the XTTS model every time: the two engines now stay on the graphics card together when the free graphics memory allows, and one steps aside only when both do not fit.
- Settings window became sluggish once the XTTS voice engine was installed: every opening counted the tens of thousands of files of the engine on the window's thread. The size is now stored and, when missing, counted in the background; the voice count no longer waits for the Windows voice list either.

### Added
- My voices: a livelier reading text (statements, a question, an exclamation, a calm ending; about 25 seconds) in Hungarian, English and German, for a clone with more natural intonation. Any other text works too: only the recording matters
- **My voices:** record a sample of your own voice (a short text is shown to read) or add a sound file, and speak with it through XTTS (no training; Hungarian included). The sample is checked for length, volume, distortion and noise, the voice is named and needs a consent tick, and it appears first in the voice list. Samples live in the data folder, so removing the voice engine keeps them.
- Status icon (tray, taskbar and window): blue when idle, red while recording, **red and blue blinking while the speech is being turned into text**, and **green for about 2.5 seconds when the text is ready** (the tooltip then says whether it was also copied to the clipboard). Works whether the window is in front or not.

### Fixed (analysis of 0.3.0)
- Closing the Settings window or quitting no longer crashes or freezes while a background job runs; a second start of SpeTte only shows the running window.
- The voice-engine installation can be retried after a failure; engine and app dependencies are pinned and hash-checked; the engine's Python and Linux's library path no longer disturb each other.
- The shortcut handles AltGr, key repeat, lost key releases and Settings being open; the first recording no longer freezes the window; the graphics memory is handed over between recognition and XTTS.
- The Windows voice list is read correctly (byte order mark); voices load in the background; the microphone is remembered by name; Copy copies the selection; temporary speech files are deleted; audition clips ignore the speed setting; a failed engine removal is reported; the graphics card can be checked again; shortcut hints in Settings.
- Data folder is `%LOCALAPPDATA%\SpeTte` on Windows (moved once from the old place); the uninstaller asks whether to delete it; third-party licence notices added; `--selfcheck` for built packages.

### Added
- System tray: minimize to the tray and closing keeps SpeTte running in the tray, two separate options in Settings, both on by default. The tray icon (and the window icon) is blue when idle and red while recording; the tray menu shows or hides the window, starts or stops recording, opens the settings and quits.
- A system-wide recording shortcut (works while any program has the focus): any key, key combination or modifier-only combination such as Ctrl+Shift, chosen in Settings by pressing the keys; either press-to-start/press-to-stop or hold-to-record (push to talk). Default: F9.
- New application and tray icons.
- Background behaviour: when SpeTte is hidden in the tray, minimized or not the window in front, each new recording replaces the previous text (one undo step brings it back) and the recognised text is copied to the clipboard automatically. Two separate options in Settings, both on by default.

- Text to speech: a voice row with a voice drop-down, ▶ Audition, 🔊 Speak and 💾 Save audio (WAV, FLAC, OGG). Reads the selected text or all text, only when you press a button, never split. System voices (Windows speech, espeak-ng on Linux) work without any download. Audition clips are made once and kept; voices can be labelled and a male/female guess comes from the sample's pitch. New Text to speech tab in Settings (the settings window now has three tabs).

- Optional XTTS-v2 voice engine for high-quality voices (Hungarian and 16 other languages, many built-in voices without reference clips): installed from Settings > Text to speech by SpeTte itself (uv from PyPI creates a private Python environment with PyTorch and the XTTS library, then the model is downloaded; the non-commercial Coqui licence must be accepted). Runs in a separate process, needs an NVIDIA graphics card (otherwise the system voices stay in use), can be removed again. Audition clips for all voices in one go and an editor for voice labels (gender, age, accent, favourite, note).

### Changed
- The in-window F9 shortcut is replaced by the system-wide shortcut (same default key).

### Added
- First version: a window with Record, Clear text, Copy to clipboard and Settings; local Whisper recognition (GPU or CPU) and an optional Google recognizer; Windows installer and Linux AppImage builds.
