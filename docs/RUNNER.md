# NEXUS local runner

The V2.1 runner lets the hosted Command Center inspect an explicitly approved
local directory while keeping the machine behind its firewall. The local process
initiates every HTTPS request; NEXUS never opens or connects to an inbound port.

## Pair and start

1. Open **Local Runner** in the hosted app and pair a machine.
2. Copy the one-time runner ID and token immediately.
3. Install optional runner capabilities, then in a local PowerShell terminal at
   the repository root set the values only for that process and choose the one
   approved root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-runner.txt
$env:NEXUS_URL = "https://nexus-command-center-r3h8.onrender.com"
$env:NEXUS_RUNNER_ID = "<one-time node id>"
$env:NEXUS_RUNNER_TOKEN = "<one-time runner token>"
$env:NEXUS_RUNNER_ROOT = "C:\Workspace\AI\experiments\ai-playground"
.\.venv\Scripts\python.exe scripts\nexus_runner.py
```

Do not place the runner token in Git, command-line arguments, screenshots, or the
hosted application token field. If it is exposed, disable that runner in the UI,
pair a replacement node, and use the new credentials.

## Tool boundary

The runner supports only `system_info`, `git_status`, `git_diff`, `list_files`,
`read_text_file`, `create_text_file`, `speak_text`, and `media_control`. It uses argument-array subprocess calls
with `shell=False` only for Git. Paths must remain below `NEXUS_RUNNER_ROOT` and
secret, VCS, dependency, generated, runtime database, cache, and log locations
are excluded.

`create_text_file` is approval-gated in the hosted Activity page and uses
create-only mode, so it cannot replace an existing file. There are no delete,
process-control, package-install, Git-write, Docker-write, Terraform, or arbitrary
command operations.

`speak_text` is also approval-gated. Text is limited to 2,000 characters, rate
to 120-220 words per minute, volume to 0-1, and voice selection to an installed
system voice index. Speech is generated locally through `pyttsx3`; text is not
sent to a speech service and the tool never invokes a shell or creates audio files.

`media_control` is approval-gated and Windows-only. It accepts only play/pause,
next, previous, stop, mute, volume down, and volume up. The repeat count is capped
at ten; arbitrary keys, programs, and shell commands are rejected.

`launch_app` is approval-gated. Configure it locally, for example:

```powershell
$env:NEXUS_RUNNER_APP_ALLOWLIST = '{"notepad":["C:\\Windows\\System32\\notepad.exe"]}'
```

NEXUS transmits only `notepad`; the runner rejects executable paths, extra
arguments, unknown IDs, non-absolute targets, and missing executable files.

`capture_screenshot` is approval-gated and accepts no arguments. It uses Pillow
locally to cap a PNG to 1920x1080 and 8 MB, then uploads it over the runner's
existing authenticated outbound connection while that exact job is running. The
backend stores the result as a protected Media Studio asset; no local path is sent
to the browser.

Use `--once` for a single poll during diagnostics. The default loop waits ten
seconds between polls and safely retries transient network failures.

## Optional offline wake word

The wake-word companion is a separate, local process. It does not start with
NEXUS, install itself as a service, or listen unless `--enable` is present. Install
the runner dependencies and download the selected official model once:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-runner.txt
.\.venv\Scripts\python.exe scripts\nexus_wakeword.py --download-model
.\.venv\Scripts\python.exe scripts\nexus_wakeword.py --enable --open-command-center
```

The default `hey_jarvis` detector runs locally through ONNX on 16 kHz mono PCM.
NEXUS processes one 80 ms frame at a time, does not save frames, and does not
upload audio. A detection only emits a JSON event; the optional browser action
opens an HTTPS Command Center URL (or an HTTP loopback URL). It does not execute
commands or bypass approvals. Use `Ctrl+C` to stop listening.
