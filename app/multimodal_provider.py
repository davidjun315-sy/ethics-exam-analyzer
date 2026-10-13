"""Validated provider contract shared by mock and future external vision adapters."""
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol
from pydantic import Field, model_validator
from .schemas import Input, Text


class Source(Input):
    page_number: int = Field(gt=0)
    bbox: list[Annotated[float, Field(ge=0, le=1)]] = Field(min_length=4, max_length=4)

    @model_validator(mode='after')
    def valid_bbox(self):
        x0, y0, x1, y1 = self.bbox
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            raise ValueError('bbox must be a non-empty normalized rectangle')
        return self


class VisualElement(Source):
    type: Literal['image', 'table']


class Choice(Input):
    label: Text
    text: str


class MultimodalQuestion(Input):
    question_number: int = Field(gt=0, le=999)
    question_text: Text
    passage: str | None = None
    choices: list[Choice] = Field(default_factory=list)
    answer_area: str | None = None
    sources: list[Source] = Field(min_length=1)
    visual_elements: list[VisualElement] = Field(default_factory=list)
    uncertain_fields: list[Literal['question_number', 'question_text', 'passage', 'choices', 'answer_area', 'sources', 'visual_elements']] = Field(default_factory=list)
    continues_to_next_page: bool = False


class ExtractionOutput(Input):
    questions: list[MultimodalQuestion] = Field(min_length=1, max_length=500)


@dataclass(frozen=True)
class PageInput:
    page_number: int
    image_png: bytes
    auxiliary_text: str
    width_px: int
    height_px: int


class MultimodalExtractionProvider(Protocol):
    name: str
    model: str
    def extract(self, pages: list[PageInput]) -> ExtractionOutput: ...


class MockMultimodalExtractionProvider:
    name = 'mock'
    model = 'mock-page-placeholder-v1'

    def extract(self, pages):
        # No OCR, vision interpretation, regex boundaries, or fabricated answers.
        # One full-page placeholder per input exercises the image-first contract.
        questions = []
        for page in pages:
            if not page.image_png.startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('Provider requires rendered PNG images')
            questions.append(MultimodalQuestion(
                question_number=page.page_number,
                question_text=page.auxiliary_text.strip() or '[Mock] 스캔 페이지입니다. 원본 이미지를 보고 문항 내용을 직접 입력하세요.',
                sources=[Source(page_number=page.page_number, bbox=[0, 0, 1, 1])],
                uncertain_fields=['question_number', 'question_text', 'passage', 'choices', 'sources'],
            ))
        return ExtractionOutput(questions=questions)


def get_provider() -> MultimodalExtractionProvider:
    import os
    if os.getenv('MULTIMODAL_PROVIDER', 'mock') != 'mock':
        raise ValueError('External LLM provider is not connected; select mock')
    return MockMultimodalExtractionProvider()
