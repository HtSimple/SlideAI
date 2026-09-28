from fastapi import Request

from slideai.application.content.service import SlideContentService


def get_slide_content_service(request: Request) -> SlideContentService:
    return request.app.state.slide_content_service
