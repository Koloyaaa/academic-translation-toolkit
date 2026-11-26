from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def skills(tier):
    root = ROOT / 'skills' / tier / 'skills'
    return {path.name: path for path in root.iterdir() if path.is_dir() and (path / 'SKILL.md').is_file()}


def test_each_tier_has_its_own_valid_skill_entries():
    for tier in ('lite', 'plus', 'pro', 'max'):
        entries = skills(tier)
        assert entries, tier
        for name, directory in entries.items():
            assert not directory.is_symlink()
            content = (directory / 'SKILL.md').read_text(encoding='utf-8')
            assert re.search(r'^name:\s*' + re.escape(name) + r'\s*$', content, re.MULTILINE), (tier, name)


def test_smart_handout_completion_is_available_only_in_plus_pro_and_max():
    assert len(skills('plus')) == 3
    for tier in ('plus', 'pro', 'max'):
        entries = skills(tier)
        completer_names = [name for name in entries if 'handout-completer' in name]
        assert len(completer_names) == 1, (tier, completer_names)
        completer = entries[completer_names[0]]
        assert (completer / 'references' / 'math-proof-completion.md').is_file()
        assert '待老师确认' in (completer / 'SKILL.md').read_text(encoding='utf-8')
    assert not any('handout-completer' in name for name in skills('lite'))


def test_pro_and_max_each_contain_the_complete_new_group():
    assert len(skills('max')) == 13
    assert set(skills('pro')) == set(skills('max'))


def test_completion_rendering_hooks_are_present_in_each_supported_tier():
    for tier in ('plus', 'pro', 'max'):
        builders = ROOT / 'skills' / tier / 'skills'
        translator = next(path for path in builders.iterdir() if path.name == 'foreign-academic-translator-plus') if tier == 'plus' else builders / 'translation-orchestrator'
        scripts = translator / 'scripts' / 'builders'
        assert 'wrap_handout_completion_details' in (scripts / 'html_builder.py').read_text(encoding='utf-8')
        assert 'mark_handout_completion_blocks' in (scripts / 'docx_builder.py').read_text(encoding='utf-8')
        assert 'strip_handout_completion_markers' in (scripts / 'md_builder.py').read_text(encoding='utf-8')
        if tier in ('pro', 'max'):
            assert 'smart-completion' in (scripts / 'pptx_builder.py').read_text(encoding='utf-8')


def test_max_contains_runtime_scripts():
    maximum = ROOT / 'skills' / 'max' / 'skills' / 'translation-orchestrator' / 'scripts'
    for name in ('workflow_state.py', 'builder.py', 'text_extractor.py'):
        assert (maximum / name).is_file()
