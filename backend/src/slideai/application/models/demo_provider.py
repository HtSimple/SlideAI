import json
from collections.abc import Sequence
from typing import Any, cast

from pydantic import BaseModel

from slideai.core.errors import ModelPermanentError
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
