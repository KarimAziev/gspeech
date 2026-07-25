# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog], and version identifiers follow
[PEP 440].

## [0.1.0] - 2026-07-25

Initial release of the `g-speech` distribution.

### Added

- Cross-platform MP3 playback through Miniaudio on Raspberry Pi, Linux, macOS,
  and Windows.
- Interruptible speech playback with a non-blocking `SpeechPlayer`, cancellable
  request handles, observable lifecycle states, and deterministic shutdown.
- Replace and enqueue policies for interrupting current speech or preserving
  queued requests.
- Bounded background synthesis so replacement requests can proceed without
  unbounded worker growth.
- Google Translate TTS synthesis with configurable connection and read timeouts,
  per-thread HTTP sessions, response validation, and explicit resource cleanup.
- A persistent SQLite audio cache with configurable expiration and capacity,
  least-recently-used pruning, explicit clearing, and an option to disable it.
- A command-line interface for speaking text, reading standard input, selecting
  a language, writing MP3 output, controlling log verbosity, and reporting the
  installed version.
- Text normalization and segmentation at natural boundaries for provider-sized
  requests.
- A blocking `Speech` API for playback and writing synthesized audio to files or
  binary streams.
- Public protocols for injecting custom synthesizers, HTTP sessions, caches, and
  audio backends.
- Inline type information with a `py.typed` marker for downstream type checkers.
- Support for Python 3.10 through 3.14.

### Changed

- Replaced the `pygame-ce` audio dependency with the substantially smaller
  Miniaudio backend.
- Published the project under the `g-speech` distribution name while retaining
  the `gspeech` Python import package and command-line executable.

### Fixed

- Closed every SQLite connection deterministically so temporary and persistent
  cache databases are not left locked on Windows.
- Propagated decoder and playback-device failures as library exceptions instead
  of allowing failures to escape from the audio callback thread.

### Security

- Stored cache entries under opaque SHA-256 keys rather than the original speech
  text.
- Kept spoken text and complete provider URLs out of lifecycle and diagnostic
  logs.
- Added secretless PyPI publishing with short-lived trusted-publishing
  credentials and package attestations.

[Keep a Changelog]: https://keepachangelog.com/en/1.1.0/
[PEP 440]: https://peps.python.org/pep-0440/
[0.1.0]: https://github.com/KarimAziev/gspeech/tree/v0.1.0
