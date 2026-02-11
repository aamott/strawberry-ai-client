import argparse
import asyncio
import logging
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path

# Allow running from a repo checkout without installing the package.
_HERE = Path(__file__).resolve()
_SRC = _HERE.parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from strawberry.voice import (  # noqa: E402
    VoiceConfig,
    VoiceCore,
    VoiceError,
    VoiceListening,
    VoiceStateChanged,
    VoiceTranscription,
    VoiceWakeWordDetected,
)


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _print_threads(prefix: str) -> None:
    names = sorted({t.name for t in threading.enumerate()})
    print(f"{prefix} threads={len(names)} {names}")


def _make_event_handler(
    state_changes: list[tuple[float, str]],
):
    """Build a VoiceCore event listener that logs to stdout."""

    def on_event(evt) -> None:
        ts = time.time()
        if isinstance(evt, VoiceStateChanged):
            print(f"[{ts:.3f}] STATE {evt.old_state.name} -> {evt.new_state.name}")
            state_changes.append((ts, f"{evt.old_state.name}->{evt.new_state.name}"))
        elif isinstance(evt, VoiceWakeWordDetected):
            print(f"[{ts:.3f}] WAKE {evt.keyword} (idx={evt.keyword_index})")
        elif isinstance(evt, VoiceListening):
            print(f"[{ts:.3f}] LISTENING")
        elif isinstance(evt, VoiceTranscription):
            print(f"[{ts:.3f}] STT {evt.text!r}")
        elif isinstance(evt, VoiceError):
            print(f"[{ts:.3f}] ERROR {evt.error}")

    return on_event


def _run_interactive(core: VoiceCore) -> None:
    """Run the interactive command loop."""
    print()
    print("Commands:")
    print("  - Press Enter to trigger wakeword (start LISTENING)")
    print("  - Type 'state' then Enter to print current state")
    print("  - Type 'threads' then Enter to list threads")
    print("  - Type 'quit' then Enter to exit")
    print()

    while True:
        cmd = input("> ").strip().lower()
        if cmd == "quit":
            break
        if cmd == "state":
            print(f"STATE={core.get_state().name}")
            continue
        if cmd == "threads":
            _print_threads("NOW")
            continue

        print("Triggering wakeword...")
        core.trigger_wakeword()


async def main() -> None:
    _setup_logging()

    parser = argparse.ArgumentParser(description="VoiceCore debug runner")
    parser.add_argument(
        "--mode",
        choices=["auto", "interactive"],
        default="auto",
        help="Run mode. 'auto' triggers wakeword on a timer; 'interactive' reads stdin.",
    )
    parser.add_argument(
        "--warmup-seconds",
        type=float,
        default=2.0,
        help="Seconds to wait after start() before triggering wakeword.",
    )
    parser.add_argument(
        "--listen-seconds",
        type=float,
        default=10.0,
        help="Seconds to wait in LISTENING before stopping.",
    )
    args = parser.parse_args()

    config = VoiceConfig(
        # Use mock wakeword so you can trigger wakeword by pressing Enter.
        wake_backend=["mock", "porcupine"],
        # Prefer silero but fall back to mock if torch/model isn't available.
        vad_backend=["silero", "mock"],
        # Keep STT/TTS mock so we don't depend on cloud/local models.
        stt_backend=["mock"],
        tts_backend=["mock"],
        wake_words=["jarvis", "strawberry"],
        sensitivity=0.5,
        sample_rate=16000,
    )

    print("Voice debug starting with config:")
    print(asdict(config))

    core = VoiceCore(config=config)

    state_changes: list[tuple[float, str]] = []
    core.add_listener(_make_event_handler(state_changes))

    started = await core.start()
    print(f"VoiceCore.start() -> {started}")
    _print_threads("AFTER start")

    try:
        if args.mode == "interactive":
            _run_interactive(core)
        else:
            print(f"Auto mode: warming up for {args.warmup_seconds:.1f}s...")
            await asyncio.sleep(args.warmup_seconds)
            print("Triggering wakeword now. Speak after this line.")
            core.trigger_wakeword()
            print(f"Waiting {args.listen_seconds:.1f}s (LISTENING should exit)...")
            await asyncio.sleep(args.listen_seconds)
            print(f"FINAL STATE={core.get_state().name}")

    finally:
        print("Stopping VoiceCore...")
        await core.stop()
        _print_threads("AFTER stop")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
