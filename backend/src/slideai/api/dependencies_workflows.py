from fastapi import Request

from slideai.application.outlines.service import OutlineService
from slideai.application.requirements.service import RequirementService
from slideai.application.workflows.service import WorkflowControlService


def get_workflow_control_service(request: Request) -> WorkflowControlService:
    return request.app.state.workflow_control_service


def get_requirement_service(request: Request) -> RequirementService:
    return request.app.state.requirement_service


def get_outline_service(request: Request) -> OutlineService:
    return request.app.state.outline_service
