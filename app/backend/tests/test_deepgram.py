from app.asr.deepgram import format_diarized_utterances


def test_single_speaker_joins_with_spaces_no_newlines():
    utterances = [{"speaker": 0, "transcript": "Привет,"}, {"speaker": 0, "transcript": "как дела?"}]
    assert format_diarized_utterances(utterances) == "Привет, как дела?"


def test_multiple_speakers_separated_by_blank_line():
    # Реальная жалоба: результат вставляется в markdown-карточку
    # (serialize_image_ocr_result → ReactMarkdown) — одинарный перенос
    # строки НЕ разрывает абзац в markdown, реплики разных спикеров
    # слипались в один сплошной кусок текста без видимых переносов.
    # Двойной перенос — это и есть исправление, проверяем его тут.
    utterances = [
        {"speaker": 0, "transcript": "Привет!"},
        {"speaker": 1, "transcript": "Привет, как дела?"},
    ]
    result = format_diarized_utterances(utterances)
    assert result == "Спикер 1: Привет!\n\nСпикер 2: Привет, как дела?"


def test_no_speaker_field_treated_as_single_speaker():
    utterances = [{"transcript": "Текст без метки спикера."}]
    assert format_diarized_utterances(utterances) == "Текст без метки спикера."


def test_empty_utterances_returns_empty_string():
    assert format_diarized_utterances([]) == ""
