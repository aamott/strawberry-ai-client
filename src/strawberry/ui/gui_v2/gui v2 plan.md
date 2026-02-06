# GUI V2 Implementation Plan

This document outlines the complete implementation plan for the Spoke Core GUI V2, including UI design specifications, technology stack, architecture, and interaction flows.

---

# Table of Contents

1. [UI Design](#ui-design)
2. [Technology Stack](#technology-stack)
3. [Architecture](#architecture)
4. [Component Specifications](#component-specifications)
5. [Sequence Diagrams](#sequence-diagrams)
6. [Call Hierarchy](#call-hierarchy)
7. [Implementation Phases](#implementation-phases)

---

# UI Design

## Approved Layout: Collapsible Rail (Layout Option 2)

### Design Principles
- **Modularity**: Each component is self-contained with clear interfaces
- **Focus**: Maximum space dedicated to chat content
- **Accessibility**: Keyboard navigation, screen reader support
- **Responsiveness**: Adapts to window size changes
- **Consistency**: Unified theming across all components

### Component Layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│                            TitleBar                                      │
│ [≡]  Strawberry AI                                    [─] [□] [×]        │
├────┬─────────────────────────────────────────────────────────────────────┤
│    │                                                                     │
│ S  │                         ChatArea                                    │
│ i  │  ┌───────────────────────────────────────────────────────────────┐ │
│ d  │  │                      MessageCard                               │ │
│ e  │  │  [Avatar] Role                                    Timestamp   │ │
│ b  │  │  ─────────────────────────────────────────────────────────────│ │
│ a  │  │  Message content...                                           │ │
│ r  │  │  ┌─ ToolCallWidget ─────────────────────────────────────────┐ │ │
│    │  │  │ Skill.method(args) → result                              │ │ │
│ R  │  │  └──────────────────────────────────────────────────────────┘ │ │
│ a  │  └───────────────────────────────────────────────────────────────┘ │
│ i  │                                                                     │
│ l  │                         TypingIndicator                             │
│    │                              ◉◉◉                                    │
│    ├─────────────────────────────────────────────────────────────────────┤
│    │                          InputArea                                  │
│    │   ┌─────────────────────────────────────────────────────────────┐  │
│    │   │ TextInput                                   [🎤] [📎] [⬆️]  │  │
│    │   └─────────────────────────────────────────────────────────────┘  │
├────┴─────────────────────────────────────────────────────────────────────┤
│                            StatusBar                                     │
│ 🟢 Hub: Connected │ 💻 device-name │ 🎙️ Voice: Ready    │ v1.0.0        │
└──────────────────────────────────────────────────────────────────────────┘
```


### Iconography

Using Unicode/Emoji for cross-platform compatibility:
- 💬 Chats/Sessions
- 📝 New Chat
- 🔧 Skills
- ⚙️ Settings
- 🎤 Voice/Microphone
- 📎 Attachments
- ⬆️ Send
- 🤖 Assistant
- 👤 User
- 🟢 Connected
- 🔴 Disconnected
- ⚠️ Warning

---

# Technology Stack

## Core Framework

| Component | Technology | Version | Rationale |
|-----------|------------|---------|-----------|
| GUI Framework | PySide6 | 6.6+ | Qt6 bindings, LGPL license, mature ecosystem |
| Python | Python | 3.11+ | Type hints, async support, performance |
| Async | asyncio + qasync | latest | Qt event loop integration |
| Styling | Qt Style Sheets (QSS) | - | CSS-like theming |


## Dependencies

```toml
# pyproject.toml additions
[project.dependencies]
PySide6 = ">=6.6.0"
qasync = ">=0.27.0"  # asyncio + Qt integration
```

## Integration Points

| System | Interface | Notes |
|--------|-----------|-------|
| SpokeCore | Direct import | Message handling, skill execution |
| VoiceCore | Event-based | Voice state, transcription events |
| SettingsManager | Schema-driven | Auto-generated settings UI |
| SessionController | Async API | Chat history, session management |
| TensorZeroClient | Async streaming | LLM responses |
| HubClient | WebSocket | Online mode, device sync |

---

# Architecture

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              Application                                 │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                         MainWindow                                 │  │
│  │  ┌─────────────────────────────────────────────────────────────┐  │  │
│  │  │                      LayoutManager                           │  │  │
│  │  │  ┌─────────┐ ┌──────────────────────────┐ ┌──────────────┐  │  │  │
│  │  │  │TitleBar │ │       ContentArea        │ │SettingsPanel│  │  │  │
│  │  │  └─────────┘ │  ┌────────┐ ┌─────────┐  │ │  (overlay)   │  │  │  │
│  │  │              │  │Sidebar │ │ChatView │  │ └──────────────┘  │  │  │
│  │  │              │  │  Rail  │ │         │  │                   │  │  │
│  │  │              │  └────────┘ └─────────┘  │                   │  │  │
│  │  │              └──────────────────────────┘                   │  │  │
│  │  │  ┌─────────────────────────────────────────────────────────┐│  │  │
│  │  │  │                      StatusBar                          ││  │  │
│  │  │  └─────────────────────────────────────────────────────────┘│  │  │
│  │  └─────────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                        Services Layer                              │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐  │  │
│  │  │ Session  │ │  Theme   │ │  Voice   │ │ Settings │ │  Agent  │  │  │
│  │  │Controller│ │ Manager  │ │ Manager  │ │ Manager  │ │ Runner  │  │  │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └─────────┘  │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                         Core Layer                                 │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────────┐  │  │
│  │  │SpokeCore │ │VoiceCore │ │HubClient │ │ TensorZeroClient     │  │  │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Component Hierarchy

```
Application
├── MainWindow (QMainWindow)
│   ├── TitleBar (QFrame)
│   │   ├── MenuButton (QToolButton)
│   │   ├── AppTitle (QLabel)
│   │   └── WindowControls (QWidget)
│   │       ├── MinimizeButton (QToolButton)
│   │       ├── MaximizeButton (QToolButton)
│   │       └── CloseButton (QToolButton)
│   │
│   ├── ContentArea (QWidget)
│   │   ├── SidebarRail (QFrame)
│   │   │   ├── NavButton: Chats (QToolButton)
│   │   │   ├── NavButton: NewChat (QToolButton)
│   │   │   ├── NavButton: Skills (QToolButton)
│   │   │   ├── NavButton: Settings (QToolButton)
│   │   │   └── SessionList (QWidget) [expanded only]
│   │   │       └── SessionItem (QWidget) [multiple]
│   │   │
│   │   └── ChatView (QWidget)
│   │       ├── OfflineBanner (QFrame) [conditional]
│   │       ├── ChatArea (QScrollArea)
│   │       │   └── MessageList (QWidget)
│   │       │       └── MessageCard (QFrame) [multiple]
│   │       │           ├── MessageHeader (QWidget)
│   │       │           ├── MessageContent (QWidget)
│   │       │           └── ToolCallWidget (QFrame) [optional]
│   │       ├── TypingIndicator (QWidget) [conditional]
│   │       └── InputArea (QFrame)
│   │           ├── TextInput (QTextEdit)
│   │           └── ActionButtons (QWidget)
│   │               ├── VoiceButton (QToolButton)
│   │               ├── AttachButton (QToolButton)
│   │               └── SendButton (QToolButton)
│   │
│   ├── SettingsPanel (QFrame) [overlay, slides from right]
│   │   ├── SettingsHeader (QWidget)
│   │   ├── SettingsTabs (QTabWidget)
│   │   └── SettingsFooter (QWidget)
│   │
│   ├── VoiceOverlay (QFrame) [modal, center screen]
│   │   ├── VoiceIndicator (QWidget)
│   │   ├── TranscriptionPreview (QLabel)
│   │   └── VoiceControls (QWidget)
│   │
│   └── StatusBar (QFrame)
│       ├── ConnectionStatus (QLabel)
│       ├── DeviceName (QLabel)
│       ├── VoiceStatus (QLabel)
│       └── VersionLabel (QLabel)
```

## Module Structure

```
gui_v2/
├── __init__.py              # Package exports
├── app.py                   # Application entry point
├── main_window.py           # MainWindow class
├── PLAN.md                  # This document
├── gui_v2.md                # Design document
│
├── components/              # Reusable UI components
│   ├── __init__.py
│   ├── title_bar.py         # TitleBar component
│   ├── sidebar_rail.py      # SidebarRail component
│   ├── chat_view.py         # ChatView container
│   ├── chat_area.py         # Scrollable message list
│   ├── message_card.py      # Individual message display
│   ├── tool_call_widget.py  # Tool call display
│   ├── input_area.py        # Message input
│   ├── status_bar.py        # Status bar
│   ├── settings_panel.py    # Settings slide-in
│   ├── voice_overlay.py     # Voice mode overlay
│   └── typing_indicator.py  # Typing animation
│
├── services/                # Business logic services
│   ├── __init__.py
│   ├── session_service.py   # Session management
│   ├── theme_service.py     # Theme management
│   ├── voice_service.py     # Voice integration
│   ├── agent_service.py     # Agent loop runner
│   └── settings_service.py  # Settings integration
│
├── models/                  # Data models
│   ├── __init__.py
│   ├── message.py           # Message model
│   ├── session.py           # Session model
│   └── state.py             # UI state model
│
├── utils/                   # Utilities
│   ├── __init__.py
│   ├── animations.py        # Animation helpers
│   ├── icons.py             # Icon management
│   └── shortcuts.py         # Keyboard shortcuts
│
└── themes/                  # Theme definitions
    ├── __init__.py
    ├── base.py              # Base theme class
    ├── dark.py              # Dark theme
    └── light.py             # Light theme
```

---

# Component Specifications


## Component: MessageCard

### Architecture: Composite Bubble with Interleaved Content

A single assistant turn may contain multiple interleaved segments: text responses and tool calls in any order. Since `QTextDocument` doesn't natively support expandable/collapsible elements, we use a **composite widget architecture** where the MessageCard contains a vertical layout of multiple content segments.

### Visual Structure

**Design Principle: Seamless Flow**
The MessageCard should appear as one continuous text block to the user, NOT as nested bubbles.
Tool call widgets are inline elements that blend into the text flow with minimal visual separation.
Only the outer MessageCard has a bubble/card appearance.

```
┌─ MessageCard (QFrame) ──────────────────────────────────────────────────┐
│ [🤖] Assistant                                           12:35 PM       │
│ ────────────────────────────────────────────────────────────────────────│
│                                                                          │
│ [▼] 🔧 WeatherSkill.get_current_weather("NYC") ✓                        │
│     Args: {"city": "NYC"}                                                │
│     Result: {"temp": 72, "condition": "sunny"} · 0.3s                    │
│                                                                          │
│ The current weather in NYC is 72°F and sunny.                            │
│                                                                          │
│ Would you like me to check the forecast for tomorrow?                    │
│                                                                          │
│ [▶] 🔧 CalendarSkill.get_events("tomorrow") ✓                           │
│                                                                          │
│ I also checked your calendar - you have 2 meetings tomorrow.             │
└──────────────────────────────────────────────────────────────────────────┘
```

**Key Visual Rules:**
- Only the outer MessageCard has a border/background (the "bubble")
- Tool calls are inline with subtle background tint, no nested borders
- Text segments have no visible container - they flow naturally
- Minimal vertical spacing between segments (4-8px)
- Tool call toggle [▶]/[▼] is compact and inline
- Collapsed tool calls show as single line: `[▶] 🔧 SkillName.method() ✓`
- Expanded tool calls indent details slightly but remain part of the flow

---

# Sequence Diagrams

## 1. Application Startup

```
┌──────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│ User │     │   App    │     │MainWindow│     │SpokeCore │     │ Session  │
└──┬───┘     └────┬─────┘     └────┬─────┘     └────┬─────┘     └────┬─────┘
   │              │                │                │                │
   │ Launch App   │                │                │                │
   │─────────────>│                │                │                │
   │              │                │                │                │
   │              │ Create Window  │                │                │
   │              │───────────────>│                │                │
   │              │                │                │                │
   │              │                │ Init SpokeCore │                │
   │              │                │───────────────>│                │
   │              │                │                │                │
   │              │                │ Load Sessions  │                │
   │              │                │───────────────────────────────>│
   │              │                │                │                │
   │              │                │<───────────────────────────────│
   │              │                │  Session List  │                │
   │              │                │                │                │
   │              │                │ Connect Hub    │                │
   │              │                │───────────────>│                │
   │              │                │                │ WebSocket      │
   │              │                │                │───────────────>│
   │              │                │                │                │
   │              │                │<───────────────│                │
   │              │                │ Connection OK  │                │
   │              │                │                │                │
   │              │<───────────────│                │                │
   │              │  Window Ready  │                │                │
   │              │                │                │                │
   │<─────────────│                │                │                │
   │  UI Visible  │                │                │                │
```

## 2. Send Message Flow

```
┌──────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│ User │     │InputArea │     │ ChatView │     │AgentServ │     │SpokeCore │
└──┬───┘     └────┬─────┘     └────┬─────┘     └────┬─────┘     └────┬─────┘
   │              │                │                │                │
   │ Type Message │                │                │                │
   │─────────────>│                │                │                │
   │              │                │                │                │
   │ Press Send   │                │                │                │
   │─────────────>│                │                │                │
   │              │                │                │                │
   │              │ submit(text)   │                │                │
   │              │───────────────>│                │                │
   │              │                │                │                │
   │              │                │ Add User Msg   │                │
   │              │                │────────┐       │                │
   │              │                │<───────┘       │                │
   │              │                │                │                │
   │              │                │ Show Typing    │                │
   │              │                │────────┐       │                │
   │              │                │<───────┘       │                │
   │              │                │                │                │
   │              │                │ run_agent()    │                │
   │              │                │───────────────>│                │
   │              │                │                │                │
   │              │                │                │ send_message() │
   │              │                │                │───────────────>│
   │              │                │                │                │
   │              │                │                │<───────────────│
   │              │                │                │ Stream chunks  │
   │              │                │                │                │
   │              │                │<───────────────│                │
   │              │                │ Update Message │                │
   │              │                │                │                │
   │              │                │<───────────────│                │
   │              │                │ Tool Call      │                │
   │              │                │                │                │
   │              │                │<───────────────│                │
   │              │                │ Final Response │                │
   │              │                │                │                │
   │              │                │ Hide Typing    │                │
   │              │                │────────┐       │                │
   │              │                │<───────┘       │                │
```

## 3. Voice Input Flow

```
┌──────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│ User │     │InputArea │     │VoiceOver │     │VoiceServ │     │VoiceCore │
└──┬───┘     └────┬─────┘     └────┬─────┘     └────┬─────┘     └────┬─────┘
   │              │                │                │                │
   │ Click 🎤     │                │                │                │
   │─────────────>│                │                │                │
   │              │                │                │                │
   │              │ voice_clicked  │                │                │
   │              │───────────────────────────────>│                │
   │              │                │                │                │
   │              │                │                │ start_listen() │
   │              │                │                │───────────────>│
   │              │                │                │                │
   │              │                │ Show Overlay   │                │
   │              │                │<───────────────│                │
   │              │                │                │                │
   │ Speak        │                │                │                │
   │─────────────────────────────>│                │                │
   │              │                │                │                │
   │              │                │                │<───────────────│
   │              │                │                │ Audio Level    │
   │              │                │                │                │
   │              │                │<───────────────│                │
   │              │                │ Update Visual  │                │
   │              │                │                │                │
   │              │                │                │<───────────────│
   │              │                │                │ Transcription  │
   │              │                │                │                │
   │              │                │<───────────────│                │
   │              │                │ Show Preview   │                │
   │              │                │                │                │
   │ Stop Speaking│                │                │                │
   │─────────────────────────────>│                │                │
   │              │                │                │                │
   │              │                │                │<───────────────│
   │              │                │                │ Final Text     │
   │              │                │                │                │
   │              │                │ Hide Overlay   │                │
   │              │                │────────┐       │                │
   │              │                │<───────┘       │                │
   │              │                │                │                │
   │              │<───────────────────────────────│                │
   │              │ Set Input Text │                │                │
```

## 4. Sidebar Navigation Flow

```
┌──────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│ User │     │ Sidebar  │     │MainWindow│     │ Session  │     │ ChatView │
└──┬───┘     └────┬─────┘     └────┬─────┘     └────┬─────┘     └────┬─────┘
   │              │                │                │                │
   │ Click 💬     │                │                │                │
   │─────────────>│                │                │                │
   │              │                │                │                │
   │              │ expand()       │                │                │
   │              │────────┐       │                │                │
   │              │<───────┘       │                │                │
   │              │                │                │                │
   │ Click Session│                │                │                │
   │─────────────>│                │                │                │
   │              │                │                │                │
   │              │session_selected│                │                │
   │              │───────────────>│                │                │
   │              │                │                │                │
   │              │                │ load_session() │                │
   │              │                │───────────────>│                │
   │              │                │                │                │
   │              │                │<───────────────│                │
   │              │                │ Session Data   │                │
   │              │                │                │                │
   │              │                │ set_messages() │                │
   │              │                │───────────────────────────────>│
   │              │                │                │                │
   │              │ collapse()     │                │                │
   │              │────────┐       │                │                │
   │              │<───────┘       │                │                │
```

## 5. Settings Panel Flow

```
┌──────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│ User │     │ Sidebar  │     │ Settings │     │SettServ  │     │SettMgr   │
└──┬───┘     └────┬─────┘     └────┬─────┘     └────┬─────┘     └────┬─────┘
   │              │                │                │                │
   │ Click ⚙️     │                │                │                │
   │─────────────>│                │                │                │
   │              │                │                │                │
   │              │nav_changed     │                │                │
   │              │("settings")    │                │                │
   │              │───────────────>│                │                │
   │              │                │                │                │
   │              │                │ show()         │                │
   │              │                │────────┐       │                │
   │              │                │<───────┘       │                │
   │              │                │                │                │
   │              │                │ load_settings()│                │
   │              │                │───────────────>│                │
   │              │                │                │                │
   │              │                │                │ get_schema()   │
   │              │                │                │───────────────>│
   │              │                │                │                │
   │              │                │                │<───────────────│
   │              │                │                │ Schema + Values│
   │              │                │                │                │
   │              │                │<───────────────│                │
   │              │                │ Render Fields  │                │
   │              │                │                │                │
   │ Modify Value │                │                │                │
   │─────────────────────────────>│                │                │
   │              │                │                │                │
   │              │                │settings_changed│                │
   │              │                │───────────────>│                │
   │              │                │                │                │
   │ Click Save   │                │                │                │
   │─────────────────────────────>│                │                │
   │              │                │                │                │
   │              │                │ save_settings()│                │
   │              │                │───────────────>│                │
   │              │                │                │                │
   │              │                │                │ set_values()   │
   │              │                │                │───────────────>│
   │              │                │                │                │
   │              │                │<───────────────│                │
   │              │                │ settings_saved │                │
   │              │                │                │                │
   │              │                │ hide()         │                │
   │              │                │────────┐       │                │
   │              │                │<───────┘       │                │
```

---

# Call Hierarchy

## MainWindow Initialization

```
MainWindow.__init__()
├── super().__init__()
├── _init_services()
│   ├── SessionService(settings_manager)
│   ├── ThemeService(settings_manager)
│   ├── VoiceService(voice_core)
│   ├── AgentService(spoke_core)
│   └── SettingsService(settings_manager)
│
├── _setup_window()
│   ├── setWindowFlags(Qt.FramelessWindowHint)
│   ├── setMinimumSize(800, 600)
│   └── _load_geometry()
│
├── _setup_ui()
│   ├── TitleBar()
│   │   ├── setup_ui()
│   │   └── connect_signals()
│   │
│   ├── ContentArea()
│   │   ├── SidebarRail()
│   │   │   ├── setup_ui()
│   │   │   └── connect_signals()
│   │   │
│   │   └── ChatView()
│   │       ├── ChatArea()
│   │       ├── InputArea()
│   │       └── connect_signals()
│   │
│   ├── SettingsPanel()
│   │   ├── setup_ui()
│   │   └── connect_signals()
│   │
│   ├── VoiceOverlay()
│   │   ├── setup_ui()
│   │   └── connect_signals()
│   │
│   └── StatusBar()
│       ├── setup_ui()
│       └── connect_signals()
│
├── _connect_signals()
│   ├── title_bar.menu_clicked.connect(_on_menu)
│   ├── title_bar.minimize_clicked.connect(showMinimized)
│   ├── title_bar.maximize_clicked.connect(_toggle_maximize)
│   ├── title_bar.close_clicked.connect(close)
│   ├── sidebar.navigation_changed.connect(_on_navigation)
│   ├── sidebar.session_selected.connect(_on_session_selected)
│   ├── chat_view.message_sent.connect(_on_message_sent)
│   ├── chat_view.voice_requested.connect(_on_voice_requested)
│   └── settings_panel.settings_saved.connect(_on_settings_saved)
│
├── _apply_theme()
│   └── theme_service.apply_theme(self)
│
└── _start_async()
    ├── spoke_core.start()
    ├── session_service.load_sessions()
    └── _update_connection_status()
```

## Message Send Flow

```
_on_message_sent(text)
├── chat_view.add_message(UserMessage(text))
├── chat_view.set_typing(True)
├── chat_view.set_input_enabled(False)
│
├── agent_service.run_agent(text, session_id)
│   ├── spoke_core.send_message(text)
│   │   ├── [Online] hub_client.send()
│   │   └── [Offline] tensorzero_client.inference()
│   │
│   ├── [Stream] yield chunks
│   │   └── _on_stream_chunk(chunk)
│   │       └── chat_view.update_message(msg_id, chunk)
│   │
│   ├── [Tool Call] yield tool_call
│   │   └── _on_tool_call(tool_call)
│   │       └── chat_view.add_tool_call(msg_id, tool_call)
│   │
│   └── return final_response
│
├── chat_view.set_typing(False)
├── chat_view.set_input_enabled(True)
└── session_service.save_message(session_id, response)
```

## Theme Application Flow

```
theme_service.apply_theme(widget)
├── theme = get_current_theme()
├── stylesheet = generate_stylesheet(theme)
├── widget.setStyleSheet(stylesheet)
│
└── [Recursive] for child in widget.children():
    └── child.apply_theme(theme)
```

---

# Appendix

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Ctrl+N | New chat |
| Ctrl+, | Open settings |
| Enter | Send message |
| Ctrl+M | Toggle voice mode |
| Ctrl+B | Toggle sidebar |
| Ctrl+W | Close current session |
| Escape | Close overlay/panel |
| Up/Down | Navigate sessions |

## Accessibility Requirements

- All interactive elements focusable via Tab
- Screen reader labels for all buttons
- High contrast mode support
- Minimum touch target size: 44x44px
- Color not sole indicator of state
- Keyboard navigation for all features
