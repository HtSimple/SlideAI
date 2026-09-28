from dataclasses import dataclass

from slideai.domain.changes.models import ChangeIntent, ChangeRisk, ChatTarget
from slideai.domain.content.models import SlideContent
from slideai.domain.requirements.models import Outline


@dataclass(frozen=True)
class ChangeScope:
    target_ids: list[str]
    slide_ids: set[str]
    impact_scope: list[str]
    risk_level: ChangeRisk
    needs_clarification: bool
    clarification_question: str | None = None
    needs_confirmation: bool = False


def resolve_change_scope(
    intent: ChangeIntent,
    target: ChatTarget | None,
    outline: Outline | None,
    slides: list[SlideContent],
) -> ChangeScope:
    target_type = target.target_type if target is not None else intent.target_type
    target_ids = (
        [target.target_id]
        if target is not None and target.target_id is not None
        else list(intent.target_ids)
    )
    clarify = intent.needs_clarification
    question = intent.clarification_question
    outline_item_ids = {
        item.id
        for section in (outline.sections if outline is not None else [])
        for item in section.items
    }
    section_ids = {section.id for section in (outline.sections if outline is not None else [])}
    slide_ids = {str(slide.id) for slide in slides}

    valid_ids: set[str] = set()
    if target_type == "whole_deck":
        resolved_ids: list[str] = []
        affected = list(slides)
    elif target_type == "outline_item":
        valid_ids = outline_item_ids
        resolved_ids = target_ids
        affected = [slide for slide in slides if slide.outline_item_id in resolved_ids]
    elif target_type == "section":
        valid_ids = section_ids
        resolved_ids = target_ids
        affected = [slide for slide in slides if slide.section_id in resolved_ids]
    else:
        valid_ids = slide_ids
        resolved_ids = target_ids
        affected = [slide for slide in slides if str(slide.id) in resolved_ids]

    if target_type != "whole_deck" and not resolved_ids:
        clarify = True
        question = question or "你希望修改哪一章、条目或页面？"
    elif target_type != "whole_deck" and not set(resolved_ids).issubset(valid_ids):
        clarify = True
        question = "我没有找到对应对象。请从当前大纲或页面中指定一个目标。"

    if target_type == "outline_item" and not intent.replacement_text:
        clarify = True
        question = question or "请提供希望替换成的条目标题或内容。"

    selected_sections = {slide.section_id for slide in affected}
    denominator = len(slides)
    wide_ratio = bool(denominator and len(affected) / denominator > 0.30)
    structural = intent.operation in {"reorder", "regenerate"} or intent.risk_level in {
        "wide",
        "constraint_change",
    }
    outline_with_content = target_type == "outline_item" and bool(affected)
    needs_confirmation = not clarify and (
        target_type == "whole_deck"
        or wide_ratio
        or len(selected_sections) > 1
        or structural
        or outline_with_content
    )
    risk_level = "constraint_change" if structural else "wide" if needs_confirmation else "local"
    impact = [str(slide.id) for slide in affected]
    if target_type == "outline_item" and not impact:
        impact = list(resolved_ids)
    return ChangeScope(
        target_ids=resolved_ids,
        slide_ids={str(slide.id) for slide in affected},
        impact_scope=impact,
        risk_level=risk_level,
        needs_clarification=clarify,
        clarification_question=question,
        needs_confirmation=needs_confirmation,
    )
