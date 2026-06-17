from __future__ import annotations

from doccontext.llm.base import LLMClient, LLMResponse, Message, Usage
from doccontext.llm.factory import UnknownLLMProvider, get_llm_client
from doccontext.llm.prompts import (
    ANSWER_FULL_DOC_SYSTEM_INSTRUCTION,
    ANSWER_SECTION_SYSTEM_INSTRUCTION,
    ROUTER_SYSTEM_INSTRUCTION,
    build_full_doc_answer_messages,
    build_router_messages,
    build_section_answer_messages,
)

__all__ = [
    "ANSWER_FULL_DOC_SYSTEM_INSTRUCTION",
    "ANSWER_SECTION_SYSTEM_INSTRUCTION",
    "LLMClient",
    "LLMResponse",
    "Message",
    "ROUTER_SYSTEM_INSTRUCTION",
    "UnknownLLMProvider",
    "Usage",
    "build_full_doc_answer_messages",
    "build_router_messages",
    "build_section_answer_messages",
    "get_llm_client",
]
