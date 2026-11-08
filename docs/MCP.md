# Локальные инструменты в редакторе

Сначала создай проект командой `python -m strategy_agent init`. MCP предоставляет тот же
Toolbox для чтения материалов, регистрации источников, расчётов и черновика. Агентную
роль и финальное решение обеспечивает LLM редактора по `AGENTS.md`; нативные инструменты
runtime `submit_strategy` и `consult_specialist` принадлежат CLI, а не серверу Toolbox.

Пример настройки MCP-клиента (замени оба абсолютных пути):

```json
{
  "mcpServers": {
    "product-research": {
      "command": "python",
      "args": [
        "C:/path/product-strategy-agent/scripts/mcp_server.py",
        "--project", "C:/path/product-strategy-agent/workspace/my-product"
      ]
    }
  }
}
```

Обёртка добавляет корень репозитория в импорт; рабочий каталог редактора не влияет на
запуск. Стандартный транспорт — UTF-8 JSON-RPC/stdio, версия 2025-03-26. Вывод stdout
содержит только сообщения протокола. Сервер объявляет список инструментов через tools/list.
Он не требует OpenRouter-ключа: модель предоставляет сам клиент.

Разрешённые сайты указываются человеком в `<проект>/sources-policy.json`:

```json
{"allowed_domains": ["www.cbr.ru", "support.mts.ru", "t2.ru"]}
```

Сопоставление домена точное. Поддомены добавляются отдельно. Материал не может изменить
эту политику. Ошибки инструмента возвращаются клиенту; сервер не имитирует успешную загрузку.
Документация транспорта: [MCP](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports).
