"""Terminal-based UI for Strawberry AI Spoke."""

import sys
import signal
from pathlib import Path
from typing import Optional, Callable

from .config import load_config, Settings
from .pipeline.events import PipelineEvent, EventType


class Colors:
    """ANSI color codes."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    
    @classmethod
    def disable(cls):
        """Disable colors (for non-TTY output)."""
        for attr in dir(cls):
            if not attr.startswith('_') and attr != 'disable':
                setattr(cls, attr, "")


class TerminalApp:
    """Terminal-based interface for Strawberry AI.
    
    Provides a simple chat interface with support for:
    - Text input/output
    - Pipeline event display
    - Debug mode
    """
    
    def __init__(
        self,
        config_path: Optional[Path] = None,
        voice_mode: bool = False,
        debug: bool = False,
        response_handler: Optional[Callable[[str], str]] = None,
    ):
        """Initialize terminal app.
        
        Args:
            config_path: Path to config file
            voice_mode: Enable voice interaction (requires backends)
            debug: Enable debug output
            response_handler: Custom response handler for text input
        """
        self.voice_mode = voice_mode
        self.debug = debug
        self._running = False
        self._response_handler = response_handler
        
        # Load config
        if config_path and config_path.exists():
            self.settings = load_config(config_path)
        else:
            self.settings = Settings()
        
        # Disable colors if not a TTY
        if not sys.stdout.isatty():
            Colors.disable()
    
    def run(self) -> int:
        """Run the terminal application.
        
        Returns:
            Exit code (0 for success)
        """
        self._running = True
        
        # Set up signal handler for clean exit
        signal.signal(signal.SIGINT, self._handle_interrupt)
        
        self._print_header()
        
        if self.voice_mode:
            return self._run_voice_mode()
        else:
            return self._run_text_mode()
    
    def _print_header(self) -> None:
        """Print application header."""
        print(f"\n{Colors.CYAN}{Colors.BOLD}🍓 Strawberry AI Spoke{Colors.RESET}")
        print(f"{Colors.DIM}─" * 40 + Colors.RESET)
        print(f"{Colors.DIM}Device: {self.settings.device.name}{Colors.RESET}")
        
        if self.voice_mode:
            print(f"{Colors.GREEN}Voice mode enabled{Colors.RESET}")
            print(f"{Colors.DIM}Wake word: {', '.join(self.settings.wake_word.keywords)}{Colors.RESET}")
        else:
            print(f"{Colors.YELLOW}Text mode (use --voice for voice interaction){Colors.RESET}")
        
        print(f"{Colors.DIM}Type 'quit' or 'exit' to stop, 'help' for commands{Colors.RESET}")
        print(f"{Colors.DIM}─" * 40 + Colors.RESET)
        print()
    
    def _run_text_mode(self) -> int:
        """Run in text-only mode."""
        while self._running:
            try:
                # Get user input
                user_input = input(f"{Colors.GREEN}You:{Colors.RESET} ").strip()
                
                if not user_input:
                    continue
                
                # Handle commands
                if user_input.lower() in ("quit", "exit", "q"):
                    break
                elif user_input.lower() == "help":
                    self._print_help()
                    continue
                elif user_input.lower() == "config":
                    self._print_config()
                    continue
                elif user_input.lower() == "debug":
                    self.debug = not self.debug
                    print(f"{Colors.YELLOW}Debug mode: {'on' if self.debug else 'off'}{Colors.RESET}")
                    continue
                
                # Get response
                response = self._get_response(user_input)
                
                # Print response
                print(f"{Colors.CYAN}AI:{Colors.RESET} {response}")
                print()
                
            except EOFError:
                # Handle Ctrl+D
                break
        
        print(f"\n{Colors.DIM}Goodbye!{Colors.RESET}")
        return 0
    
    def _run_voice_mode(self) -> int:
        """Run with voice interaction."""
        try:
            from .audio.backends.sounddevice_backend import SoundDeviceBackend
            from .wake.backends.porcupine import PorcupineDetector
            from .vad.backends.silero import SileroVAD
            from .stt.backends.leopard import LeopardSTT
            from .tts.backends.orca import OrcaTTS
            from .pipeline import ConversationPipeline, PipelineConfig
        except ImportError as e:
            print(f"{Colors.RED}Error: Missing dependencies for voice mode{Colors.RESET}")
            print(f"{Colors.DIM}Install with: pip install -e '.[picovoice,silero]'{Colors.RESET}")
            print(f"{Colors.DIM}Details: {e}{Colors.RESET}")
            return 1
        
        try:
            # Initialize components
            print(f"{Colors.DIM}Initializing audio...{Colors.RESET}")
            audio = SoundDeviceBackend(
                sample_rate=self.settings.audio.sample_rate,
                frame_length_ms=self.settings.audio.frame_length_ms,
            )
            
            print(f"{Colors.DIM}Initializing wake word detector...{Colors.RESET}")
            wake = PorcupineDetector(
                keywords=self.settings.wake_word.keywords,
                sensitivity=self.settings.wake_word.sensitivity,
            )
            
            print(f"{Colors.DIM}Initializing VAD...{Colors.RESET}")
            vad = SileroVAD(sample_rate=self.settings.audio.sample_rate)
            
            print(f"{Colors.DIM}Initializing STT...{Colors.RESET}")
            stt = LeopardSTT()
            
            print(f"{Colors.DIM}Initializing TTS...{Colors.RESET}")
            tts = OrcaTTS()
            
            # Create pipeline
            config = PipelineConfig(
                vad_config=self.settings.vad.config,
            )
            
            pipeline = ConversationPipeline(
                audio_backend=audio,
                wake_detector=wake,
                vad_backend=vad,
                stt_engine=stt,
                tts_engine=tts,
                response_handler=self._get_response,
                config=config,
            )
            
            # Register event handler
            pipeline.on_event(self._on_pipeline_event)
            
            print(f"\n{Colors.GREEN}Ready! Say '{self.settings.wake_word.keywords[0]}' to start.{Colors.RESET}")
            print(f"{Colors.DIM}Press Ctrl+C to stop.{Colors.RESET}\n")
            
            # Start pipeline
            pipeline.start()
            
            # Wait for interrupt
            while self._running:
                try:
                    # Also accept text input while listening
                    user_input = input()
                    if user_input.lower() in ("quit", "exit", "q"):
                        break
                except EOFError:
                    break
            
            # Cleanup
            pipeline.stop()
            wake.cleanup()
            stt.cleanup()
            tts.cleanup()
            
        except ValueError as e:
            print(f"{Colors.RED}Configuration error: {e}{Colors.RESET}")
            return 1
        except Exception as e:
            print(f"{Colors.RED}Error: {e}{Colors.RESET}")
            if self.debug:
                import traceback
                traceback.print_exc()
            return 1
        
        print(f"\n{Colors.DIM}Goodbye!{Colors.RESET}")
        return 0
    
    def _get_response(self, user_input: str) -> str:
        """Get response to user input.
        
        Override this or pass response_handler to customize.
        """
        if self._response_handler:
            return self._response_handler(user_input)
        
        # Default echo response (placeholder for LLM integration)
        return f"I heard: \"{user_input}\"\n(LLM integration coming soon)"
    
    def _on_pipeline_event(self, event: PipelineEvent) -> None:
        """Handle pipeline events."""
        if event.type == EventType.WAKE_WORD_DETECTED:
            keyword = event.data.get("keyword", "")
            print(f"\n{Colors.MAGENTA}🎤 Wake word detected: {keyword}{Colors.RESET}")
        
        elif event.type == EventType.RECORDING_STARTED:
            print(f"{Colors.YELLOW}Recording...{Colors.RESET}")
        
        elif event.type == EventType.RECORDING_STOPPED:
            print(f"{Colors.DIM}Recording stopped{Colors.RESET}")
        
        elif event.type == EventType.TRANSCRIPTION_COMPLETE:
            text = event.data.get("text", "")
            if text:
                print(f"{Colors.GREEN}You:{Colors.RESET} {text}")
        
        elif event.type == EventType.RESPONSE_TEXT:
            text = event.data.get("text", "")
            print(f"{Colors.CYAN}AI:{Colors.RESET} {text}")
        
        elif event.type == EventType.TTS_STARTED:
            if self.debug:
                print(f"{Colors.DIM}Speaking...{Colors.RESET}")
        
        elif event.type == EventType.TTS_COMPLETE:
            if self.debug:
                print(f"{Colors.DIM}Done speaking{Colors.RESET}")
            print()  # Blank line after conversation turn
        
        elif event.type == EventType.ERROR:
            error = event.data.get("error", "Unknown error")
            stage = event.data.get("stage", "")
            print(f"{Colors.RED}Error ({stage}): {error}{Colors.RESET}")
        
        elif self.debug:
            print(f"{Colors.DIM}[{event.type.name}] {event.data}{Colors.RESET}")
    
    def _print_help(self) -> None:
        """Print help message."""
        print(f"\n{Colors.BOLD}Commands:{Colors.RESET}")
        print(f"  {Colors.CYAN}quit{Colors.RESET}, {Colors.CYAN}exit{Colors.RESET}, {Colors.CYAN}q{Colors.RESET}  - Exit the application")
        print(f"  {Colors.CYAN}help{Colors.RESET}            - Show this help message")
        print(f"  {Colors.CYAN}config{Colors.RESET}          - Show current configuration")
        print(f"  {Colors.CYAN}debug{Colors.RESET}           - Toggle debug mode")
        print()
    
    def _print_config(self) -> None:
        """Print current configuration."""
        print(f"\n{Colors.BOLD}Configuration:{Colors.RESET}")
        print(f"  Device: {self.settings.device.name} ({self.settings.device.id})")
        print(f"  Hub: {self.settings.hub.url}")
        print(f"  Audio: {self.settings.audio.backend} @ {self.settings.audio.sample_rate}Hz")
        print(f"  Wake word: {self.settings.wake_word.keywords}")
        print(f"  VAD: {self.settings.vad.backend}")
        print(f"  STT: {self.settings.stt.backend}")
        print(f"  TTS: {self.settings.tts.backend}")
        print()
    
    def _handle_interrupt(self, signum, frame) -> None:
        """Handle Ctrl+C."""
        self._running = False
        print(f"\n{Colors.DIM}Stopping...{Colors.RESET}")

