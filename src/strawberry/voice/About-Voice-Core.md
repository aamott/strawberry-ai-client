---
description: Voice interface summary and design. Use this when working on the VoiceCore or voice interface.
---
# VoiceInterface Plan

## VoiceInterface
`ai-pc-spoke/src/strawberry/ui/voice_interface/voice_interface.py`
A lightweight, voice-only wrapper that exposes SpokeCore through VoiceCore.
It is an example program showing how to wire voice interaction to sessions and skills.

**Boundary**
- VoiceInterface: Orchestrates VoiceCore + SpokeCore for a voice-only experience.
- SpokeCore: Owns sessions, skills, and chat state.
- VoiceCore: Owns wake word, STT, VAD, and TTS pipelines.

## VoiceCore
A class that can be imported by external classes. 
 - Manages voice pipelines
 - Importable by external classes
 - Can be wrapped in another UI. Doesn't manage sessions, only voice interaction. 

**Folder Structure**
`ai-pc-spoke/src/strawberry/voice/`
voice/
├── voice_core.py
├── About-Voice-Core.md # read this if you're working VoiceCore
├── config.py           # VoiceConfig dataclass
├── events.py           # VoiceEvent types and emitter
├── state.py            # VoiceState enum and transitions
├── settings_schema.py  # VOICE_CORE_SCHEMA for SettingsManager
├── settings_integration.py  # VoiceSettingsHelper
├── component_manager.py     # Backend discovery and initialization
├── pipeline_manager.py      # Dual-FSM pipeline coordinator
├── stt/
│   ├── base.py
│   ├── discovery.py
│   └── backends/
│       ├── stt_google.py
│       ├── stt_leopard.py
│       └── ...
├── tts/
│   ├── base.py
│   ├── discovery.py
│   └── backends/
│       ├── tts_google.py
│       ├── tts_orca.py
│       └── ...
├── wakeword/
│   ├── base.py
│   ├── discovery.py
│   └── backends/
│       ├── wakeword_porcupine.py
│       └── ...
├── audio/
│   ├── base.py
│   ├── discovery.py
│   └── backends/
│       ├── audio_sounddevice.py
│       └── ...
├── vad/
│   ├── base.py
│   ├── discovery.py
│   └── backends/
│       ├── vad_silero.py
│       └── vad_ten.py
└── ...

## Settings

VoiceCore registers a `voice_core` namespace with the SettingsManager on
construction (if a SettingsManager is provided). The schema is defined in
`settings_schema.py` and includes:

- **general.autostart** (checkbox, default off) — Start the voice engine
  automatically when the app launches. When off, VoiceCore is created but
  not started; it starts lazily on first voice button click.
- **stt/tts/vad/wakeword order** — Backend fallback order (PROVIDER_SELECT).
- **wakeword.phrase / sensitivity** — Wake word configuration.
- **audio.sample_rate / feedback_enabled** — Audio pipeline settings.

Backend-specific settings (e.g. `voice.stt.leopard`, `voice.tts.pocket`)
are registered dynamically by `VoiceSettingsHelper` based on discovered
backend modules.

## GUI V2 Integration

The GUI V2 uses a `VoiceService` (`ui/gui_v2/services/voice_service.py`)
as a Qt bridge between VoiceCore and the UI.

### Lifecycle

1. `run_app_integrated()` creates a VoiceCore instance (but does **not**
   start it) and passes it to `MainWindow` and `IntegratedApp`.
2. `IntegratedApp` calls `VoiceService.set_voice_core()` to wire event
   listeners and enable the voice buttons.
3. VoiceCore starts lazily:
   - If `general.autostart` is on → started during `IntegratedApp.start()`.
   - Otherwise → started on first voice button click via
     `VoiceService._ensure_started()`, which emits a `starting` signal
     so the UI shows "Voice: Starting..." during initialization.

### Voice Buttons (InputArea)

- **Record button** (tap / hold):
  - *Tap* → `trigger_wakeword()` — skips wakeword, starts listening
    immediately. VAD determines when to stop.
  - *Hold* → push-to-talk (PTT). Recording for as long as held.
  - Both auto-start VoiceCore if not yet running.
- **Voice Mode button** (toggle):
  - *On* → starts VoiceCore and listens for wake word continuously.
  - *Off* → stops VoiceCore.

### UI Status

The status bar shows the current voice state:
- **Voice: Idle** — VoiceCore available but not started.
- **Voice: Starting...** — VoiceCore is initializing.
- **Voice: Ready** — VoiceCore running, listening for wake word.
- **Voice: Listening** — Recording speech (STT active).
- **Voice: Processing** — Processing transcription.
- **Voice: Speaking** — TTS playback.
- **Voice: Unavailable** — No VoiceCore (deps missing).
- **Voice: Error** — An error occurred.

When VoiceCore is unavailable, voice buttons are disabled with a tooltip
explaining why.

## VoiceCore API

**Key functionality**
Classes can use VoiceCore to:
- Start or stop the listening pipeline.
- Trigger a wakeword detect (skipping the wakeword as if it had been said).
- Push-to-talk start/stop.
- Send text to be read out loud.
- See the current state.

**Public functions**
- `start()`: Initializes components and starts the audio/voice pipeline.
- `stop()`: Stops the pipeline and cleans up.
- `trigger_wakeword()`: Triggers a wakeword detect (skipping the wakeword as if it had been said) and starts the listening flow.
- `push_to_talk_start()` / `push_to_talk_stop()`: Manual recording control.
- `speak(text: str)`: Adds text to the speaking pipeline queue.
- `stop_speaking()`: Interrupts current TTS playback.
- `get_state()` / `state`: Returns the current VoiceState.
- `is_running()`: Whether the pipeline is active.
- `set_response_handler(handler)`: Sets the callback for transcribed text.

**Events**
- `add_listener(callback)` / `remove_listener(callback)`: Subscribe to VoiceEvent instances.
- Event types: `VoiceStateChanged`, `VoiceWakeWordDetected`, `VoiceListening`, `VoiceTranscription`, `VoiceSpeaking`, `VoiceError`, `VoiceNoSpeechDetected`, `VoiceResponse`.

**The Listening pipeline:**
1. Listens for the wakeword.
2. When detected, switches to speech-to-text.
   - VAD runs only during STT. When speech is detected, the timeout buffer refills. When speech is not detected, the buffer drains. When the timeout buffer runs out, STT stops recording and audio is redirected back to wakeword.
3. When the STT module is done, it redirects the audio back to the wakeword module.
4. Maintains a singular audio stream: wakeword and STT share one stream, and the active consumer switches based on state.

**The Speaking pipeline:**
1. Receives text to be read out loud.
2. Switches state to "speaking".
3. Reads the text out loud.
4. Switches state to "waiting".

**States:**
 - Stopped: Not listening for wakeword.
 - Idle: Pipeline started, waiting for wakeword.
 - Listening: Running STT.
 - Processing: Processing chat and TTS (wakeword can interrupt).
 - Speaking: Speaking text (wakeword can interrupt).

State transitions:
- Stopped → Idle on start().
- Idle → Listening on wakeword detect or trigger_wakeword.
- Listening → Processing after STT completes.
- Processing → Speaking when TTS begins playback.
- Speaking → Idle when TTS finishes (or Processing if another wakeword arrives).
- Idle → Stopped on stop().

Listening pipeline runs independently of the speaking pipeline. When it detects a wakeword, it stops the speaking pipeline if it is speaking.