# Security Policy

## Supported versions

The most recent release receives security fixes. Please make sure you're on the
[latest release](https://github.com/oriaharo-creator/YouTube-to-Smash-Ultimate/releases/latest)
before reporting an issue.

| Version | Supported |
|---|---|
| Latest release | ✅ |
| Older releases | ❌ |

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Instead, report it privately through GitHub's
[private vulnerability reporting](https://github.com/oriaharo-creator/YouTube-to-Smash-Ultimate/security/advisories/new)
(on the repo: **Security → Report a vulnerability**). This keeps the report
confidential until a fix is ready and routes it straight to the maintainers.

Please include:

- A description of the issue and its potential impact.
- Steps to reproduce, or a proof of concept.
- The version/build affected and your OS.

We'll acknowledge your report as soon as we can, keep you updated on progress, and
credit you in the release notes when a fix ships (unless you'd prefer to remain
anonymous).

## Scope and good to know

This is a desktop tool that downloads audio, shells out to bundled command-line
programs, and can upload files to a device over FTP on your local network. Areas
especially worth scrutiny:

- **Tool downloads** (`tooldl.py`): components are fetched over HTTPS from
  upstream sources. Reports about download integrity or substitution are welcome.
- **Subprocess handling** (`backend.py`): the app invokes FFmpeg, VGAudio, and
  nus3audio. Arguments are passed as argument lists (never a shell string).
- **FTP upload**: plain FTP on the local network to a homebrew Switch FTP server,
  by design — credentials are not used and nothing is sent to the internet.

The app ships **no copyrighted audio** and sends no telemetry. Thank you for
helping keep users safe.
