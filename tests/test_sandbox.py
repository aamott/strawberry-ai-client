"""Tests for the sandbox module."""

import pytest
import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from strawberry.skills.sandbox import (
    SandboxExecutor,
    SandboxConfig,
    ExecutionResult,
    Gatekeeper,
    ProxyGenerator,
)
from strawberry.skills.sandbox.process import DenoProcessManager, DenoNotFoundError
from strawberry.skills.sandbox.bridge import BridgeClient, BridgeError
from strawberry.skills.loader import SkillInfo, SkillMethod, SkillLoader


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_skill_info():
    """Create a mock skill info."""
    class MockTimeSkill:
        def get_time(self):
            return "12:00 PM"
    
    instance = MockTimeSkill()
    
    mock_method = SkillMethod(
        name="get_time",
        signature="get_time() -> str",
        docstring="Get the current time.",
        callable=instance.get_time,
    )
    
    skill_info = SkillInfo(
        name="TimeSkill",
        class_obj=MockTimeSkill,
        methods=[mock_method],
        module_path=Path("test.py"),
    )
    # Add instance attribute for gatekeeper to use
    skill_info.instance = instance
    return skill_info


@pytest.fixture
def mock_loader(mock_skill_info):
    """Create a mock skill loader."""
    loader = Mock(spec=SkillLoader)
    loader.get_all_skills.return_value = [mock_skill_info]
    loader.get_skill.return_value = mock_skill_info
    return loader


@pytest.fixture
def gatekeeper(mock_loader):
    """Create a gatekeeper with mock loader."""
    gate = Gatekeeper(mock_loader)
    return gate


@pytest.fixture
def proxy_generator(mock_skill_info):
    """Create a proxy generator."""
    return ProxyGenerator([mock_skill_info])


@pytest.fixture
def mock_skill_method():
    """Create a standalone mock skill method."""
    return SkillMethod(
        name="get_time",
        signature="get_time() -> str",
        docstring="Get the current time.",
        callable=lambda: "12:00 PM",
    )


# =============================================================================
# ProxyGenerator Tests
# =============================================================================

class TestProxyGenerator:
    """Tests for ProxyGenerator."""
    
    def test_generate_creates_code(self, proxy_generator):
        """Should generate non-empty proxy code."""
        code = proxy_generator.generate()
        assert code
        assert "device = _DeviceProxy()" in code
    
    def test_generate_includes_skill_names(self, proxy_generator):
        """Should include skill names in generated code."""
        code = proxy_generator.generate()
        assert "TimeSkill" in code
    
    def test_generate_includes_methods(self, proxy_generator):
        """Should include method info in generated code."""
        code = proxy_generator.generate()
        assert "get_time" in code
    
    def test_generate_caches_result(self, proxy_generator):
        """Should cache generated code."""
        code1 = proxy_generator.generate()
        code2 = proxy_generator.generate()
        assert code1 is code2  # Same object (cached)
    
    def test_invalidate_clears_cache(self, proxy_generator):
        """Should clear cache on invalidate."""
        code1 = proxy_generator.generate()
        proxy_generator.invalidate()
        code2 = proxy_generator.generate()
        assert code1 is not code2  # Different objects
    
    def test_includes_search_skills(self, proxy_generator):
        """Should include search_skills method."""
        code = proxy_generator.generate()
        assert "def search_skills" in code
    
    def test_includes_describe_function(self, proxy_generator):
        """Should include describe_function method."""
        code = proxy_generator.generate()
        assert "def describe_function" in code


# =============================================================================
# Gatekeeper Tests
# =============================================================================

class TestGatekeeper:
    """Tests for Gatekeeper."""
    
    def test_is_allowed_valid_path(self, gatekeeper):
        """Should allow valid skill paths."""
        assert gatekeeper.is_allowed("TimeSkill.get_time")
    
    def test_is_allowed_invalid_path(self, gatekeeper):
        """Should reject invalid skill paths."""
        assert not gatekeeper.is_allowed("FakeSkill.hack")
        assert not gatekeeper.is_allowed("TimeSkill.nonexistent")
    
    def test_execute_calls_skill(self, gatekeeper, mock_skill_info):
        """Should execute valid skill calls."""
        result = gatekeeper.execute("TimeSkill.get_time", [], {})
        assert result == "12:00 PM"
    
    def test_execute_raises_for_blocked(self, gatekeeper):
        """Should raise for blocked paths."""
        from strawberry.skills.sandbox.gatekeeper import SkillNotAllowedError
        
        with pytest.raises(SkillNotAllowedError):
            gatekeeper.execute("FakeSkill.hack", [], {})
    
    def test_execute_with_args(self, mock_loader):
        """Should pass arguments to skill method."""
        class MockSkill:
            def add(self, a, b):
                return a + b
        
        instance = MockSkill()
        mock_skill = SkillInfo(
            name="MathSkill",
            class_obj=MockSkill,
            methods=[SkillMethod(
                name="add",
                signature="add(a, b)",
                docstring="Add two numbers.",
                callable=instance.add,
            )],
            module_path=Path("test.py"),
        )
        mock_skill.instance = instance
        mock_loader.get_all_skills.return_value = [mock_skill]
        mock_loader.get_skill.return_value = mock_skill
        
        gatekeeper = Gatekeeper(mock_loader)
        result = gatekeeper.execute("MathSkill.add", [2, 3], {})
        assert result == 5
    
    def test_refresh_updates_allow_list(self, gatekeeper, mock_loader):
        """Should update allow-list on refresh."""
        # Add a new skill
        class NewMockSkill:
            def new_method(self):
                return None
        
        instance = NewMockSkill()
        new_method = SkillMethod(
            name="new_method",
            signature="new_method()",
            docstring="New method.",
            callable=instance.new_method,
        )
        new_skill = SkillInfo(
            name="NewSkill",
            class_obj=NewMockSkill,
            methods=[new_method],
            module_path=Path("new.py"),
        )
        new_skill.instance = instance
        mock_loader.get_all_skills.return_value.append(new_skill)
        
        # Before refresh
        assert not gatekeeper.is_allowed("NewSkill.new_method")
        
        # After refresh
        gatekeeper.refresh()
        assert gatekeeper.is_allowed("NewSkill.new_method")
    
    def test_sanitize_error(self, gatekeeper):
        """Should sanitize error messages."""
        raw_error = 'File "/home/user/secret/code.py", line 42, in module'
        sanitized = gatekeeper._sanitize_error(raw_error)
        
        assert "/home/user/secret/code.py" not in sanitized
        assert "line ?" in sanitized


# =============================================================================
# DenoProcessManager Tests
# =============================================================================

class TestDenoProcessManager:
    """Tests for DenoProcessManager."""
    
    def test_verify_deno_not_found(self):
        """Should raise when Deno not found."""
        manager = DenoProcessManager(deno_path="/nonexistent/deno")
        
        with pytest.raises(DenoNotFoundError):
            manager._verify_deno()
    
    def test_is_running_false_initially(self):
        """Should report not running initially."""
        manager = DenoProcessManager()
        assert not manager.is_running
    
    @pytest.mark.asyncio
    async def test_kill_when_not_running(self):
        """Should handle kill when not running."""
        manager = DenoProcessManager()
        await manager.kill()  # Should not raise
        assert not manager.is_running


# =============================================================================
# BridgeClient Tests  
# =============================================================================

class TestBridgeClient:
    """Tests for BridgeClient."""
    
    def test_init(self):
        """Should initialize with streams and handler."""
        stdin = Mock()
        stdout = Mock()
        handler = Mock()
        
        client = BridgeClient(stdin, stdout, handler)
        
        assert client.stdin is stdin
        assert client.stdout is stdout
        assert client.call_handler is handler


# =============================================================================
# SandboxExecutor Tests
# =============================================================================

class TestSandboxExecutor:
    """Tests for SandboxExecutor."""
    
    def test_init(self, gatekeeper, proxy_generator):
        """Should initialize with components."""
        config = SandboxConfig(enabled=True, timeout_seconds=5.0)
        executor = SandboxExecutor(gatekeeper, proxy_generator, config)
        
        assert executor.gatekeeper is gatekeeper
        assert executor.proxy_generator is proxy_generator
        assert executor.config.timeout_seconds == 5.0
    
    @pytest.mark.asyncio
    async def test_execute_disabled_sandbox(self, gatekeeper, proxy_generator):
        """Should use direct execution when sandbox disabled."""
        config = SandboxConfig(enabled=False)
        executor = SandboxExecutor(gatekeeper, proxy_generator, config)
        
        result = await executor.execute('print("hello")')
        
        assert result.success
        assert result.output == "hello"
    
    @pytest.mark.asyncio
    async def test_execute_direct_skill_call(self, gatekeeper, proxy_generator):
        """Should execute skill calls in direct mode."""
        config = SandboxConfig(enabled=False)
        executor = SandboxExecutor(gatekeeper, proxy_generator, config)
        
        result = await executor.execute('print(device.TimeSkill.get_time())')
        
        assert result.success
        assert result.output == "12:00 PM"
    
    @pytest.mark.asyncio
    async def test_execute_direct_search_skills(self, gatekeeper, proxy_generator):
        """Should handle search_skills in direct mode."""
        config = SandboxConfig(enabled=False)
        executor = SandboxExecutor(gatekeeper, proxy_generator, config)
        
        result = await executor.execute('print(device.search_skills("time"))')
        
        assert result.success
        assert "TimeSkill" in result.output
    
    @pytest.mark.asyncio
    async def test_execute_direct_describe_function(self, gatekeeper, proxy_generator):
        """Should handle describe_function in direct mode."""
        config = SandboxConfig(enabled=False)
        executor = SandboxExecutor(gatekeeper, proxy_generator, config)
        
        result = await executor.execute('print(device.describe_function("TimeSkill.get_time"))')
        
        assert result.success
        assert "get_time" in result.output
    
    @pytest.mark.asyncio
    async def test_execute_direct_error(self, gatekeeper, proxy_generator):
        """Should return error for invalid code."""
        config = SandboxConfig(enabled=False)
        executor = SandboxExecutor(gatekeeper, proxy_generator, config)
        
        result = await executor.execute('raise ValueError("test error")')
        
        assert not result.success
        assert "test error" in result.error
    
    @pytest.mark.asyncio
    async def test_execute_direct_skill_not_found(self, gatekeeper, proxy_generator):
        """Should return error for unknown skill."""
        config = SandboxConfig(enabled=False)
        executor = SandboxExecutor(gatekeeper, proxy_generator, config)
        
        result = await executor.execute('print(device.FakeSkill.method())')
        
        assert not result.success
        # Error should indicate something went wrong with the skill access
        assert result.error is not None
    
    @pytest.mark.asyncio
    async def test_refresh_skills(self, gatekeeper, proxy_generator):
        """Should refresh components."""
        executor = SandboxExecutor(gatekeeper, proxy_generator)
        
        # Should not raise
        executor.refresh_skills()
    
    def test_sanitize_error(self, gatekeeper, proxy_generator):
        """Should sanitize error messages."""
        executor = SandboxExecutor(gatekeeper, proxy_generator)
        
        # Test with proper traceback format (File "...", line X)
        raw = 'File "/path/to/secret.py", line 42, in some_internal_proxy'
        sanitized = executor._sanitize_error(raw)
        
        assert "/path/to/secret.py" not in sanitized
        assert "<sandbox>" in sanitized


# =============================================================================
# ExecutionResult Tests
# =============================================================================

class TestExecutionResult:
    """Tests for ExecutionResult dataclass."""
    
    def test_success_result(self):
        """Should create success result."""
        result = ExecutionResult(success=True, output="hello")
        assert result.success
        assert result.output == "hello"
        assert result.error is None
        assert not result.timed_out
    
    def test_error_result(self):
        """Should create error result."""
        result = ExecutionResult(success=False, error="Something went wrong")
        assert not result.success
        assert result.error == "Something went wrong"
        assert result.output is None
    
    def test_timeout_result(self):
        """Should create timeout result."""
        result = ExecutionResult(success=False, error="Timeout", timed_out=True)
        assert not result.success
        assert result.timed_out


# =============================================================================
# SandboxConfig Tests
# =============================================================================

class TestSandboxConfig:
    """Tests for SandboxConfig dataclass."""
    
    def test_defaults(self):
        """Should have sensible defaults."""
        config = SandboxConfig()
        assert config.timeout_seconds == 5.0
        assert config.memory_limit_mb == 128
        assert config.deno_path == "deno"
        assert config.enabled
    
    def test_custom_values(self):
        """Should accept custom values."""
        config = SandboxConfig(
            timeout_seconds=10.0,
            memory_limit_mb=256,
            deno_path="/usr/local/bin/deno",
            enabled=False,
        )
        assert config.timeout_seconds == 10.0
        assert config.memory_limit_mb == 256
        assert config.deno_path == "/usr/local/bin/deno"
        assert not config.enabled

