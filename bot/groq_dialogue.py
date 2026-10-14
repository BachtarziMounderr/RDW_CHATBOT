"""Rédaction Groq facultative avec le même contrôle documentaire que Gemini."""
from __future__ import annotations

from .gemini_dialogue import GeminiDialogue, GeminiLimits, SYSTEM_INSTRUCTION, UsageLimit


# Modèles explicitement autorisés pour ce test. La présence ici évite qu'une faute
# de configuration sélectionne silencieusement un autre modèle.
FREE_GROQ_MODELS = {"qwen/qwen3.8-27b"}


class GroqSDKTransport:
    """Transport utilisant le SDK Python officiel maintenu par Groq."""

    def __init__(self, key: str, model: str, limits: GeminiLimits):
        if not key:
            raise ValueError("GROQ_API_KEY absente ; le mode IA reste désactivé.")
        if model not in FREE_GROQ_MODELS:
            raise ValueError("GROQ_MODEL n'est pas dans la liste locale des modèles Groq gratuits autorisés.")
        from groq import Groq

        self.model = model
        self.limits = limits
        self.client = Groq(api_key=key, timeout=limits.timeout_seconds, max_retries=0)

    def generate(self, prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=self.limits.max_output_tokens,
            temperature=0.2,
        )
        return response.choices[0].message.content or ""


class GroqDialogue(GeminiDialogue):
    """Composeur RDW fondé sur Groq, avec question filtrée et passages publics."""

    provider_label = "Groq"
    provider_slug = "groq"

    def __init__(self, key: str, model: str, limits: GeminiLimits, usage: UsageLimit,
                 transport=None, **kwargs):
        selected = transport or GroqSDKTransport(key, model, limits)
        super().__init__(key, model, limits, usage, transport=selected, **kwargs)
