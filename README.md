# SpeTte

A small speech-to-text program for Windows and Linux. One window with a text box and four buttons:

- **Record**: start recording; press again to stop and turn the speech into text. The text is added at the end of the box. The **recording shortcut** (F9 by default) does the same from any program.
- **Clear text**: removes all text. **Ctrl+Z** brings it back.
- **Copy to clipboard**: copies all text (**Ctrl+Shift+C**).
- **Settings**: voice recognition, window and shortcut.

## Settings

| Setting | What it does |
|---|---|
| Recognition | **Local, offline (Whisper)**: runs on your computer, nothing is sent anywhere. **Google**: sends the audio to Google (internet needed, at most 60 s per recording). It uses a free public key shared by all users of the speech library, which Google can limit or switch off at any time; SpeTte then says so and suggests local recognition. Settings can hold a key of your own (optional): it is kept in the system keyring (Windows Credential Manager, the Linux Secret Service), never in the settings file or the log; without a keyring the field is disabled. |
| Language | Hungarian, English (US/UK), German, French, Spanish, Italian, Portuguese (Brazil), Russian, Japanese, Korean, Chinese (Simplified). |
| Microphone | The system default or a specific input device. |
| Longest recording | A recording stops by itself after 30 to 480 seconds. |
| Model | Whisper model, from Tiny (75 MB) to Large v3 (3 GB). Models download once, on first use or with **Download now**. Small is the minimum for good Hungarian. |
| Compute device | Automatic (GPU if usable, otherwise CPU), NVIDIA GPU, or CPU. |
| GPU libraries | Windows with an NVIDIA card: a one-time download of NVIDIA's CUDA libraries (about 1 GB, checksum verified) so the graphics card can be used. |
| Window and tray | **Minimize to the tray** and **closing keeps SpeTte in the tray** are two separate checkboxes, both on by default. In the tray, the icon is **blue** when idle, **red** while recording, **red and blue blinking** while the speech is turned into text, and **green** for a moment when the text is ready (and copied); click it to show or hide the window, right-click for the menu (show/hide, start/stop recording, settings, quit). |
| In the background | When SpeTte is hidden in the tray, minimized or not the window in front, a new recording **replaces the previous text** and the result is **copied to the clipboard automatically** (two separate checkboxes, both on by default). Recording while the window is in front works as before: the text is added and nothing is copied until you press Copy. |
| Recording shortcut | A key or key combination that works **in any program**, even when SpeTte is hidden: for example `F9`, `Ctrl+Alt+R` or just `Ctrl+Shift` (two modifiers pressed together). Click the field and press the keys. Behaviour: **press to start and press again to stop**, or **hold to record and release to stop** (push to talk). A plain letter is refused so you can still type it. |

The shortcut uses [pynput](https://pypi.org/project/pynput/): it works on Windows and on Linux under X11 (and XWayland). On a native Wayland window Linux does not let programs listen to the keyboard, so the shortcut may not react there; the Record button always works. Some desktops (for example GNOME without a tray extension) have no system tray; then the tray options have no effect and closing really quits.

## Download

Releases are on the [Releases page](../../releases):

- Windows: `SpeTte-Setup-x64.exe` (installer, per user, no administrator rights) or `SpeTte-windows-x64.zip` (portable).
- Linux: `SpeTte-x86_64.AppImage` (`chmod +x`, then run) or `SpeTte-linux-x64.tar.gz`.

On Windows, allow microphone access for desktop apps (Settings > Privacy & security > Microphone).

## Run from source

```
pip install -r requirements.txt     # Linux needs portaudio19-dev to build PyAudio
python main.py
pip install -r requirements-dev.txt   # only for the tests
python -m pytest
```

## Releases and builds

GitHub Actions builds both platforms (`.github/workflows/build.yml`). `SpeTte --selfcheck` checks the bundled files and libraries of a built package (the build runs it). A pre-release is published when a tag `vX.Y.Z-beta.N` is pushed, or when a commit on `main` has `[pre-release vX.Y.Z-beta.N]` in its message. Dependencies are installed from hash-checked lock files (`requirements-windows.lock`, `requirements-linux.lock`), made from `requirements-build.in` with `uv pip compile --generate-hashes --python-platform windows|linux --python-version 3.12`.

## License

SpeTte's own code is MIT, see [LICENSE](LICENSE). It uses PyQt6, which is GPL v3, so the distributed program is subject to the GPL v3 as well. All third-party components and their licences are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
