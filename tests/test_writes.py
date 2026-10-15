import dataclasses

import pytest

from maclasse_mcp import writes, config


def test_gate_refuse_sans_activation(monkeypatch):
    monkeypatch.setattr(writes, "SETTINGS", dataclasses.replace(config.SETTINGS, enable_writes=False))
    g = writes.WriteGate()
    with pytest.raises(RuntimeError):
        g.prepare("associer_noms", {}, lambda: {})


def test_gate_jeton_unique(monkeypatch):
    monkeypatch.setattr(writes, "SETTINGS", dataclasses.replace(config.SETTINGS, enable_writes=True))
    g = writes.WriteGate()
    calls = []
    r = g.prepare("associer_noms", {"n": 1}, lambda: calls.append(1) or {"ok": True})
    assert r["apercu"] == {"n": 1} and calls == []
    assert g.confirm(r["jeton"])["ok"] is True and calls == [1]
    with pytest.raises(RuntimeError):
        g.confirm(r["jeton"])
    with pytest.raises(RuntimeError):
        g.prepare("supprimer_tout", {}, lambda: {})
