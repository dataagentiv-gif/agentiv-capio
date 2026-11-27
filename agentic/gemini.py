"""Native tool calls, with CAPIO key/model routing and per-request accounting."""
import asyncio
import dataclasses
from contextlib import AsyncExitStack

import httpx

from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.providers.google import GoogleProvider
from google.genai.types import HttpRetryOptions

import keypool
from llm import rute, telemetry
from llm._engine import LLMError, _kuota_habis
from utils.logging import get

log = get(__name__)


#: HTTP codes that mean "try another key/model", not "this request is wrong".
TRANSIENT = (429, 500, 502, 503, 504)


class GeminiPool(WrapperModel):
    """`limit` counts only answered requests: a 503 or a hung connection is Google's
    hiccup, not the agent's thinking budget. Failures have their own ceiling."""

    def __init__(self, model_name, deadline, limit=12, timeout=90, max_failures=10):
        self.keys = keypool.keys("gemini")
        if not self.keys:
            raise LLMError("API key Gemini belum diisi.")
        self.deadline = deadline
        self.name = model_name
        self.limit, self.timeout, self.max_failures = limit, timeout, max_failures
        self.attempts = 0   # every try, for accounting
        self.requests = 0   # answered tries, for the budget
        self.failures = 0
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
        from pydantic_ai.exceptions import UsageLimitExceeded
        if self.limit and self.requests >= self.limit:
            raise UsageLimitExceeded(f"Batas {self.limit} permintaan Gemini tercapai.")
        if self.limit and self.requests >= self.limit - 2 and model_request_parameters is not None \
                and model_request_parameters.function_tools:
            # Last two answers: no more research tools, so the agent must hand in
            # what it already verified instead of running out mid-search.
            model_request_parameters = dataclasses.replace(model_request_parameters, function_tools=[])
        order = rute.urutan("gemini", self.models, len(self.keys))
        order = ([pair for pair in order if pair not in self.failed_pairs]
                 + [pair for pair in order if pair in self.failed_pairs])
        last_code = None
        for attempt, (model, index) in enumerate(order):
            self.deadline.check("agent model")
            if self.failures >= self.max_failures:
                break
            self.attempts += 1
            if model != self.name:
                log.info("Agent berpindah ke model cadangan %s", model)
            try:
                response = await asyncio.wait_for(self.clients[(model, index)].request(
                    messages, model_settings, model_request_parameters),
                    timeout=self.deadline.remaining(self.timeout))
            except Exception as exc:
                code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
                hung = isinstance(exc, (TimeoutError, asyncio.TimeoutError, httpx.TransportError))
                last_code = code or ("timeout" if hung else None)
                telemetry.record(model, 0, 0, 0, False, False)
                keypool.lapor("gemini", index, False, f"Agent HTTP {code or type(exc).__name__}")
                if code in (401, 403, *TRANSIENT) or hung:
                    self.failed_pairs.add((model, index))
                if _kuota_habis(code, str(exc)):
                    rute.tandai_habis("gemini", model, index)
                if code not in (401, 403, *TRANSIENT) and not hung:
                    raise
                self.failures += 1
                if attempt + 1 < len(order) and (code in TRANSIENT or hung):
                    await asyncio.sleep(min(3, self.deadline.remaining(3)))
                continue
            self.requests += 1
            u = response.usage
            self.input_tokens += u.input_tokens
            self.output_tokens += u.output_tokens
            telemetry.record(model, u.input_tokens, u.output_tokens,
                             u.input_tokens + u.output_tokens)
            keypool.lapor("gemini", index, True, "OK")
            self.deadline.check("agent model")
            return response
        raise LLMError(f"Server Gemini sedang sibuk atau kuota habis di semua key (terakhir: {last_code}). "
                       "Tunggu sebentar lalu klik Coba ulang; progres dan kandidat sebelumnya tetap tersimpan.")
