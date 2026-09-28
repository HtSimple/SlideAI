import json
from collections.abc import Sequence
from typing import Any, cast

from pydantic import BaseModel

from slideai.core.errors import ModelPermanentError
from slideai.domain.changes.models import ChangeIntent
from slideai.domain.content.models import SlideBatch
from slideai.domain.evaluation.models import EvaluationDraft, SlideRefinementDraft
from slideai.domain.models.catalog import ModelDefinition
from slideai.domain.requirements.models import Outline, StructuredRequirement

ModelMessage = dict[str, str]


class DeterministicDemoProvider:
    """Build local, repeatable content when fake generation is explicitly configured."""

    def __init__(self, *, evaluation_score: int = 90) -> None:
        self.evaluation_score = evaluation_score

    async def invoke_structured(
        self,
        *,
        model: ModelDefinition,
        messages: Sequence[ModelMessage],
        output_schema: type[BaseModel],
        idempotency_key: str,
    ) -> BaseModel:
        del model, idempotency_key
        payload = _latest_json_message(messages)
        if output_schema is EvaluationDraft:
            names = [
                "completeness",
                "logic",
                "content_quality",
                "requirement_alignment",
            ]
            score = self.evaluation_score
            slides = payload.get("slides", [])
            issues = []
            if score < 85:
                scope = [slides[0]["id"]] if slides else []
                issues = [
                    {
                        "code": "DEMO_QUALITY_IMPROVEMENT",
                        "severity": "medium",
                        "scope": scope,
                        "description": "演示评估建议进一步明确页面结论与支撑要点。",
                        "suggestion": "精炼标题并让要点直接回应页面目标。",
                    }
                ]
            return EvaluationDraft.model_validate(
                {
                    "dimensions": [
                        {"name": name, "score": score, "feedback": "本地确定性演示评分。"}
                        for name in names
                    ],
                    "issues": issues,
                    "suggestions": ["检查结论与页面目标是否一致。"],
                }
            )
        if output_schema is ChangeIntent:
            user_message = str(payload.get("user_message", ""))
            selected_value = payload.get("selected_target")
            selected: dict[str, Any] | None = None
            if isinstance(selected_value, dict):
                selected = cast(dict[str, Any], selected_value)
            outline = cast(dict[str, Any], payload.get("outline") or {})
            slides = cast(list[dict[str, Any]], payload.get("slides") or [])
            target_type = "slide"
            target_ids: list[str] = []
            if selected is not None and selected.get("target_type"):
                target_type = str(selected["target_type"])
                if selected.get("target_id"):
                    target_ids = [str(selected["target_id"])]
            elif any(token in user_message for token in ("整份", "全部页面", "全部内容")):
                target_type = "whole_deck"
            else:
                digits = {
                    "一": 1,
                    "二": 2,
                    "三": 3,
                    "四": 4,
                    "五": 5,
                    "六": 6,
                    "七": 7,
                    "八": 8,
                    "九": 9,
                    "十": 10,
                }
                sections = cast(list[dict[str, Any]], outline.get("sections", []))
                flattened: list[dict[str, Any]] = [
                    item
                    for section in sections
                    for item in cast(list[dict[str, Any]], section.get("items", []))
                ]
                point_number = next(
                    (
                        number
                        for label, number in digits.items()
                        if f"第{label}点" in user_message or f"第 {label} 点" in user_message
                    ),
                    None,
                )
                page_number = next(
                    (
                        number
                        for label, number in digits.items()
                        if f"第{label}页" in user_message or f"第 {label} 页" in user_message
                    ),
                    None,
                )
                if point_number and point_number <= len(flattened):
                    target_type = "outline_item"
                    target_ids = [str(flattened[point_number - 1]["id"])]
                elif page_number:
                    selected_slide = next(
                        (slide for slide in slides if slide.get("page_number") == page_number),
                        None,
                    )
                    if selected_slide:
                        target_type = "slide"
                        target_ids = [str(selected_slide["id"])]
            replacement = None
            for marker in ("改成", "改为", "替换为", "调整为", "改成：", "改为："):
                if marker in user_message:
                    replacement = user_message.split(marker, 1)[1].strip(" ：:，,。")
                    if replacement:
                        break
            needs_clarification = target_type != "whole_deck" and not target_ids
            if target_type == "outline_item" and not replacement:
                needs_clarification = True
            return ChangeIntent.model_validate(
                {
                    "target_type": target_type,
                    "target_ids": target_ids,
                    "operation": "replace" if replacement else "rewrite",
                    "instruction": user_message,
                    "replacement_text": replacement,
                    "risk_level": "local",
                    "needs_clarification": needs_clarification,
                    "clarification_question": (
                        "你希望修改哪一章、条目或页面？"
                        if needs_clarification and not target_ids
                        else "请提供希望替换成的条目标题或内容。"
                        if needs_clarification
                        else None
                    ),
                }
            )
        if output_schema is SlideRefinementDraft:
            feedback = str(payload.get("feedback", "")).strip().splitlines()[0][:80]

            def refine_demo_slide(slide: dict[str, Any]) -> dict[str, Any]:
                title = slide["title"]
                if not title.startswith("已优化："):
                    title = f"已优化：{title}"
                bullets = list(slide["bullets"])
                if feedback:
                    bullets[-1] = f"结合反馈“{feedback}”：{bullets[-1]}"
                return {
                    "id": slide["id"],
                    "title": title[:200],
                    "bullets": bullets,
                    "speaker_notes": slide.get("speaker_notes"),
                    "verification_notes": slide.get("verification_notes", []),
                }

            return SlideRefinementDraft.model_validate(
                {"slides": [refine_demo_slide(slide) for slide in payload.get("slides", [])]}
            )
        if output_schema is StructuredRequirement:
            raw = payload
            return StructuredRequirement.model_validate(
                {
                    "topic": raw.get("topic"),
                    "target_page_count": raw.get("target_page_count"),
                    "scenario": raw.get("scenario"),
                    "audience": raw.get("audience"),
                    "style": raw.get("style"),
                    "constraints": raw.get("special_constraints", []),
                    "language": "zh-CN",
                    "source_usage": "preferred",
                    "original_text": raw.get("original_text"),
                    "domain_expertise": "general",
                    "analysis_depth": "overview",
                }
            )
        if output_schema is Outline:
            requirement = StructuredRequirement.model_validate(payload)
            topic = requirement.topic or "内容概览"
            page_count = requirement.target_page_count
            if page_count is None:
                raise ModelPermanentError("A target page count is required for the demo provider.")
            item = {
                "id": "main-content",
                "title": f"{topic}分析",
                "objective": f"围绕{topic}梳理关键背景、现状与行动方向",
                "page_count": page_count,
            }
            return Outline.model_validate(
                {
                    "title": topic,
                    "sections": [
                        {
                            "id": "main-section",
                            "title": f"{topic}概览",
                            "objective": f"帮助{requirement.audience or '目标受众'}理解{topic}",
                            "page_count": page_count,
                            "items": [item],
                        }
                    ],
                }
            )
        if output_schema is SlideBatch:
            requirement = StructuredRequirement.model_validate(payload.get("requirement", {}))
            evidence_by_page = payload.get("untrusted_source_evidence", {})
            slides: list[dict[str, Any]] = []
            for plan in payload.get("page_plans", []):
                page_number = plan["page_number"]
                evidence = evidence_by_page.get(str(page_number), [])
                citations = [{"chunk_id": source["chunk_id"]} for source in evidence[:1]]
                bullets = [
                    f"围绕{requirement.topic or '主题'}梳理{plan['title']}的关键背景与现状。",
                    f"本页聚焦{plan['objective']}，服务于{requirement.audience or '目标受众'}。",
                ]
                verification_notes: list[str] = []
                if evidence:
                    excerpt = str(evidence[0].get("content", "")).strip()
                    if excerpt:
                        bullets.append(f"资料依据：{excerpt[:180]}")
                else:
                    verification_notes.append("需要补充资料核实具体数据。")
                slides.append(
                    {
                        "page_number": page_number,
                        "title": plan["title"],
                        "bullets": bullets,
                        "speaker_notes": (
                            f"围绕“{plan['objective']}”展开说明，保持与相邻页面的逻辑衔接。"
                        ),
                        "citations": citations,
                        "verification_notes": verification_notes,
                    }
                )
            return SlideBatch.model_validate({"slides": slides})
        raise ModelPermanentError(
            f"The local demo provider does not support {output_schema.__name__}."
        )


def _latest_json_message(messages: Sequence[ModelMessage]) -> dict[str, Any]:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        try:
            payload = json.loads(message.get("content", ""))
        except json.JSONDecodeError as error:
            raise ModelPermanentError(
                "The local demo provider received invalid JSON input."
            ) from error
        if isinstance(payload, dict):
            return cast(dict[str, Any], payload)
    raise ModelPermanentError("The local demo provider received no structured input.")
