#!/usr/bin/env python3
"""Demonstration of new skills for Strawberry AI."""

from strawberry.skills.loader import SkillLoader
from strawberry.skills.service import SkillService
from pathlib import Path


def demo_internet_skills():
    """Demonstrate internet search skills."""
    print("🌐 INTERNET SKILLS DEMO")
    print("=" * 50)
    
    service = SkillService(Path("skills"))
    service.load_skills()
    
    # Demo 1: Search the web
    print("1. Searching the web for 'Python programming'...")
    code1 = """
results = device.InternetSearchSkill.search_web("Python programming")
for result in results:
    print(f"Title: {result['title']}")
    print(f"URL: {result['url']}")
    print(f"Snippet: {result['snippet']}")
    print()
"""
    result1 = service.execute_code(code1)
    print(f"Success: {result1.success}")
    print(f"Output:\n{result1.result}")
    print()
    
    # Demo 2: Open a website
    print("2. Opening a website...")
    code2 = """
result = device.InternetSearchSkill.open_website("https://www.python.org")
print(result)
"""
    result2 = service.execute_code(code2)
    print(f"Success: {result2.success}")
    print(f"Output: {result2.result}")
    print()


def demo_media_skills():
    """Demonstrate media control skills."""
    print("🎵 MEDIA CONTROL SKILLS DEMO")
    print("=" * 50)
    
    service = SkillService(Path("skills"))
    service.load_skills()
    
    # Demo 1: Play media
    print("1. Playing media...")
    code1 = """
result = device.MediaControlSkill.play()
print(result)
"""
    result1 = service.execute_code(code1)
    print(f"Success: {result1.success}")
    print(f"Output: {result1.result}")
    print()
    
    # Demo 2: Set volume
    print("2. Setting volume to 75%...")
    code2 = """
result = device.MediaControlSkill.set_volume(75)
print(result)
"""
    result2 = service.execute_code(code2)
    print(f"Success: {result2.success}")
    print(f"Output: {result2.result}")
    print()
    
    # Demo 3: Get current track
    print("3. Getting current track info...")
    code3 = """
track = device.MediaControlSkill.get_current_track()
print(f"Now playing: {track['title']} by {track['artist']}")
print(f"Album: {track['album']}")
print(f"Duration: {track['duration']}")
"""
    result3 = service.execute_code(code3)
    print(f"Success: {result3.success}")
    print(f"Output:\n{result3.result}")
    print()


def demo_system_skills():
    """Demonstrate system control skills."""
    print("⚙️ SYSTEM CONTROL SKILLS DEMO")
    print("=" * 50)
    
    service = SkillService(Path("skills"))
    service.load_skills()
    
    # Demo 1: Get system info
    print("1. Getting system information...")
    code1 = """
info = device.SystemControlSkill.get_system_info()
for key, value in info.items():
    print(f"{key}: {value}")
"""
    result1 = service.execute_code(code1)
    print(f"Success: {result1.success}")
    print(f"Output:\n{result1.result}")
    print()
    
    # Demo 2: Set system volume
    print("2. Setting system volume to 60%...")
    code2 = """
result = device.SystemControlSkill.set_system_volume(60)
print(result)
"""
    result2 = service.execute_code(code2)
    print(f"Success: {result2.success}")
    print(f"Output: {result2.result}")
    print()
    
    # Demo 3: Set display brightness
    print("3. Setting display brightness to 80%...")
    code3 = """
result = device.DisplayControlSkill.set_brightness(80)
print(result)
"""
    result3 = service.execute_code(code3)
    print(f"Success: {result3.success}")
    print(f"Output: {result3.result}")
    print()


def demo_skill_discovery():
    """Demonstrate skill discovery capabilities."""
    print("🔍 SKILL DISCOVERY DEMO")
    print("=" * 50)
    
    service = SkillService(Path("skills"))
    service.load_skills()
    
    # Demo 1: Search for skills
    print("1. Searching for 'media' skills...")
    code1 = """
results = device.search_skills("media")
for result in results:
    print(f"Skill: {result['path']}")
    print(f"Signature: {result['signature']}")
    print(f"Summary: {result['summary']}")
    print()
"""
    result1 = service.execute_code(code1)
    print(f"Success: {result1.success}")
    print(f"Output:\n{result1.result}")
    print()
    
    # Demo 2: Get function details
    print("2. Getting details about MediaControlSkill.play...")
    code2 = """
info = device.describe_function("MediaControlSkill.play")
print(info)
"""
    result2 = service.execute_code(code2)
    print(f"Success: {result2.success}")
    print(f"Output:\n{result2.result}")
    print()


def main():
    """Run all demonstrations."""
    print("🍓 STRAWBERRY AI - NEW SKILLS DEMONSTRATION")
    print("=" * 60)
    print()
    
    try:
        demo_internet_skills()
        print()
        
        demo_media_skills()
        print()
        
        demo_system_skills()
        print()
        
        demo_skill_discovery()
        print()
        
        print("🎉 All demonstrations completed successfully!")
        print()
        print("These skills can now be used by the LLM through the agent loop:")
        print("- The LLM can search for skills using device.search_skills()")
        print("- Get function details with device.describe_function()")
        print("- Execute skills with device.SkillName.method()")
        print("- All results are returned to the LLM for continued reasoning")
        
    except Exception as e:
        print(f"❌ Error during demonstration: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()