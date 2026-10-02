"""Есть ли чем распознавать речь — одна проверка на всех.

Три места проверяли это руками, и все три ошибались одинаково:
`settings.deepgram_api_key or settings.whisper_api_key`. Поля
whisper_api_key в конфиге НЕТ — его удалили, whisper ходит через
groq_api_key. Пока ключ Deepgram задан, короткое замыкание прячет
ошибку; стоит ему опустеть — AttributeError вместо честного «нет ключа»,
и голосовое сообщение в Telegram падает в «Необработанная ошибка».
Поймано 02.10.
"""

from __future__ import annotations

import pytest

from app.asr.factory import asr_available
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_deepgram_с_ключом(monkeypatch):
    monkeypatch.setenv("ASR_PROVIDER", "deepgram")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "ключ")
    assert asr_available() is True


def test_deepgram_без_ключа_не_роняет(monkeypatch):
    """Ровно тот случай, который падал с AttributeError."""
    monkeypatch.setenv("ASR_PROVIDER", "deepgram")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "")
    assert asr_available() is False


def test_whisper_берёт_ключ_groq(monkeypatch):
    """У whisper своего ключа нет и не было — он ходит через Groq."""
    monkeypatch.setenv("ASR_PROVIDER", "whisper")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "ключ-groq")
    assert asr_available() is True


def test_whisper_без_ключа_groq(monkeypatch):
    monkeypatch.setenv("ASR_PROVIDER", "whisper")
    monkeypatch.setenv("GROQ_API_KEY", "")
    assert asr_available() is False


def test_неизвестный_провайдер_это_нет(monkeypatch):
    monkeypatch.setenv("ASR_PROVIDER", "выдуманный")
    assert asr_available() is False


def test_поля_whisper_api_key_в_конфиге_нет():
    """Чтобы его не завели обратно по мотивам старого кода."""
    assert not hasattr(get_settings(), "whisper_api_key")
