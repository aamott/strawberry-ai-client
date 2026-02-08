"""Tests for repo-style skills living in subfolders under the skills directory."""

import tempfile
from pathlib import Path

from strawberry.skills.loader import SkillLoader


def test_repo_skill_loaded_with_relative_import() -> None:
    """Repo skills can use relative imports within their repo folder."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir)
        repo_dir = skills_dir / "my_repo"
        repo_dir.mkdir()

        (repo_dir / "helpers.py").write_text(
            """

def add(a: int, b: int) -> int:
    return a + b
""".lstrip()
        )

        (repo_dir / "skill.py").write_text(
            """
from .helpers import add


class MyRepoSkill:
    '''Repo-loaded skill for testing.'''

    def plus(self, a: int, b: int) -> int:
        '''Add two numbers.'''
        return add(a, b)
""".lstrip()
        )

        loader = SkillLoader(skills_dir)
        loader.load_all()

        assert loader.call_method("MyRepoSkill", "plus", 2, 3) == 5


def test_repo_entrypoint_falls_back_to_main_py() -> None:
    """If skill.py is missing, main.py can be used as an entrypoint."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir)
        repo_dir = skills_dir / "another_repo"
        repo_dir.mkdir()

        (repo_dir / "main.py").write_text(
            """

class AnotherRepoSkill:
    '''Repo-loaded skill for testing entrypoint selection.'''

    def ping(self) -> str:
        '''Return a test string.'''
        return "pong"
""".lstrip()
        )

        loader = SkillLoader(skills_dir)
        loader.load_all()

        assert loader.call_method("AnotherRepoSkill", "ping") == "pong"


def test_multiple_skill_classes_in_one_repo() -> None:
    """A single repo entrypoint can define multiple *Skill classes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir)
        repo_dir = skills_dir / "multi_skill_repo"
        repo_dir.mkdir()

        (repo_dir / "skill.py").write_text(
            """

class AlphaSkill:
    '''First skill in multi-skill repo.'''

    def greet(self) -> str:
        '''Say hello.'''
        return "hello from alpha"


class BetaSkill:
    '''Second skill in multi-skill repo.'''

    def farewell(self) -> str:
        '''Say goodbye.'''
        return "goodbye from beta"
""".lstrip()
        )

        loader = SkillLoader(skills_dir)
        skills = loader.load_all()

        skill_names = {s.name for s in skills}
        assert "AlphaSkill" in skill_names, f"AlphaSkill not found in {skill_names}"
        assert "BetaSkill" in skill_names, f"BetaSkill not found in {skill_names}"

        assert loader.call_method("AlphaSkill", "greet") == "hello from alpha"
        assert loader.call_method("BetaSkill", "farewell") == "goodbye from beta"


def test_multiple_skills_with_cross_module_imports() -> None:
    """Multi-skill repo where skills import from sibling modules."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir)
        repo_dir = skills_dir / "shared_repo"
        repo_dir.mkdir()

        (repo_dir / "utils.py").write_text(
            """

def double(x: int) -> int:
    return x * 2

def triple(x: int) -> int:
    return x * 3
""".lstrip()
        )

        (repo_dir / "skill.py").write_text(
            """
from .utils import double, triple


class DoublerSkill:
    '''Doubles numbers.'''

    def run(self, x: int) -> int:
        '''Double x.'''
        return double(x)


class TriplerSkill:
    '''Triples numbers.'''

    def run(self, x: int) -> int:
        '''Triple x.'''
        return triple(x)
""".lstrip()
        )

        loader = SkillLoader(skills_dir)
        skills = loader.load_all()

        skill_names = {s.name for s in skills}
        assert "DoublerSkill" in skill_names
        assert "TriplerSkill" in skill_names

        assert loader.call_method("DoublerSkill", "run", 5) == 10
        assert loader.call_method("TriplerSkill", "run", 5) == 15


def test_duplicate_skill_class_names_are_skipped() -> None:
    """Duplicate skill class names do not overwrite previously loaded skills.

    Repo-style skills are loaded before top-level files, so the repo version wins.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir)

        # Top-level skill
        (skills_dir / "dup_skill.py").write_text(
            """

class DuplicateSkill:
    '''Top-level duplicate skill.'''

    def top(self) -> str:
        return "top"
""".lstrip()
        )

        # Repo skill with the same class name
        repo_dir = skills_dir / "dup_repo"
        repo_dir.mkdir()
        (repo_dir / "skill.py").write_text(
            """

class DuplicateSkill:
    '''Repo duplicate skill.'''

    def repo(self) -> str:
        return "repo"
""".lstrip()
        )

        loader = SkillLoader(skills_dir)
        loader.load_all()

        assert loader.call_method("DuplicateSkill", "repo") == "repo"

        # Top-level method should not be available since the top-level duplicate is skipped.
        try:
            loader.call_method("DuplicateSkill", "top")
        except ValueError as e:
            assert "Method not found" in str(e)
        else:
            raise AssertionError("Expected ValueError for missing top() method")
