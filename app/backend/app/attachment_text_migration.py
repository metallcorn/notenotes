"""Разовый перенос: распознанный текст файлов — из заметок в загрузки.

Запуск (внутри контейнера бэкенда, ПОСЛЕ `sudo notenotes-backup-now`):

    python -m app.attachment_text_migration            # только отчёт
    python -m app.attachment_text_migration --apply    # записать

Почему так — app/attachment_text.py. Что делает с каждым блоком вложения,
у которого есть data-text:

  * текст совпадает с transcript загрузки — data-text убирается;
  * transcript пуст (docx, PDF без автообработки — текст уходил только в
    заметку) — сначала текст переносится в загрузку, потом убирается;
  * билет — data-text это «синонимы + transcript»: синонимы переезжают в
    properties.search_keywords, data-text убирается;
  * загрузки больше нет — блок НЕ трогается: текст в заметке остался
    единственной копией;
  * текст расходится с transcript — блок НЕ трогается, попадает в отчёт.

У карточки текста картинки, вставленной до августа, нет data-upload-id —
он дописывается, иначе карточке без своего текста неоткуда его взять.

Каждая изменённая заметка получает версию в item_versions до записи, а
перед записью проверяется, что весь убранный текст лежит в загрузке.
"""
from __future__ import annotations

import argparse
import asyncio
import uuid

from sqlalchemy import select

from app.attachment_text import BLOCK_RE, DATA_TEXT_RE, find_attachments
from app.db import async_session
from app.models import Item, ItemVersion, Space, Upload
from app.tickets import _SEARCH_SYNONYMS


def _norm(text: str) -> str:
    return " ".join(text.split())


def _ticket_keywords(inline: str, transcript: str) -> str | None:
    """Синонимы, если data-text билета — это «синонимы\\n\\ntranscript»."""
    for keywords in _SEARCH_SYNONYMS.values():
        if _norm(inline) == _norm(f"{keywords}\n\n{transcript}"):
            return keywords
    return None


async def run(apply: bool) -> None:
    async with async_session() as db:
        items = (
            await db.execute(
                select(Item)
                .join(Space, Space.id == Item.space_id)
                .where(Item.deleted_at.is_(None), Space.is_vault.is_(False), Item.content.like('%data-text="%'))
            )
        ).scalars().all()

        stats: dict[str, int] = {}
        report: list[str] = []
        changed_items = 0

        for item in items:
            content = item.content
            attachments = [a for a in find_attachments(content) if a.inline_text]
            if not attachments:
                continue
            uploads = {
                u.id: u
                for u in (
                    await db.execute(select(Upload).where(Upload.id.in_({a.upload_id for a in attachments if a.upload_id})))
                ).scalars().all()
            }

            replacements: list[tuple[int, int, str]] = []
            moved: list[tuple[Upload, str]] = []
            for a in attachments:
                upload = uploads.get(a.upload_id) if a.upload_id else None
                if upload is None:
                    stats["оставлен: загрузки нет"] = stats.get("оставлен: загрузки нет", 0) + 1
                    report.append(f"  оставлен (загрузки нет): «{item.title[:50]}» {a.upload_id}")
                    continue
                transcript = upload.transcript or ""
                if not transcript.strip():
                    upload.transcript = a.inline_text
                    if upload.transcription_status in (None, "none"):
                        upload.transcription_status = "done"
                    verdict = "перенесён в загрузку"
                elif _norm(transcript) == _norm(a.inline_text):
                    verdict = "совпал с загрузкой"
                elif a.kind == "data-ticket-attachment" and (keywords := _ticket_keywords(a.inline_text, transcript)):
                    item.properties = {**(item.properties or {}), "search_keywords": keywords}
                    verdict = "билет: синонимы в properties"
                else:
                    stats["оставлен: текст расходится"] = stats.get("оставлен: текст расходится", 0) + 1
                    report.append(
                        f"  оставлен (расходится): «{item.title[:50]}» {upload.id} "
                        f"заметка {len(a.inline_text)} / файл {len(transcript)} симв."
                    )
                    continue
                stats[verdict] = stats.get(verdict, 0) + 1

                tag = DATA_TEXT_RE.sub("", content[a.start:a.end])
                if a.kind == "data-image-ocr-result" and "data-upload-id=" not in tag:
                    can = upload.content_type.startswith(("image/", "video/")) or upload.content_type == "application/pdf"
                    extra = f' data-upload-id="{upload.id}"' + (' data-can-reprocess="1"' if can else "")
                    tag = tag.replace("<div data-image-ocr-result", f"<div data-image-ocr-result{extra}", 1)
                    stats["дописан data-upload-id"] = stats.get("дописан data-upload-id", 0) + 1
                replacements.append((a.start, a.end, tag))
                moved.append((upload, a.inline_text))

            if not replacements:
                continue

            new_content = content
            for start, end, tag in sorted(replacements, reverse=True):
                new_content = new_content[:start] + tag + new_content[end:]

            # Проверка «текст не потерян»: всё, что убрано из заметки, лежит
            # в загрузке. Билет сравнивается без синонимов — они в properties.
            for upload, inline in moved:
                have = _norm(upload.transcript or "")
                if _norm(inline) != have and not _norm(inline).endswith(have):
                    raise RuntimeError(f"Текст потерялся бы: заметка {item.id}, файл {upload.id}")
            # И что вне блоков вложений заметка не изменилась ни на символ.
            if BLOCK_RE.sub("", new_content) != BLOCK_RE.sub("", content):
                raise RuntimeError(f"Изменилось что-то кроме блоков вложений: заметка {item.id}")

            changed_items += 1
            report.append(
                f"  «{item.title[:50]}»: {len(replacements)} блок(ов), {len(content)} → {len(new_content)} симв."
            )
            if apply:
                db.add(ItemVersion(item_id=item.id, title=item.title, content=content, author_id=item.author_id))
                item.content = new_content

        # Билеты, чей блок не тронут (загрузки нет, текст разошёлся) или
        # был без data-text, — синонимы всё равно нужны для поиска: их
        # тип уже известен из properties.
        tickets = (
            await db.execute(
                select(Item)
                .join(Space, Space.id == Item.space_id)
                .where(Item.deleted_at.is_(None), Space.is_vault.is_(False), Item.material_type == "ticket")
            )
        ).scalars().all()
        for ticket in tickets:
            props = ticket.properties or {}
            keywords = _SEARCH_SYNONYMS.get(props.get("ticket_type") or "", "")
            if keywords and not props.get("search_keywords"):
                ticket.properties = {**props, "search_keywords": keywords}
                stats["билет: синонимы по типу"] = stats.get("билет: синонимы по типу", 0) + 1

        print("\n".join(report))
        print()
        for k, v in sorted(stats.items()):
            print(f"{k}: {v}")
        print(f"заметок к изменению: {changed_items}")
        if apply:
            await db.commit()
            print("ЗАПИСАНО")
        else:
            await db.rollback()
            print("только отчёт — для записи запусти с --apply")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    asyncio.run(run(parser.parse_args().apply))
