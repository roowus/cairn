"""Skills loader: built-in discovery, parsing, user override, turn rendering."""

from __future__ import annotations

from cairn.skills import Skill, discover_skills, render_turn


def test_discovers_builtin_skills():
    skills = discover_skills()
    names = set(skills)
    assert {"investigate-person", "domain-recon", "ip-enrich", "breach-check"} <= names
    for s in skills.values():
        assert s.description
        assert s.usage.startswith("/")
        assert s.body.strip()


def test_render_turn_prepends_playbook():
    s = Skill(name="x", description="d", usage="/x <t>", body="# Playbook\nDo the thing.")
    out = render_turn(s, "example.com")
    assert out.startswith("# Playbook")
    assert "Investigation request: example.com" in out


def test_user_skill_overrides_builtin(tmp_path):
    # conftest points CAIRN_CONFIG_DIR at tmp_path -> user skills dir is tmp_path/skills
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "ip-enrich.md").write_text(
        "---\nname: ip-enrich\ndescription: MINE\nusage: /ip-enrich <ip>\n---\nOVERRODE",
        encoding="utf-8",
    )
    skills = discover_skills()
    assert skills["ip-enrich"].description == "MINE"
    assert "OVERRODE" in skills["ip-enrich"].body


def test_parse_without_frontmatter(tmp_path):
    # a bare skill (no frontmatter) still loads: name = filename, desc = first line
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "quick.md").write_text("# Quick lookup\nbody line", encoding="utf-8")
    skills = discover_skills()
    assert "quick" in skills
    assert skills["quick"].description == "Quick lookup"
