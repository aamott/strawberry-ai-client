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


**Key functionality**
Classes can use VoiceCore to:
- Start or stop the listening pipeline.
- Trigger a wakeword detect (skipping the wakeword as if it had been said).
- Send text to be read out loud.
- See the current state.

**Public functions**
- `start_listening()`: Starts the listening pipeline.
- `stop_listening()`: Stops the listening pipeline.
- `trigger_wakeword()`: Triggers a wakeword detect (skipping the wakeword as if it had been said) and starts the listening flow.
- `speak(text: str)`: Adds text to the speaking pipeline queue.
- `get_state()`: Returns the current state.

**Callbacks**
- `on_voice_event(event: VoiceEvent)`: Called when a voice event occurs.


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
 - Waiting: Waiting for wakeword.
 - Listening: Running STT.
 - Processing: Processing chat and TTS (wakeword can interrupt).
 - Speaking: Speaking text (wakeword can interrupt).

State transitions:
- Stopped → Waiting on start_listening.
- Waiting → Listening on wakeword detect or trigger_wakeword.
- Listening → Processing after STT completes.
- Processing → Speaking when TTS begins playback.
- Speaking → Waiting when TTS finishes (or Processing if another wakeword arrives).
- Waiting → Stopped on stop_listening.

Listening pipeline runs independently of the speaking pipeline. When it detects a wakeword, it stops the speaking pipeline if it is speaking.