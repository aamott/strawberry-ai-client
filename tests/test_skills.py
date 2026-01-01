"""Tests for skill loading, registry, and service."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import tempfile
import os

from strawberry.skills.loader import SkillLoader, SkillInfo
from strawberry.skills.service import SkillService


@pytest.fixture
def skills_dir():
    """Create a temporary skills directory with test skills."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a test skill file
        skill_file = Path(tmpdir) / "test_skill.py"
        skill_file.write_text('''
class TestSkill:
    """A test skill."""
    
    def greet(self, name: str) -> str:
        """Greet someone.
        
        Args:
            name: Name to greet
        """
        return f"Hello, {name}!"
    
    def add(self, a: int, b: int) -> int:
        """Add two numbers."""
        return a + b
    
    def _private_method(self):
        """Should be ignored."""
        pass
''')
        yield Path(tmpdir)


@pytest.fixture
def loader(skills_dir):
    """Create a skill loader."""
    return SkillLoader(skills_dir)


class TestSkillLoader:
    """Tests for SkillLoader."""
    
    def test_load_all_finds_skills(self, loader):
        """Test that load_all finds skill classes."""
        skills = loader.load_all()
        
        assert len(skills) == 1
        assert skills[0].name == "TestSkill"
    
    def test_skill_has_methods(self, loader):
        """Test that skills have their methods extracted."""
        skills = loader.load_all()
        skill = skills[0]
        
        method_names = [m.name for m in skill.methods]
        assert "greet" in method_names
        assert "add" in method_names
        assert "_private_method" not in method_names  # Private excluded
    
    def test_method_has_signature(self, loader):
        """Test that method signatures are extracted."""
        skills = loader.load_all()
        skill = skills[0]
        
        greet = next(m for m in skill.methods if m.name == "greet")
        assert "name: str" in greet.signature
        assert "-> str" in greet.signature
    
    def test_method_has_docstring(self, loader):
        """Test that docstrings are extracted."""
        skills = loader.load_all()
        skill = skills[0]
        
        greet = next(m for m in skill.methods if m.name == "greet")
        assert "Greet someone" in greet.docstring
    
    def test_get_skill_by_name(self, loader):
        """Test getting a skill by name."""
        loader.load_all()
        
        skill = loader.get_skill("TestSkill")
        assert skill is not None
        assert skill.name == "TestSkill"
        
        missing = loader.get_skill("NonExistent")
        assert missing is None
    
    def test_get_instance(self, loader):
        """Test getting skill instances."""
        loader.load_all()
        
        instance = loader.get_instance("TestSkill")
        assert instance is not None
        
        # Same instance returned
        instance2 = loader.get_instance("TestSkill")
        assert instance is instance2
    
    def test_call_method(self, loader):
        """Test calling skill methods."""
        loader.load_all()
        
        result = loader.call_method("TestSkill", "greet", "World")
        assert result == "Hello, World!"
        
        result = loader.call_method("TestSkill", "add", 2, 3)
        assert result == 5
    
    def test_call_method_invalid_skill(self, loader):
        """Test calling method on non-existent skill."""
        loader.load_all()
        
        with pytest.raises(ValueError, match="Skill not found"):
            loader.call_method("NonExistent", "method")
    
    def test_call_method_invalid_method(self, loader):
        """Test calling non-existent method."""
        loader.load_all()
        
        with pytest.raises(ValueError, match="Method not found"):
            loader.call_method("TestSkill", "nonexistent")
    
    def test_get_registration_data(self, loader):
        """Test getting Hub registration data."""
        loader.load_all()
        
        data = loader.get_registration_data()
        
        assert len(data) == 2  # greet and add
        
        greet_data = next(d for d in data if d["function_name"] == "greet")
        assert greet_data["class_name"] == "TestSkill"
        assert "name: str" in greet_data["signature"]
    
    def test_empty_skills_dir(self):
        """Test loading from empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = SkillLoader(Path(tmpdir))
            skills = loader.load_all()
            assert skills == []
    
    def test_nonexistent_skills_dir(self):
        """Test loading from non-existent directory."""
        loader = SkillLoader(Path("/nonexistent/path"))
        skills = loader.load_all()
        assert skills == []


class TestExampleSkills:
    """Tests for the example skills."""
    
    @pytest.fixture
    def example_loader(self):
        """Load the example skills."""
        skills_path = Path(__file__).parent.parent / "skills"
        if not skills_path.exists():
            pytest.skip("Example skills not found")
        loader = SkillLoader(skills_path)
        loader.load_all()
        return loader
    
    def test_time_skill_loaded(self, example_loader):
        """Test TimeSkill is loaded."""
        skill = example_loader.get_skill("TimeSkill")
        assert skill is not None
        
        method_names = [m.name for m in skill.methods]
        assert "get_current_time" in method_names
        assert "get_current_date" in method_names
    
    def test_calculator_skill_loaded(self, example_loader):
        """Test CalculatorSkill is loaded."""
        skill = example_loader.get_skill("CalculatorSkill")
        assert skill is not None
        
        method_names = [m.name for m in skill.methods]
        assert "add" in method_names
        assert "multiply" in method_names
    
    def test_calculator_operations(self, example_loader):
        """Test calculator methods work."""
        assert example_loader.call_method("CalculatorSkill", "add", 5, 3) == 8
        assert example_loader.call_method("CalculatorSkill", "multiply", 4, 7) == 28
        assert example_loader.call_method("CalculatorSkill", "divide", 10, 2) == 5
    
    def test_calculator_divide_by_zero(self, example_loader):
        """Test divide by zero handling."""
        with pytest.raises(ValueError, match="Cannot divide by zero"):
            example_loader.call_method("CalculatorSkill", "divide", 10, 0)


class TestSkillService:
    """Tests for SkillService."""
    
    @pytest.fixture
    def service(self):
        """Create skill service with example skills."""
        skills_path = Path(__file__).parent.parent / "skills"
        if not skills_path.exists():
            pytest.skip("Example skills not found")
        return SkillService(skills_path)
    
    def test_load_skills(self, service):
        """Test loading skills through service."""
        skills = service.load_skills()
        assert len(skills) >= 2  # TimeSkill and CalculatorSkill
    
    def test_get_system_prompt(self, service):
        """Test system prompt generation."""
        prompt = service.get_system_prompt()
        
        assert "Strawberry" in prompt
        assert "TimeSkill" in prompt or "CalculatorSkill" in prompt
        assert "device" in prompt
    
    def test_parse_skill_calls(self, service):
        """Test parsing skill calls from response."""
        response = '''Here's the time:

```python
result = device.TimeSkill.get_current_time()
print(result)
```

That's the current time!'''
        
        code_blocks = service.parse_skill_calls(response)
        
        assert len(code_blocks) == 1
        assert "TimeSkill" in code_blocks[0]
    
    def test_parse_multiple_skill_calls(self, service):
        """Test parsing multiple skill calls."""
        response = '''Let me do both:

```python
time = device.TimeSkill.get_current_time()
print(time)
```

```python
result = device.CalculatorSkill.add(5, 3)
print(result)
```

Done!'''
        
        code_blocks = service.parse_skill_calls(response)
        assert len(code_blocks) == 2
    
    def test_parse_bare_code_without_fences(self, service):
        """Test parsing bare code without markdown fences."""
        # LLM sometimes outputs code without proper fences
        response = '''Let me try that.
print(device.TimeSkill.get_current_time())
'''
        
        code_blocks = service.parse_skill_calls(response)
        
        assert len(code_blocks) == 1
        assert "device.TimeSkill.get_current_time()" in code_blocks[0]
    
    def test_parse_bare_code_adds_print(self, service):
        """Test that bare code without print() gets wrapped."""
        response = '''Here you go:
device.CalculatorSkill.add(5, 3)
'''
        
        code_blocks = service.parse_skill_calls(response)
        
        assert len(code_blocks) == 1
        assert code_blocks[0].startswith("print(")
    
    def test_parse_tool_code_fence(self, service):
        """Test parsing ```tool_code``` fences (some LLMs use this)."""
        response = '''Let me search for that.

```tool_code
print(device.search_skills("browser"))
```

Here are the results.'''
        
        code_blocks = service.parse_skill_calls(response)
        
        assert len(code_blocks) == 1
        assert "device.search_skills" in code_blocks[0]
    
    def test_parse_various_fence_types(self, service):
        """Test parsing various code fence types."""
        # Test ```code
        response1 = '```code\nprint(device.TimeSkill.get_current_time())\n```'
        assert len(service.parse_skill_calls(response1)) == 1
        
        # Test ```py
        response2 = '```py\nprint(device.TimeSkill.get_current_time())\n```'
        assert len(service.parse_skill_calls(response2)) == 1
        
        # Test bare ``` (no language)
        response3 = '```\nprint(device.TimeSkill.get_current_time())\n```'
        assert len(service.parse_skill_calls(response3)) == 1
    
    def test_execute_code_success(self, service):
        """Test executing skill code."""
        service.load_skills()
        
        code = "result = device.CalculatorSkill.add(10, 5)\nprint(result)"
        result = service.execute_code(code)
        
        assert result.success
        assert "15" in result.result
    
    def test_execute_code_error(self, service):
        """Test executing code with error."""
        service.load_skills()
        
        code = "result = device.NonExistentSkill.method()"
        result = service.execute_code(code)
        
        assert not result.success
        assert result.error is not None
    
    def test_process_response(self, service):
        """Test processing LLM response with skill calls."""
        service.load_skills()
        
        response = '''The sum is:

```python
result = device.CalculatorSkill.add(7, 3)
print(result)
```'''
        
        processed, tool_calls = service.process_response(response)
        
        assert len(tool_calls) == 1
        assert tool_calls[0]["success"]
        assert "10" in processed  # Result included
    
    def test_process_response_no_skills(self, service):
        """Test processing response without skill calls."""
        service.load_skills()
        
        response = "Just a normal response without any code."
        
        processed, tool_calls = service.process_response(response)
        
        assert processed == response
        assert len(tool_calls) == 0


class TestDeviceProxy:
    """Tests for device proxy discovery methods."""
    
    @pytest.fixture
    def service(self):
        """Create skill service with example skills."""
        skills_path = Path(__file__).parent.parent / "skills"
        if not skills_path.exists():
            pytest.skip("Example skills not found")
        service = SkillService(skills_path)
        service.load_skills()
        return service
    
    def test_search_skills_finds_matches(self, service):
        """Test search_skills finds matching skills."""
        code = "results = device.search_skills('time')\nprint(results)"
        result = service.execute_code(code)
        
        assert result.success
        assert "TimeSkill" in result.result
        assert "get_current_time" in result.result
    
    def test_search_skills_empty_query(self, service):
        """Test search_skills with empty query returns all."""
        code = "results = device.search_skills('')\nprint(len(results))"
        result = service.execute_code(code)
        
        assert result.success
        # Should have multiple methods from TimeSkill and CalculatorSkill
        count = int(result.result)
        assert count >= 5
    
    def test_search_skills_no_matches(self, service):
        """Test search_skills with no matches."""
        code = "results = device.search_skills('nonexistent_xyz')\nprint(len(results))"
        result = service.execute_code(code)
        
        assert result.success
        assert result.result == "0"
    
    def test_describe_function_success(self, service):
        """Test describe_function returns function details."""
        code = "info = device.describe_function('TimeSkill.get_current_time')\nprint(info)"
        result = service.execute_code(code)
        
        assert result.success
        assert "def get_current_time" in result.result
        assert "Get the current time" in result.result
    
    def test_describe_function_invalid_path(self, service):
        """Test describe_function with invalid path format."""
        code = "info = device.describe_function('invalid')\nprint(info)"
        result = service.execute_code(code)
        
        assert result.success
        assert "Error" in result.result
    
    def test_describe_function_skill_not_found(self, service):
        """Test describe_function with non-existent skill."""
        code = "info = device.describe_function('FakeSkill.method')\nprint(info)"
        result = service.execute_code(code)
        
        assert result.success
        assert "not found" in result.result.lower()
    
    def test_agent_workflow(self, service):
        """Test complete agent workflow: search → describe → call."""
        # Step 1: Search
        code1 = "results = device.search_skills('add')\nprint(results)"
        result1 = service.execute_code(code1)
        assert result1.success
        assert "CalculatorSkill.add" in result1.result
        
        # Step 2: Describe
        code2 = "info = device.describe_function('CalculatorSkill.add')\nprint(info)"
        result2 = service.execute_code(code2)
        assert result2.success
        assert "a: float" in result2.result
        
        # Step 3: Call
        code3 = "result = device.CalculatorSkill.add(10, 20)\nprint(result)"
        result3 = service.execute_code(code3)
        assert result3.success
        assert "30" in result3.result

