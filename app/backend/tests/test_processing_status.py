"""«Распознано, но ничего не нашлось» — не сбой.

Живой разбор 10.10. Два видео от 04.10 стояли в базе как "failed", и я
сам прочитал это как поломку — а в логах было «Deepgram не распознал речь
(пустой транскрипт, аудио 227561 байт)»: провайдер отработал и честно
вернул пустоту, в видео просто нет речи.

Человеку это сказано правильно, прямо в заметке («🔇 В видео не
распознано речи»). А в базе оба случая выглядели одинаково — и ассистент
через get_file видел processing="failed" у совершенно целого файла.
"""

from __future__ import annotations

import pytest

from app.processing_status import STATUS_EMPTY
from app.tools.files import _processing_note


class TestЧтоВидитМодель:
    def test_пустое_распознавание_не_называется_сбоем(self):
        note = _processing_note(STATUS_EMPTY)

        assert note is not None
        assert "цел" in note, "модель должна понять, что файл в порядке"
        assert "не удалось" not in note

    def test_настоящий_сбой_назван_сбоем(self):
        assert _processing_note("failed") == "обработать не удалось"

    def test_готовое_и_неприменимое_молчат(self):
        """Лишнее поле в результате — лишний повод для модели о нём
        заговорить."""
        assert _processing_note("done") is None
        assert _processing_note("none") is None

    def test_промежуточные_состояния_передаются_как_есть(self):
        assert _processing_note("pending") == "pending"
        assert _processing_note("processing") == "processing"

    def test_незнакомое_значение_не_роняет(self):
        assert _processing_note("какое-то-новое") == "какое-то-новое"


class TestВсеКонвейерыСогласованы:
    @pytest.mark.parametrize("module", [
        "app.transcription", "app.note_recording", "app.pdf_processing", "app.tickets", "app.vision",
    ])
    def test_пустой_результат_не_помечается_failed(self, module):
        """Пять конвейеров писали одно и то же `else "failed"`. Если
        появится шестой — пусть этот тест напомнит, что состояний два."""
        import importlib
        import inspect

        source = inspect.getsource(importlib.import_module(module))

        assert 'else "failed"' not in source, (
            f"{module}: пустой результат распознавания — не сбой, нужен STATUS_EMPTY"
        )
