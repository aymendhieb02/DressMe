"""A metadata-only Hugging Face cache must not mask usable offline E5 weights."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from dressme import rag


def snapshot(root, complete=True):
    for name in ('config.json', 'modules.json', '1_Pooling/config.json', 'tokenizer_config.json', 'tokenizer.json'):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}', encoding='utf-8')
    if complete:
        (root / 'model.safetensors').write_bytes(b'test weights')
    return root


def loader(monkeypatch, project, global_cache, downloads=False):
    import huggingface_hub
    import sentence_transformers

    monkeypatch.setattr(rag, 'ALLOW_DOWNLOADS', downloads)
    def find(*args, **kwargs):
        return str(project if kwargs.get('cache_dir') is not None else global_cache)
    download = Mock(side_effect=find)
    model = SimpleNamespace(tokenizer=object())
    construct = Mock(return_value=model)
    monkeypatch.setattr(huggingface_hub, 'snapshot_download', download)
    monkeypatch.setattr(sentence_transformers, 'SentenceTransformer', construct)
    return download, construct


def test_incomplete_project_cache_uses_complete_global_cache_offline(tmp_path, monkeypatch):
    project = snapshot(tmp_path / 'project', complete=False)
    global_cache = snapshot(tmp_path / 'global')
    download, construct = loader(monkeypatch, project, global_cache)
    rag.E5Encoder()
    assert download.call_count == 2
    assert all(call.kwargs['local_files_only'] for call in download.call_args_list)
    construct.assert_called_once_with(str(global_cache), device='cpu', local_files_only=True)


def test_complete_project_cache_is_portable_without_global_cache(tmp_path, monkeypatch):
    project = snapshot(tmp_path / 'project')
    download, construct = loader(monkeypatch, project, tmp_path / 'absent')
    rag.E5Encoder()
    assert download.call_count == 1
    construct.assert_called_once_with(str(project), device='cpu', local_files_only=True)


def test_no_complete_cache_offline_does_not_attempt_network_or_model_load(tmp_path, monkeypatch):
    project = snapshot(tmp_path / 'project', complete=False)
    global_cache = snapshot(tmp_path / 'global', complete=False)
    download, construct = loader(monkeypatch, project, global_cache)
    with pytest.raises(FileNotFoundError, match='No complete local'):
        rag.E5Encoder()
    assert all(call.kwargs['local_files_only'] for call in download.call_args_list)
    construct.assert_not_called()


def test_lfs_pointer_is_not_a_model_and_missing_tokenizer_is_incomplete(tmp_path):
    project = snapshot(tmp_path / 'project')
    weights = project / 'model.safetensors'
    weights.write_bytes(b'version https://git-lfs.github.com/spec/v1\noid sha256:example\n')
    assert not rag.E5Encoder._complete_snapshot(project)
    weights.write_bytes(b'test weights')
    (project / 'tokenizer.json').unlink()
    assert not rag.E5Encoder._complete_snapshot(project)


def test_incomplete_cache_can_be_repaired_by_explicit_download(tmp_path, monkeypatch):
    project = snapshot(tmp_path / 'project', complete=False)
    global_cache = snapshot(tmp_path / 'global', complete=False)
    download, construct = loader(monkeypatch, project, global_cache, downloads=True)
    def find(*args, **kwargs):
        if not kwargs['local_files_only']:
            snapshot(project)
        return str(project if kwargs.get('cache_dir') is not None else global_cache)
    download.side_effect = find
    rag.E5Encoder()
    assert download.call_count == 3
    assert download.call_args.kwargs['local_files_only'] is False
    construct.assert_called_once_with(str(project), device='cpu', local_files_only=True)
