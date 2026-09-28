from slideai.domain.content.models import SlideContent
from slideai.domain.requirements.models import Outline


def render_markdown(outline: Outline, slides: list[SlideContent]) -> str:
    """Render the accepted structured pages into a stable, UTF-8 Markdown source."""
    pages_by_section: dict[str, list[SlideContent]] = {
        section.id: [] for section in outline.sections
    }
    for slide in sorted(slides, key=lambda item: item.page_number):
        if slide.section_id in pages_by_section:
            pages_by_section[slide.section_id].append(slide)

    lines = [f"# {_text(outline.title)}", ""]
    for section in outline.sections:
        section_slides = pages_by_section[section.id]
        if not section_slides:
            continue
        lines.extend((f"## {_text(section.title)}", ""))
        for slide in section_slides:
            lines.extend(
                (
                    f"### 第 {slide.page_number} 页：{_text(slide.title)}",
                    "",
                    *(f"- {_text(bullet)}" for bullet in slide.bullets),
                    "",
                )
            )
            if slide.speaker_notes:
                lines.extend(("**演讲备注**", "", _text(slide.speaker_notes), ""))
            if slide.citations:
                lines.extend(("**资料来源**", ""))
                seen: set[tuple[str, int | None, str | None]] = set()
                for citation in slide.citations:
                    source_key = (
                        citation.display_name,
                        citation.page_number,
                        citation.section_title,
                    )
                    if source_key in seen:
                        continue
                    seen.add(source_key)
                    location = (
                        f"第 {citation.page_number} 页"
                        if citation.page_number is not None
                        else citation.section_title or "未标记位置"
                    )
                    lines.append(
                        f"- [来源：{_text(citation.display_name)}，{_text(location)}] "
                        f"{_text(citation.excerpt)}"
                    )
                lines.append("")
            if slide.verification_notes:
                lines.extend(("**待核实**", ""))
                lines.extend(f"- {_text(note)}" for note in slide.verification_notes)
                lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _text(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
