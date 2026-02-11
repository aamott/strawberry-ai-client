"""Voice processing engine - manages STT/TTS/VAD/WakeWord pipelines.

This module provides a clean API for voice processing.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import re
import threading
import time
from typing import TYPE_CHECKING, Any, Callable, List, Optional

import numpy as np

from .component_manager import VoiceComponentManager
from .config import VoiceConfig
from .events import (
    VoiceError,
    VoiceEvent,
    VoiceEventEmitter,
    VoiceListening,
    VoiceNoSpeechDetected,
    VoiceResponse,
    VoiceSpeaking,
    VoiceStateChanged,
    VoiceTranscription,
    VoiceWakeWordDetected,
)
from .pipeline_manager import VoicePipelineManager
from .settings_integration import VoiceSettingsHelper
from .state import VoiceState, VoiceStateError, can_transition

if TYPE_CHECKING:
    from strawberry.shared.settings import SettingsManager

logger = logging.getLogger(__name__)


# =============================================================================
# VoiceCore
# =============================================================================


class VoiceCore:
    """Voice processing engine."""

    def __init__(
        self,
        config: VoiceConfig,
        response_handler: Optional[Callable[[str], str]] = None,
        settings_manager: Optional["SettingsManager"] = None,
    ):
        """Initialize VoiceCore."""
        self._config = config
        self._response_handler = response_handler
        self._settings_manager = settings_manager

        # Pipeline manager (dual FSM coordinator)
        self._pipeline = VoicePipelineManager()
        self._session_counter = 0

        # Legacy state lock for backward compat during transition
        self._state_lock = threading.Lock()

        # Sub-components
        self.event_emitter = VoiceEventEmitter()
        self.component_manager = VoiceComponentManager(config, settings_manager)
        self.settings_helper = VoiceSettingsHelper(
            config,
            settings_manager,
            self.component_manager,
            self._on_component_settings_changed,
        )

        # Register settings (if manager provided)
        if settings_manager:
            self.settings_helper.register()

        # Audio buffering
        self._recording_buffer: List[np.ndarray] = []
        self._recording_start_time: float = 0
        self._max_recording_duration: float = 30.0
        self._last_frame_time: float = 0
        self._frame_timeout: float = 5.0

        # PTT state
        self._ptt_active = False

        # Threads
        self._watchdog_thread: Optional[threading.Thread] = None
        self._watchdog_stop = threading.Event()
        self._speak_queue: queue.Queue[str] = queue.Queue(maxsize=10)
        self._speak_thread: Optional[threading.Thread] = None
        self._speak_stop = threading.Event()
        self._current_speech_text: Optional[str] = None

        # Re-init tracking
        self._reinit_pending = False
        self._pending_changes: set[str] = set()
        self._pending_changes_lock = threading.Lock()

    # -------------------------------------------------------------------------
    # Public API: State
    # -------------------------------------------------------------------------

    def get_state(self) -> VoiceState:
        """Thread-safe state getter."""
        return self._pipeline.pipeline_state

    @property
    def state(self) -> VoiceState:
        """Thread-safe state property."""
        return self._pipeline.pipeline_state

    @property
    def session_id(self) -> str:
        return self.event_emitter._session_id

    def is_running(self) -> bool:
        return self._pipeline.is_running

    def is_push_to_talk_active(self) -> bool:
        return self._ptt_active

    # -------------------------------------------------------------------------
    # Public API: Events
    # -------------------------------------------------------------------------

    def add_listener(self, listener: Callable[[VoiceEvent], Any]) -> None:
        self.event_emitter.add_listener(listener)

    def remove_listener(self, listener: Callable[[VoiceEvent], Any]) -> None:
        self.event_emitter.remove_listener(listener)

    # -------------------------------------------------------------------------
    # Public API: Lifecycle
    # -------------------------------------------------------------------------

    async def start(self) -> bool:
        """Start VoiceCore."""
        if self._pipeline.is_running:
            logger.warning("VoiceCore already running")
            return False

        try:
            loop = asyncio.get_running_loop()
            self.event_emitter.set_event_loop(loop)

            # Initialize components
            await self.component_manager.initialize()

            # New Session
            self._session_counter += 1
            sid = f"voice-{self._session_counter}"
            self.event_emitter.set_session_id(sid)

            # Start Audio Stream
            stream = self.component_manager.components.audio_stream
            if stream:
                stream.subscribe(self._on_audio_frame)
                stream.start()
                logger.info(f"Listening for wake words: {self._config.wake_words}")

            # Start Workers
            self._speak_stop.clear()
            self._speak_thread = threading.Thread(target=self._speak_loop, daemon=True)
            self._speak_thread.start()

            self._watchdog_stop.clear()
            self._watchdog_thread = threading.Thread(
                target=self._watchdog_loop, daemon=True
            )
            self._watchdog_thread.start()

            # Start pipeline (transitions both FSMs to ready state)
            self._pipeline.start()
            self.event_emitter.emit(
                VoiceStateChanged(old_state=VoiceState.STOPPED, new_state=VoiceState.IDLE)
            )
            logger.info("VoiceCore started")
            return True

        except Exception as e:
            logger.error(f"Failed to start VoiceCore: {e}")
            self.event_emitter.emit(VoiceError(error=str(e), exception=e))
            return False

    async def stop(self) -> None:
        """Stop VoiceCore."""
        if not self._pipeline.is_running:
            return

        old_state = self.state

        # Stop threads
        self._watchdog_stop.set()
        if self._watchdog_thread:
            self._watchdog_thread.join(timeout=1.0)

        self.stop_speaking()
        self._speak_stop.set()
        if self._speak_thread:
            self._speak_thread.join(timeout=1.0)

        # Stop pipeline (resets both FSMs)
        self._pipeline.stop()
        self.event_emitter.emit(
            VoiceStateChanged(old_state=old_state, new_state=VoiceState.STOPPED)
        )

        # Cleanup components
        if self.component_manager.components.audio_stream:
            self.component_manager.components.audio_stream.unsubscribe(
                self._on_audio_frame
            )

        await self.component_manager.cleanup()
        logger.info("VoiceCore stopped")

    # -------------------------------------------------------------------------
    # Public API: Listening Control
    # -------------------------------------------------------------------------

    def start_listening(self) -> None:
        if not self._pipeline.is_running:
            logger.warning("VoiceCore not running")
            return
        if self.state == VoiceState.IDLE:
            # Already listening for wake word
            pass

    def stop_listening(self) -> None:
        pass

    def trigger_wakeword(self) -> None:
        if self.state != VoiceState.IDLE:
            logger.warning(f"Cannot trigger wakeword in state {self.state.name}")
            return
        logger.info("Wake word triggered manually (PTT)")

        # Tell pipeline about wakeword (handles listener start)
        if not self._pipeline.on_wakeword_detected([]):
            logger.warning("Pipeline rejected wakeword")
            return

        self.event_emitter.emit(
            VoiceWakeWordDetected(keyword="<manual>", keyword_index=-1)
        )
        self._start_recording()

    def push_to_talk_start(self) -> None:
        self._ptt_active = True
        self.trigger_wakeword()

    def push_to_talk_stop(self) -> None:
        if not self._ptt_active:
            return
        self._ptt_active = False
        if self.state == VoiceState.LISTENING:
            self._finish_recording()

    # -------------------------------------------------------------------------
    # Public API: Speaking Control
    # -------------------------------------------------------------------------

    def speak(self, text: str) -> None:
        if not text or not self._pipeline.is_running:
            return
        try:
            self._speak_queue.put_nowait(text)
        except queue.Full:
            logger.warning("TTS queue full, dropping speech request")

    def stop_speaking(self) -> None:
        if self.state == VoiceState.SPEAKING:
            player = self.component_manager.components.audio_player
            if player:
                player.stop()

        while True:
            try:
                self._speak_queue.get_nowait()
            except queue.Empty:
                break

        # Let speaker FSM know we're done
        self._pipeline.speaker.finish_speaking()

    def set_response_handler(self, handler: Callable[[str], str]) -> None:
        self._response_handler = handler

    def set_audio_feedback_enabled(self, enabled: bool) -> None:
        self._config.audio_feedback_enabled = enabled

    # -------------------------------------------------------------------------
    # Internal: Transitions & Events
    # -------------------------------------------------------------------------

    def _transition_to(self, new_state: VoiceState) -> None:
        with self._state_lock:
            if not can_transition(self._state, new_state):
                raise VoiceStateError(self._state, new_state)
            old_state = self._state
            self._state = new_state
            logger.debug(f"Voice state: {old_state.name} → {new_state.name}")

        self.event_emitter.emit(
            VoiceStateChanged(old_state=old_state, new_state=new_state)
        )

        if new_state == VoiceState.IDLE and self._reinit_pending:
            self._trigger_pending_reinit()

    def _safe_transition_to(self, new_state: VoiceState) -> None:
        try:
            self._transition_to(new_state)
        except VoiceStateError:
            pass

    def _on_component_settings_changed(self, type_: str) -> None:
        with self._pending_changes_lock:
            self._pending_changes.add(type_)
            self._reinit_pending = True

        # If IDLE, trigger now
        if self.state == VoiceState.IDLE:
            self._trigger_pending_reinit()

    def _trigger_pending_reinit(self) -> None:
        # Schedule on loop
        loop = self.event_emitter._event_loop
        if not loop or not loop.is_running():
            return

        # Copy changes under lock to avoid mutation during async handling
        with self._pending_changes_lock:
            changes = set(self._pending_changes)

        async def _apply() -> None:
            if await self.component_manager.reinitialize_pending(changes):
                with self._pending_changes_lock:
                    self._pending_changes.clear()
                    self._reinit_pending = False

        try:
            asyncio.get_running_loop()
            asyncio.create_task(_apply())
        except RuntimeError:
            asyncio.run_coroutine_threadsafe(_apply(), loop)

    # -------------------------------------------------------------------------
    # Internal: Audio Processing
    # -------------------------------------------------------------------------

    def _on_audio_frame(self, frame) -> None:
        current_state = self.state  # Thread-safe read
        if current_state == VoiceState.IDLE or current_state == VoiceState.SPEAKING:
            self._handle_wakeword_check(frame)
        elif current_state == VoiceState.LISTENING:
            self._handle_listening(frame)

    def _handle_wakeword_check(self, frame) -> None:
        """Check for wake word (used in IDLE and SPEAKING states)."""
        wake = self.component_manager.components.wake
        if not wake:
            return

        try:
            idx = wake.process(frame)
            if idx >= 0:
                kw = wake.keywords[idx]
                logger.info(f"Wake word detected: {kw}")

                # Collect pending queue items for buffering (NOT current speech text,
                # since SpeakerFSM handles buffering its own current text)
                pending_items = []
                while not self._speak_queue.empty():
                    try:
                        pending_items.append(self._speak_queue.get_nowait())
                    except queue.Empty:
                        break

                # Tell pipeline about wakeword (handles interrupt + listen start)
                if not self._pipeline.on_wakeword_detected(pending_items):
                    logger.warning("Pipeline rejected wakeword")
                    return

                # Stop audio playback if speaking
                if self.state == VoiceState.SPEAKING:
                    player = self.component_manager.components.audio_player
                    if player:
                        player.stop()

                self.event_emitter.emit(
                    VoiceWakeWordDetected(keyword=kw, keyword_index=idx)
                )
                self._start_recording()
        except Exception as e:
            logger.error(f"Error processing audio frame: {e}")

    def _start_recording(self) -> None:
        self._recording_buffer.clear()
        self._recording_start_time = time.time()
        self._last_frame_time = self._recording_start_time

        proc = self.component_manager.components.vad_processor
        if proc:
            proc.reset()

        # Listener FSM already transitioned via on_wakeword_detected
        self.event_emitter.emit(VoiceListening())
        self.event_emitter.emit(
            VoiceStateChanged(old_state=VoiceState.IDLE, new_state=VoiceState.LISTENING)
        )
        logger.info("Started recording")

    def _handle_listening(self, frame) -> None:
        self._last_frame_time = time.time()
        self._recording_buffer.append(frame)

        elapsed = time.time() - self._recording_start_time
        if elapsed > self._max_recording_duration:
            logger.warning(f"Recording timed out after {elapsed:.1f}s")
            self._finish_recording()
            return

        proc = self.component_manager.components.vad_processor
        if proc:
            if proc.process(frame):
                logger.info(f"VAD speech end after {proc.session_duration:.2f}s")
                self._finish_recording()
        elif elapsed > 3.0:
            self._finish_recording()

    def _finish_recording(self) -> None:
        proc = self.component_manager.components.vad_processor
        if proc and not proc.speech_detected:
            duration = max(0.0, time.time() - self._recording_start_time)
            logger.info("Recording ended with no speech")
            self._recording_buffer.clear()
            self.event_emitter.emit(VoiceNoSpeechDetected(duration_s=duration))

            # Tell pipeline no speech was detected
            has_buffered = self._pipeline.on_no_speech_detected()
            self.event_emitter.emit(
                VoiceStateChanged(
                    old_state=VoiceState.LISTENING, new_state=VoiceState.IDLE
                )
            )

            # Resume any interrupted speech
            if has_buffered:
                buffered = self._pipeline.speaker.get_buffered_speech()
                for text in buffered:
                    self.speak(text)
            return

        # Transition listener to PROCESSING
        self._pipeline.on_speech_end()
        self.event_emitter.emit(
            VoiceStateChanged(
                old_state=VoiceState.LISTENING, new_state=VoiceState.PROCESSING
            )
        )

        if self._recording_buffer:
            audio = np.concatenate(self._recording_buffer)
        else:
            audio = np.array([], dtype=np.int16)
        self._recording_buffer.clear()

        threading.Thread(
            target=self._process_audio_sync,
            args=(audio,),
            daemon=True,
        ).start()

    def _get_ordered_backends(
        self,
        names: list[str] | None,
        active: str | None,
    ) -> list[str]:
        """Build deduplicated backend list with active backend first."""
        backends = list(names or [])
        if active and active not in backends:
            backends.insert(0, active)
        return backends

    def _try_stt_backends(self, audio: np.ndarray):
        """Try each STT backend in order, returning the first successful result.

        Returns:
            Transcription result, or None if all backends fail.
        """
        backends = self._get_ordered_backends(
            self.component_manager.stt_backend_names,
            self.component_manager.active_stt_backend,
        )
        tried: list[str] = []
        for name in backends:
            if name in tried:
                continue
            tried.append(name)

            stt_mismatch = (
                name != self.component_manager.active_stt_backend
                or not self.component_manager.components.stt
            )
            if stt_mismatch:
                try:
                    self.component_manager.init_stt_backend(name)
                except Exception:
                    continue

            try:
                return self.component_manager.components.stt.transcribe(audio)
            except Exception as e:
                logger.error(f"STT backend '{name}' failed: {e}")
                self.event_emitter.emit(VoiceError(error=str(e), exception=e))
        return None

    def _process_audio_sync(self, audio: np.ndarray) -> None:
        try:
            if not self.component_manager.components.stt:
                self._safe_transition_to(VoiceState.IDLE)
                return

            result = self._try_stt_backends(audio)
            if result is None:
                logger.error("All STT backends failed")
                self._safe_transition_to(VoiceState.IDLE)
                return

            text = result.text.strip() if result.text else ""
            if not text:
                logger.info("Empty transcription")
                buffered = self._pipeline.on_transcription_complete(
                    has_valid_text=False,
                )
                self.event_emitter.emit(
                    VoiceStateChanged(
                        old_state=VoiceState.PROCESSING, new_state=VoiceState.IDLE
                    )
                )
                for item in buffered:
                    self.speak(item)
                return

            logger.info(f"Transcription: {text}")
            self.event_emitter.emit(VoiceTranscription(text=text, is_final=True))

            self._pipeline.on_transcription_complete(has_valid_text=True)
            self.event_emitter.emit(
                VoiceStateChanged(
                    old_state=VoiceState.PROCESSING, new_state=VoiceState.IDLE
                )
            )

            if self._response_handler:
                response = self._response_handler(text)
                self.event_emitter.emit(VoiceResponse(text=response))
                self.speak(response)

        except Exception as e:
            logger.error(f"Error processing audio: {e}")
            self.event_emitter.emit(VoiceError(error=str(e), exception=e))
            self._safe_transition_to(VoiceState.IDLE)

    def _speak_loop(self) -> None:
        while not self._speak_stop.is_set():
            try:
                text = self._speak_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            self._current_speech_text = text
            try:
                self._speak_response(text)
            except Exception as e:
                logger.error(f"Speak loop error: {e}")
                self.event_emitter.emit(VoiceError(error=str(e), exception=e))
            finally:
                self._current_speech_text = None

    def _speak_response(self, text: str) -> None:
        if not self._pipeline.is_running:
            return

        # Check if we can speak via pipeline
        if not self._pipeline.can_speak():
            logger.info("Deferring speech (pipeline not ready)")
            # Buffer via speaker FSM
            self._pipeline.speaker._buffer.append(text)
            return

        tts = self.component_manager.components.tts
        if not tts:
            self._pipeline.speaker.finish_speaking()
            return

        # Prepare text
        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        text = re.sub(r"`[^`]+`", "", text)
        text = re.sub(r"\s+", " ", text).strip()

        if not text:
            self._pipeline.speaker.finish_speaking()
            return

        try:
            # Transition speaker FSM to SPEAKING
            if not self._pipeline.start_speaking(text):
                logger.warning("Pipeline rejected speaking")
                return

            old_state = self.state
            self.event_emitter.emit(VoiceSpeaking(text=text))
            if old_state != VoiceState.SPEAKING:
                self.event_emitter.emit(
                    VoiceStateChanged(old_state=old_state, new_state=VoiceState.SPEAKING)
                )
            self._synthesize_with_fallback(text)
        except Exception as e:
            logger.error(f"TTS playback failed: {e}")
            self.event_emitter.emit(VoiceError(error=str(e), exception=e))
        finally:
            self._pipeline.finish_speaking()
            if self.state == VoiceState.IDLE:
                self.event_emitter.emit(
                    VoiceStateChanged(
                        old_state=VoiceState.SPEAKING, new_state=VoiceState.IDLE
                    )
                )

    def _synthesize_with_fallback(self, text: str) -> None:
        """Synthesize text and play via streaming output.

        Uses the streaming playback API (start_stream/write_chunk/finish_stream)
        so that small TTS chunks (~80 ms from pocket-tts) play back-to-back
        without audible gaps.  Falls back through available TTS backends on
        failure.
        """
        from .speaker_fsm import SpeakerState

        if self._pipeline.speaker.state == SpeakerState.INTERRUPTED:
            logger.info("Skipping speech playback due to interrupt")
            return

        backends = self._get_ordered_backends(
            self.component_manager.tts_backend_names,
            self.component_manager.active_tts_backend,
        )
        tried: list[str] = []
        for name in backends:
            if name in tried:
                continue
            tried.append(name)

            tts_mismatch = (
                name != self.component_manager.active_tts_backend
                or not self.component_manager.components.tts
            )
            if tts_mismatch:
                if not asyncio.run_coroutine_threadsafe(
                    self.component_manager.init_tts_backend(name),
                    self.event_emitter._event_loop,
                ).result():
                    continue

            if self._try_tts_playback(text):
                return

        raise RuntimeError(f"All TTS backends failed. Tried: {tried}")

    def _try_tts_playback(self, text: str) -> bool:
        """Attempt TTS playback with the currently active backend.

        Returns:
            True if playback completed successfully.
        """
        from .speaker_fsm import SpeakerState

        tts = self.component_manager.components.tts
        player = self.component_manager.components.audio_player
        try:
            player.start_stream(sample_rate=tts.sample_rate)
            for chunk in tts.synthesize_stream(text):
                speaker_state = self._pipeline.speaker.state
                if speaker_state == SpeakerState.INTERRUPTED:
                    player.stop()
                    logger.info("Stopping playback due to interrupt")
                    return True  # Intentional stop, not a failure
                if speaker_state != SpeakerState.SPEAKING:
                    player.stop()
                    return True
                player.write_chunk(chunk.audio)
            player.finish_stream()
            return True
        except Exception as e:
            logger.error(f"TTS backend failed: {e}")
            player.finish_stream()
            return False

    def _watchdog_loop(self) -> None:
        while not self._watchdog_stop.wait(timeout=1.0):
            if self.state != VoiceState.LISTENING:
                continue

            now = time.time()
            elapsed = now - self._last_frame_time
            if elapsed > self._frame_timeout:
                logger.error(f"Watchdog: No audio frames for {elapsed:.1f}s")
                self.event_emitter.emit(
                    VoiceError(error="Audio stream stopped unexpectedly")
                )
                # Reset listener FSM
                self._pipeline.listener.reset()
                self._recording_buffer.clear()
                self._last_frame_time = 0


# =============================================================================
# Backwards Compatibility Alias
# =============================================================================

VoiceController = VoiceCore
VoiceStatusChanged = VoiceStateChanged
