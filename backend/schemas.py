from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class RequestModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class GenerateRequest(RequestModel):
    control_object: str = Field(min_length=1, max_length=4000)
    input_devices: str = Field(min_length=1, max_length=6000)
    output_devices: str = Field(min_length=1, max_length=6000)
    control_requirements: str = Field(min_length=1, max_length=10000)
    model_provider: str = Field(default="DeepSeek", min_length=1, max_length=50)


class IOPoint(BaseModel):
    address: str
    signal_name: str
    signal_type: str
    device: str
    description: str


class GenerateResponse(BaseModel):
    requirement_analysis: str
    io_table: list[IOPoint] = Field(min_length=1)
    control_logic: str
    safety_design: str
    ladder_idea: str
    report_markdown: str
    safety_notice: str


class OptimizeRequest(RequestModel):
    original_report: str = Field(min_length=1, max_length=50000)
    optimize_requirement: str = Field(min_length=1, max_length=10000)
    model_provider: str = Field(default="DeepSeek", min_length=1, max_length=50)


class OptimizeResponse(BaseModel):
    optimized_report: str
    change_summary: str
    safety_notice: str


class ErrorResponse(BaseModel):
    message: str
    detail: Optional[str] = None
