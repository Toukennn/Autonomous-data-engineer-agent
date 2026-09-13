from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

from config.settings import get_llm_settings
from utils.exceptions import LLMConfigurationError


def pick_llm(level: str):
    """
    Return the configured LLM for the requested capability level.
    """

    settings = get_llm_settings()

    level = level.lower().strip()

    if level in {
        "low",
        "medium",
        "high",
    }:

        if settings.openai_api_key is None:
            raise LLMConfigurationError(
                "OPENAI_API_KEY is not configured."
            )

        model_by_level = {
            "low": settings.low_model,
            "medium": settings.medium_model,
            "high": settings.high_model,
        }

        return ChatOpenAI(
            model=model_by_level[level],
            temperature=0,
            api_key=(
                settings.openai_api_key
                .get_secret_value()
            ),
        )

    if level == "claude":

        if settings.anthropic_api_key is None:
            raise LLMConfigurationError(
                "ANTHROPIC_API_KEY is not configured."
            )

        return ChatAnthropic(
            model=settings.anthropic_model,
            api_key=(
                settings.anthropic_api_key
                .get_secret_value()
            ),
        )

    raise ValueError(
        "Invalid LLM level. Expected one of: "
        "low, medium, high, claude."
    )