"""Small OpenRouter adapter. Keys and raw HTTP error bodies never enter the ledger."""
from __future__ import annotations

import json
import http.client
import math
import os
import socket
import urllib.error
import urllib.request
from pathlib import Path


class ProviderError(RuntimeError):
    def __init__(self, message, *, code="provider_error", uncertain=False):
        super().__init__(message)
        self.code = code
        self.uncertain = uncertain


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        # The provider endpoint is fixed. Never forward its bearer token through
        # an unexpected redirect, even if a future proxy/server misconfigures it.
        return None


def load_env(path: Path):
    """Load simple KEY=value entries, without shell expansion or overwriting env."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if name.replace("_", "").isalnum() and not name[0].isdigit():
            if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(name, value)


def number(value):
    """Reject bool, NaN, infinity and negative accounting fields."""
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


class OpenRouter:
    base_url = "https://openrouter.ai/api/v1"

    def __init__(self, api_key=None, timeout=90, opener=None):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self.timeout = timeout
        self.opener = opener or urllib.request.build_opener(_NoRedirect()).open
        self._models = None

    def _http(self, path, payload=None):
        if not self.api_key and payload is not None:
            raise ProviderError("Не задан OPENROUTER_API_KEY. Добавьте ключ в локальный .env.", code="missing_key")
        headers = {"Content-Type": "application/json", "X-Title": "Product Strategy Agent"}
        if payload is not None:
            headers["Authorization"] = "Bearer " + self.api_key
        request = urllib.request.Request(
            self.base_url + path,
            data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="GET" if payload is None else "POST",
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read(8_000_001)
            if len(raw) > 8_000_000:
                raise ProviderError("Ответ провайдера превышает допустимый размер.", code="oversized_response", uncertain=payload is not None)
            body = json.loads(raw)
        except urllib.error.HTTPError as exc:
            # Do not log provider response bodies: they can echo credentials or input.
            uncertain = payload is not None and (exc.code >= 500 or exc.code in (408, 499))
            raise ProviderError(f"OpenRouter вернул HTTP {exc.code}; автоматический повтор не выполнен.", code=f"http_{exc.code}", uncertain=uncertain) from None
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError, http.client.HTTPException):
            raise ProviderError("Сетевая ошибка; запрос мог быть оплачен. Повтор требует проверки Activity OpenRouter.", code="network_error", uncertain=payload is not None) from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ProviderError("OpenRouter вернул нечитаемый ответ; расход требует сверки.", code="invalid_json", uncertain=payload is not None) from None
        if not isinstance(body, dict):
            raise ProviderError("OpenRouter вернул неожиданный формат ответа.", code="invalid_response", uncertain=payload is not None)
        if body.get("error"):
            raise ProviderError("OpenRouter сообщил ошибку в ответе; проверьте Activity.", code="response_error", uncertain=payload is not None)
        return body

    def models(self):
        if self._models is None:
            items = self._http("/models").get("data", [])
            if not isinstance(items, list):
                raise ProviderError("Неожиданный формат каталога моделей.", code="invalid_catalog")
            self._models = {item["id"]: item for item in items if isinstance(item, dict) and isinstance(item.get("id"), str)}
        return self._models

    def reserve_cost(self, model, messages, tools, max_tokens):
        """Conservative text request reservation; authoritative final cost is usage.cost.

        Byte count upper-bounds ordinary text tokenization; an overhead allowance
        covers chat formatting. Model prices are fetched afresh per process.
        Multimodal inputs are intentionally rejected here: their billing is different.
        """
        info = self.models().get(model)
        if not info:
            raise ProviderError(f"Модель {model} отсутствует в каталоге OpenRouter.", code="unknown_model")
        if tools and "tools" not in info.get("supported_parameters", []):
            raise ProviderError(f"Модель {model} не заявляет поддержку tools.", code="unsupported_tools")
        pricing = info.get("pricing", {})
        prompt_price, completion_price = number(pricing.get("prompt")), number(pricing.get("completion"))
        request_price = number(pricing.get("request", 0))
        if None in (prompt_price, completion_price, request_price):
            raise ProviderError("Нет достоверной цены модели; запрос остановлен до настройки бюджета.", code="unknown_price")
        if any(not isinstance(m.get("content", ""), (str, type(None))) for m in messages):
            raise ProviderError("Этот CLI принимает текст; изображения передайте средствами IDE по инструкции.", code="unsupported_media")
        input_bound = len(json.dumps({"messages": messages, "tools": tools}, ensure_ascii=False).encode("utf-8")) + 2048
        # Long-context tiers may cost more than the advertised base price.
        for tier in pricing.get("overrides", []):
            if isinstance(tier, dict) and number(tier.get("min_prompt_tokens")) is not None and input_bound >= float(tier["min_prompt_tokens"]):
                tier_prompt, tier_completion = number(tier.get("prompt")), number(tier.get("completion"))
                if tier_prompt is None or tier_completion is None:
                    raise ProviderError("Неизвестна цена длинного контекста.", code="unknown_price")
                prompt_price = max(prompt_price, tier_prompt)
                completion_price = max(completion_price, tier_completion)
        context = info.get("context_length")
        if isinstance(context, int) and input_bound + max_tokens > context:
            raise ProviderError("Контекст достиг консервативного лимита модели. Сократите материалы или выберите модель с большим окном.", code="context_limit")
        return input_bound * prompt_price + max_tokens * completion_price + request_price

    def complete(self, model, messages, tools, max_tokens=5000):
        # reserve_cost normally fills this cache. Direct callers still validate
        # model capabilities using the public catalog before sending a paid POST.
        info = self.models().get(model)
        if not info:
            raise ProviderError(f"Модель {model} отсутствует в каталоге OpenRouter.", code="unknown_model")
        supported = info.get("supported_parameters", [])
        if "max_completion_tokens" in supported:
            token_parameter = "max_completion_tokens"
        elif "max_tokens" in supported:
            token_parameter = "max_tokens"
        else:
            raise ProviderError("Модель не заявляет поддержку ограничения длины ответа; платный запрос остановлен.", code="unsupported_output_limit")
        payload = {"model": model, "messages": messages, token_parameter: max_tokens,
                   "usage": {"include": True}, "provider": {"require_parameters": True}}
        if "temperature" in supported:
            payload["temperature"] = 0.2
        if tools:
            if "tools" not in supported:
                raise ProviderError(f"Модель {model} не заявляет поддержку tools.", code="unsupported_tools")
            payload["tools"] = tools
            if "tool_choice" in supported:
                payload["tool_choice"] = "auto"
        return self._http("/chat/completions", payload)
