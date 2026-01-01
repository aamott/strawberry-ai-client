"""Example usage of music control skills."""

import os
import tempfile

from skills.music_control_skill import AdvancedMusicControlSkill, MusicControlSkill


def main():
    """Demonstrate music control functionality."""

    # Create a temporary music folder for demonstration
    temp_dir = tempfile.mkdtemp()

    # Create some test music files
    test_files = [
        os.path.join(temp_dir, "summer_vibes.mp3"),
        os.path.join(temp_dir, "chill_beats.wav"),
        os.path.join(temp_dir, "rock_anthem.flac"),
    ]

    for file_path in test_files:
        with open(file_path, 'w') as f:
            f.write("test audio data")

    print("=== Music Control Skill Demo ===\n")

    # Initialize music control
    music_control = MusicControlSkill(temp_dir)
    advanced_control = AdvancedMusicControlSkill(temp_dir)

    # 1. Get music library stats
    print("1. Music Library Statistics:")
    stats = music_control.get_music_library_stats()
    print(f"   Total songs: {stats['total_songs']}")
    print(f"   Music folder: {stats['music_folder']}")
    print(f"   File types: {stats['file_types']}")
    print()

    # 2. Search for music
    print("2. Searching for 'chill':")
    results = music_control.search_music("chill")
    for i, song in enumerate(results, 1):
        print(f"   {i}. {song['title']} ({song['artist']})")
    print()

    # 3. Play a song by title
    print("3. Playing 'summer_vibes':")
    result = music_control.play_song_by_title("summer_vibes")
    print(f"   {result}")
    print()

    # 4. Advanced features - create playlist
    print("4. Creating playlist 'Summer Mix':")
    result = advanced_control.create_playlist("Summer Mix", ["summer_vibes", "chill_beats"])
    print(f"   {result}")
    print()

    # 5. List playlists
    print("5. Available playlists:")
    playlists = advanced_control.list_playlists()
    for playlist in playlists:
        print(f"   - {playlist}")
    print()

    # 6. Play a playlist
    print("6. Playing 'Summer Mix' playlist:")
    result = advanced_control.play_playlist("Summer Mix")
    print(f"   {result}")
    print()

    # 7. Get playlist info
    print("7. Playlist info for 'Summer Mix':")
    info = advanced_control.get_playlist_info("Summer Mix")
    print(f"   Name: {info['name']}")
    print(f"   Song count: {info['song_count']}")
    print()

    # Cleanup
    try:
        for file_path in test_files:
            if os.path.exists(file_path):
                os.remove(file_path)
        os.rmdir(temp_dir)
    except Exception as e:
        print(f"Cleanup warning: {e}")

    print("=== Demo Complete ===")


if __name__ == "__main__":
    main()
