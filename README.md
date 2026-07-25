# About

`gspeech` synthesizes speech with the Google Translate TTS endpoint and plays it
through a small, cross-platform [Miniaudio](https://github.com/irmen/pyminiaudio) backend. Playback works on Raspberry
Pi, Linux, macOS, and Windows.

**Table of Contents**

> - [About](#about)
>   - [Installation](#installation)
>   - [Usage](#usage)
>     - [Command line](#command-line)
>     - [Python API](#python-api)

## Installation

```bash
pip install gspeech
```

## Usage

### Command line

Speak text:

```bash
gspeech "Hello, world"
```

Select a language:

```bash
gspeech --lang fr "Bonjour tout le monde"
```

Save MP3 data instead of playing it:

```bash
gspeech --output hello.mp3 "Hello, world"
```

Read and speak standard input one line at a time:

```bash
some-command | gspeech -
```

The module entry point is equivalent:

```bash
python -m gspeech "Hello, world"
```

Press `Ctrl+C` to interrupt CLI playback.

### Python API

The familiar blocking API remains available:

```python
from gspeech import Speech

Speech("Hello, world", "en").play()
```

Use a shared `SpeechPlayer` for interruptible application playback:

```python
from gspeech import SpeechPlayer

with SpeechPlayer() as player:
    first = player.speak("This announcement is no longer relevant.")

    # The default "replace" policy interrupts first and plays second.
    second = player.speak("Turn right now.")

    print(first.wait().status)  # SpeechStatus.INTERRUPTED
    print(second.wait().status)  # SpeechStatus.COMPLETED
```

Stop active and pending speech explicitly:

```python
player.stop()
```

Queue speech instead of replacing it:

```python
from gspeech import SpeechPolicy

player.speak("First", policy=SpeechPolicy.ENQUEUE)
player.speak("Second", policy=SpeechPolicy.ENQUEUE)
```

Always close a long-lived player, either explicitly or with a context manager:

```python
player.close()
```
