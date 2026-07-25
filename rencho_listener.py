"""
Rencho wake-word listener.

Listens continuously and offline (via Vosk) for the word "Rencho" and opens
the Rencho avatar UI in your default browser as soon as it hears it.

Requires:
    pip install vosk sounddevice
And a Vosk model folder at ./model (see SETUP.md for the download link).

This never sends audio anywhere — recognition happens fully on-device.
"""

import json
import queue
import re
import sys
import time
import webbrowser
from pathlib import Path

import sounddevice as sd
from vosk import KaldiRecognizer, Model

BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / "model"
LOG_FILE = BASE_DIR / "rencho_listener.log"

# Served via the local HTTP server (run_rencho_server.vbs) rather than
# opened as a file:// path — Chrome does NOT reliably remember microphone
# permission for file:// pages, so it re-prompts every time. Over
# http://localhost it's treated as a stable, trustworthy origin and the
# mic permission grant sticks for good.
AVATAR_URL = "http://127.0.0.1:8765/jarvis-avatar-ui.html"

# Common ways "Rencho" gets mis-heard by speech recognizers, so the wake
# word still triggers even if it's not transcribed perfectly.
WAKE_PATTERNS = [
    r"\brencho\b",
    r"\bren\s?cho\b",
    r"\bwren\s?cho\b",
    r"\bren\s?show\b",
    r"\brancho\b",
    r"\brenshaw\b",
]
WAKE_REGEX = re.compile("|".join(WAKE_PATTERNS), re.IGNORECASE)

COOLDOWN_SECONDS = 8
SAMPLE_RATE = 16000


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def open_rencho() -> None:
    log(f"Wake word detected -> opening {AVATAR_URL}")
    webbrowser.open(AVATAR_URL)


def main() -> None:
    if not MODEL_DIR.exists():
        log(f"ERROR: Vosk model not found at {MODEL_DIR}. See SETUP.md.")
        sys.exit(1)

    log("Loading speech model...")
    model = Model(str(MODEL_DIR))
    rec = KaldiRecognizer(model, SAMPLE_RATE)

    audio_q: "queue.Queue[bytes]" = queue.Queue()

    def callback(indata, frames, time_info, status):
        if status:
            log(f"audio status: {status}")
        audio_q.put(bytes(indata))

    last_trigger = 0.0
    log("Rencho listener started. Say 'Rencho' anytime to open the avatar.")

    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=8000,
        dtype="int16",
        channels=1,
        callback=callback,
    ):
        while True:
            data = audio_q.get()
            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                text = result.get("text", "")
            else:
                partial = json.loads(rec.PartialResult())
                text = partial.get("partial", "")

            if text and WAKE_REGEX.search(text):
                now = time.time()
                if now - last_trigger > COOLDOWN_SECONDS:
                    last_trigger = now
                    open_rencho()
                rec.Reset()


if __name__ == "__main__":
    main()
