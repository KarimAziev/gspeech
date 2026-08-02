[![CI](https://github.com/KarimAziev/gspeech/actions/workflows/ci.yml/badge.svg)](https://github.com/KarimAziev/gspeech/actions/workflows/ci.yml) [![codecov](https://codecov.io/gh/KarimAziev/gspeech/graph/badge.svg)](https://codecov.io/gh/KarimAziev/gspeech) [![PyPI](https://img.shields.io/pypi/v/g-speech)](https://pypi.org/project/g-speech/)

# About

`gspeech` synthesizes speech with the Google Translate TTS endpoint and plays it
through a small, cross-platform [Miniaudio](https://github.com/irmen/pyminiaudio) backend.

Playback works on Raspberry Pi, Linux, macOS, and Windows.

**Table of Contents**

> - [About](#about)
>   - [Installation](#installation)
>   - [Command line](#command-line)
>   - [Python API](#python-api)
>     - [Interruption and queuing](#interruption-and-queuing)
>     - [Synthesis and cache configuration](#synthesis-and-cache-configuration)
>     - [Logging](#logging)
>     - [Errors and shutdown](#errors-and-shutdown)
>   - [Development](#development)

## Installation

```bash
pip install g-speech
```

## Command line

Speak text:

```bash
gspeech "Hello, world"
```

Select a language:

```bash
gspeech -l fr "Bonjour tout le monde"
```

Save MP3 data instead of playing it:

```bash
gspeech -o hello.mp3 "Hello, world"
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

Use `-v` for lifecycle messages, `-vv` for diagnostic logging, and `--version`
to print the installed version:

```bash
gspeech -vv "Hello, world"
gspeech --version
```

Only the CLI treats `-` as standard input. In the Python API,
`Speech("-", "en")` synthesizes a literal hyphen.

## Python API

The familiar blocking API remains available:

```python
from gspeech import Speech

result = Speech("Hello, world", "en").play()
print(result.status)
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

### Interruption and queuing

`SpeechPlayer.speak()` is non-blocking and returns a thread-safe
`SpeechHandle`. The default `replace` policy:

- interrupts the active request;
- discards older pending requests; and
- starts the newest request as soon as a download worker is available.

Cancellation is observed while downloading as well as during audio playback.
Synchronous HTTP requests cannot be forcibly killed, so an abandoned download
may continue in the bounded background download pool until its configured
timeout. The pool is bounded to avoid unbounded thread growth on small systems.

Stop active and pending speech explicitly:

```python
player.stop()
```

Wait until active playback acknowledges cancellation:

```python
player.stop(wait=True, timeout=1)
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

`SpeechPlayer` closes its audio backend and synthesizer, including injected
implementations. `Speech.write_to()` does not close an injected synthesizer
because the caller owns that standalone dependency.

### Synthesis and cache configuration

`GoogleTranslateTTSClient` owns HTTP sessions, timeouts, and the persistent
audio cache:

```python
from gspeech import GoogleTranslateTTSClient, SpeechPlayer

client = GoogleTranslateTTSClient(
    timeout=(3.05, 5.0),  # connect timeout, read timeout
    cache_ttl_seconds=7 * 24 * 60 * 60,
    cache_max_entries=500,
)

with SpeechPlayer(synthesizer=client) as player:
    player.play("Hello", "en").raise_for_error()
```

Disable persistent caching:

```python
client = GoogleTranslateTTSClient(cache_enabled=False)
```

Choose another cache directory or clear it:

```python
client = GoogleTranslateTTSClient(cache_dir="/var/cache/my-robot/gspeech")
client.clear_cache()
client.close()
```

Cache keys are SHA-256 digests and do not contain the original speech text.
Audio data is stored in a small SQLite database under the platform-specific user
cache directory by default.

### Logging

Library loggers use the `gspeech` namespace and do not configure application
logging. Applications can enable them normally:

```python
import logging

logging.basicConfig(level=logging.INFO)
logging.getLogger("gspeech").setLevel(logging.DEBUG)
```

Lifecycle logs include request IDs, language, character counts, segment numbers,
statuses, and elapsed times. They intentionally omit speech text and complete
provider URLs.

### Errors and shutdown

The public exception hierarchy is:

```text
GSpeechError
├── SynthesisError
├── PlaybackError
└── PlayerClosedError
```

Asynchronous failures are recorded in `SpeechResult`:

```python
result = player.play("Hello")
result.raise_for_error()
```

Interruption is a normal terminal status rather than an exception:

```python
from gspeech import SpeechStatus

if result.status is SpeechStatus.INTERRUPTED:
    ...
```

Use a context manager when possible. A long-lived service should call
`player.close()` during application shutdown.

Language choices for an API or user interface are available without exposing a
mutable package-global list:

```python
from gspeech import available_languages

options = available_languages()
```

## Development

Create a virtual environment, install the development extra, and run the local
CI-equivalent checks:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --editable ".[dev]"
make all
python -m coverage run -m unittest discover
python -m coverage report
```

The real provider test is opt-in and downloads audio without playing it:

```bash
GSPEECH_RUN_INTEGRATION_TESTS=1 python -m unittest tests.test_integration
```
