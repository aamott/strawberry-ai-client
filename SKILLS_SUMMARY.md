# New Skills for Strawberry AI

This document summarizes the new skills implemented for the Strawberry AI voice assistant platform.

## Overview

Three new skill categories have been added to enhance the assistant's capabilities:

1. **Internet Skills** 🌐 - Web search and browsing
2. **Media Control Skills** 🎵 - Media playback control
3. **System Control Skills** ⚙️ - Device management

## Internet Skills

### InternetSearchSkill
Provides web search and browsing capabilities:

- `search_web(query: str, max_results: int = 5)` - Search the web and return results
- `open_website(url: str)` - Open a website in the default browser
- `get_website_info(url: str)` - Get basic information about a website

### WebBrowserSkill
Controls web browser navigation:

- `navigate_back()` - Go back to the previous page
- `navigate_forward()` - Go forward to the next page
- `refresh_page()` - Refresh the current page
- `close_browser()` - Close the browser

## Media Control Skills

### MediaControlSkill
Controls media playback on the device:

- `play()` - Resume media playback
- `pause()` - Pause media playback
- `stop()` - Stop media playback
- `next_track()` - Skip to the next track
- `previous_track()` - Go back to the previous track
- `set_volume(volume: int)` - Set the media volume (0-100)
- `get_volume()` - Get the current volume level
- `get_current_track()` - Get information about the currently playing track

### MusicLibrarySkill
Manages music library and playlists:

- `search_songs(query: str, max_results: int = 10)` - Search for songs
- `create_playlist(name: str, song_titles: list)` - Create a new playlist
- `play_playlist(name: str)` - Play a specific playlist

## System Control Skills

### SystemControlSkill
Controls basic system functions:

- `get_system_info()` - Get system information (OS, version, etc.)
- `set_system_volume(volume: int)` - Set the system volume (0-100)
- `get_system_volume()` - Get the current system volume
- `sleep_system()` - Put the system to sleep (simulated for safety)
- `restart_system()` - Restart the system (simulated for safety)
- `shutdown_system()` - Shut down the system (simulated for safety)

### DisplayControlSkill
Controls display settings:

- `set_brightness(brightness: int)` - Set the display brightness (0-100)
- `get_brightness()` - Get the current display brightness

## Implementation Details

### Safety Features

- **System power operations** (sleep, restart, shutdown) are simulated for safety during testing
- **Volume and brightness controls** include range validation (0-100)
- **URL handling** includes automatic protocol prefixing (http:// or https://)

### Cross-Platform Support

The skills are designed to work across different operating systems:

- **Windows**: Uses PowerShell commands and COM objects
- **macOS**: Uses AppleScript and osascript
- **Linux**: Uses playerctl, amixer, and systemctl

### Integration with Agent Loop

All skills are fully integrated with the Strawberry AI agent loop:

1. **Discovery**: LLM can find skills using `device.search_skills("query")`
2. **Inspection**: LLM can get function details using `device.describe_function("SkillName.method")`
3. **Execution**: LLM can call skills using `device.SkillName.method(args)`
4. **Results**: Execution results are returned to the LLM for continued reasoning

## Usage Examples

### Example 1: Internet Search
```python
# LLM discovers internet skills
results = device.search_skills("web")

# LLM gets function details
info = device.describe_function("InternetSearchSkill.search_web")

# LLM executes the skill
results = device.InternetSearchSkill.search_web("Python programming")
```

### Example 2: Media Control
```python
# LLM discovers media skills
results = device.search_skills("media")

# LLM controls playback
device.MediaControlSkill.play()
device.MediaControlSkill.set_volume(75)
track_info = device.MediaControlSkill.get_current_track()
```

### Example 3: System Control
```python
# LLM gets system information
system_info = device.SystemControlSkill.get_system_info()

# LLM adjusts system settings
device.SystemControlSkill.set_system_volume(60)
device.DisplayControlSkill.set_brightness(80)
```

## Testing

Comprehensive tests have been implemented in `tests/test_new_skills.py`:

- **Unit tests** for each skill class and method
- **Integration tests** for skill discovery and execution
- **Workflow tests** for complete agent loop scenarios
- **Error handling tests** for invalid inputs

All tests pass successfully, ensuring the skills work correctly with the existing system.

## Future Enhancements

Potential improvements for future development:

1. **Real search engine integration** for InternetSearchSkill
2. **Actual media player integration** (Spotify, VLC, etc.)
3. **Real system control** with proper permissions handling
4. **Additional skills** like weather, reminders, calendar integration
5. **Multi-device coordination** for distributed skill execution

## Files Added

- `skills/internet_skill.py` - Internet search and browsing skills
- `skills/media_control_skill.py` - Media playback control skills
- `skills/system_control_skill.py` - System control skills
- `tests/test_new_skills.py` - Comprehensive tests for new skills
- `demo_new_skills.py` - Demonstration script
- `SKILLS_SUMMARY.md` - This documentation

The new skills significantly enhance Strawberry AI's capabilities while maintaining the existing architecture and safety constraints.