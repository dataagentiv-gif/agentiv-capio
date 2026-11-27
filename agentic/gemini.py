"""Native tool calls, with CAPIO key/model routing and per-request accounting."""
import asyncio
from contextlib import AsyncExitStack

from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.providers.google import GoogleProvider
from google.genai.types import HttpRetryOptions

import keypool
from llm import rute, telemetry
from llm._engine import LLMError, _kuota_habis
from utils.logging import get

log = get(__name__)


class GeminiPool(WrapperModel):
    def __init__(self, model_name, deadline):
        self.keys = keypool.keys("gemini")
        if not self.keys:
            raise LLMError("API key Gemini belum diisi.")
        self.deadline = deadline
        self.name = model_name
        self.attempts = 0
        self.input_tokens = self.output_tokens = 0
        self.failed_pairs = set()
        # Keep the session's selected model first, then use CAPIO's configured
        # tiers if that model is unavailable. The session's preference stays fixed.
        self.models = list(dict.fromkeys([model_name, *rute.daftar()]))
        self.clients = {
            (model, index): GoogleModel(model, provider=GoogleProvider(
                api_key=key, retry_options=HttpRetryOptions(attempts=1)))
            for model in self.models
            for index, key in enumerate(self.keys)
        }
        super().__init__(self.clients[(model_name, 0)])

    async def __aenter__(self):
        self._resources = AsyncExitStack()
        for client in self.clients.values():
            await self._resources.enter_async_context(client)
        return self

    async def __aexit__(self, *args):
        return await self._resources.__aexit__(*args)

    async def request(self, messages, model_settings, model_request_parameters):
        order = rute.urutan("gemini", self.models, len(self.keys))
        order = ([pair for pair in order if pair not in self.failed_pairs]
                 + [pair for pair in order if pair in self.failed_pairs])
        last_code = None
        for attempt, (model, index) in enumerate(order):
            self.deadline.check("agent model")
            from pydantic_ai.exceptions import UsageLimitExceeded
            if self.attempts >= 8:
                raise UsageLimitExceeded("Batas 8 permintaan Gemini tercapai, termasuk rotasi key.")
            self.attempts += 1
            if model != self.name:
                log.info("Agent berpindah ke model cadangan %s", model)
            try:
                response = await asyncio.wait_for(self.clients[(model, index)].request(
                    messages, model_settings, model_request_parameters),
                    timeout=self.deadline.remaining(180))
            except Exception as exc:
                code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
                last_code = code
                telemetry.record(model, 0, 0, 0, False, False)
                keypool.lapor("gemini", index, False, f"Agent HTTP {code or type(exc).__name__}")
                if code in (401, 403, 429, 500, 502, 503, 504):
                    self.failed_pairs.add((model, index))
                if _kuota_habis(code, str(exc)):
                    rute.tandai_habis("gemini", model, index)
                if code not in (401, 403, 429, 500, 502, 503, 504):
                    raise
                if attempt + 1 < len(order) and code in (429, 500, 502, 503, 504):
                    await asyncio.sleep(min(3, self.deadline.remaining(3)))
                continue
            u = response.usage
            self.input_tokens += u.input_tokens
            self.output_tokens += u.output_tokens
            telemetry.record(model, u.input_tokens, u.output_tokens,
                             u.input_tokens + u.output_tokens)
            keypool.lapor("gemini", index, True, "OK")
            self.deadline.check("agent model")
            return response
        raise LLMError(f"Gemini belum tersedia pada model-model di route Agent (HTTP {last_code}). Coba ulang setelah layanan/kuota pulih.")
