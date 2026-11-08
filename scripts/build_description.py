"""Render the actual local verification, research and architecture into HTML/PDF."""
from pathlib import Path
import html
import json
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]


def offline_main():
    from markdown_it import MarkdownIt
    from playwright.sync_api import sync_playwright
    out = ROOT / "submission"
    validation = json.loads((out / "validation.json").read_text(encoding="utf-8"))
    md = MarkdownIt("commonmark", {"html": False}).enable("table")
    def render_document(text, relative):
        if text.startswith("# "):
            text = text.split("\n", 1)[1]
        tokens = md.parse(text)
        def visit(items):
            for token in items:
                if token.type == "link_open":
                    target = token.attrGet("href") or ""
                    if target and not target.startswith(("https://", "http://", "#", "mailto:")):
                        resolved = (ROOT / relative).parent.joinpath(target.split("#", 1)[0]).resolve()
                        if resolved.is_relative_to(ROOT):
                            token.attrSet("href", "https://github.com/temurysega/product-strategy-agent/blob/main/" + quote(resolved.relative_to(ROOT).as_posix()))
                if token.children:
                    visit(token.children)
        visit(tokens)
        return md.renderer.render(tokens, md.options, {})
    screenshots = out / "screenshots"
    screenshots.mkdir(exist_ok=True)
    checks = {item["command"].split(" --project")[0]: item["output"] for item in validation["checks"]}
    demo_checks = [item for item in validation["checks"] if "demo.py" in item["command"]]
    panels = [
        ("checkpoint", "Пауза и продолжение", {"paused": demo_checks[0]["output"], "resumed": demo_checks[1]["output"]}),
        ("revision", "Отзыв основания и зависимый вывод", demo_checks[-1]["output"]),
        ("tests", "Результаты автоматических проверок", {"tests": validation["tests"], "checks": len(validation["checks"]), "live_openrouter_generation_tested": False, "note": "Числа получены scripts/verify.py; исходный журнал приложен."}),
    ]
    font = "'Segoe UI',Arial,sans-serif"
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="chrome", headless=True)
        except Exception:
            browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1200, "height": 1000}, device_scale_factor=1)
        for name, title, data in panels:
            body = '<html lang="ru"><meta charset="utf-8"><style>body{margin:0;padding:32px;background:#edf2f7;color:#162330;font-family:' + font + '}main{border-radius:16px;overflow:hidden;border:1px solid #2b4661;background:#101d2b;color:#d6e8f5}header{padding:18px 24px;background:#1c3249;font-size:20px}pre{padding:24px;margin:0;font:15px/1.5 Consolas,monospace;white-space:pre-wrap}footer{padding:16px;font-size:14px}</style><main><header>' + html.escape(title) + '</header><pre>' + html.escape(json.dumps(data, ensure_ascii=False, indent=2)) + '</pre></main><footer>Скриншот представления фактического вывода CLI. Офлайн-проверка; не интерфейс редактора и не live-вызов LLM.</footer></html>'
            page.set_content(body)
            page.screenshot(path=str(screenshots / f"{name}.png"), full_page=True)
        sections = []
        def section(title, content):
            sections.append('<section><h1>' + html.escape(title) + '</h1>' + content + '</section>')
        section("Продуктовый навигатор", '<p class="eyebrow">ОПИСАНИЕ РАБОТЫ · 8 НОЯБРЯ 2026</p><p class="lead">От размытого запроса — к проверяемой стратегии, решению человека и пересмотру оснований.</p><p>Переносимая папка агента для Cursor/Codex: инструкции, методика, источники, локальные инструменты, OpenRouter и MCP.</p><div class="stat"><b>' + str(validation["tests"]["passed"]) + '</b> пройденных тестов · <b>' + str(len(validation["checks"])) + '</b> проверок запуска · <b>$0</b> API в офлайн-прогоне</div><p><strong>Статус:</strong> техническая реализация и предварительное исследование готовы к проверке. Официальный бриф не предоставлен. Демонстрация заранее подготовлена; live-генерация OpenRouter не проверена без ключа. Ролик отложен по запросу владельца.</p><p>Репозиторий: product-strategy-agent. Основные команды и точные границы — в README.md. Время разработки и стоимость модели среды не выдаются за нулевые расходы.</p>')
        section("Путь решения", '<div class="flow"><div>Запрос<br><small>цель и ограничения</small></div><span>→</span><div>Исследование<br><small>источники и расчёты</small></div><span>→</span><div>Варианты<br><small>сильные возражения</small></div></div><div class="flow"><div>Новые данные<br><small>отзыв оснований</small></div><span>←</span><div>Решение человека<br><small>владелец и пересмотр</small></div><span>←</span><div>Две стратегии<br><small>единые обещания</small></div></div><p>На каждом шаге сохраняются состояние, результаты и журнал. Модель выбирает следующий инструмент; Python проверяет аргументы и исполняет ограниченное действие. Локальное воспроизведение использует заранее заданные ответы и служит проверкой механики.</p>')
        architecture = (ROOT / "docs/ARCHITECTURE.md").read_text(encoding="utf-8")
        architecture = architecture.split("```mermaid")[0] + architecture.split("```", 2)[-1] if "```mermaid" in architecture else architecture
        section("Архитектура и состав", render_document(architecture, "docs/ARCHITECTURE.md"))
        section("Модели, сервисы и стоимость", md.render('''| Компонент | Использование | Фактический статус |
|---|---|---|
| Python 3.12+, стандартная библиотека | CLI, расчёты, документы, сеть, MCP и состояние | Проверено локально |
| OpenRouter | Chat Completions с инструментами и usage.cost | Адаптер проверен имитацией API; живой ключ отсутствовал |
| google/gemini-2.5-flash | Базовый маршрут, синтетический респондент, текстовый UX-анализ | Настройка; не означает выполненный вызов |
| anthropic/claude-sonnet-4.5 | Критик и маршрут исправления ошибок | Настройка; не означает выполненный вызов |
| LLM среды Codex и веб-поиск | Подготовка кода и предварительного исследования | Использовались в работе; точные токены и стоимость средой не предоставлены |
| MCP stdio 2025-03-26 | Инструменты для редактора | Проверен handshake, список и вызовы |
| pypdf | Извлечение текстового слоя PDF | Необязательная зависимость; OCR не заявлен |
| Playwright, Chromium, markdown-it-py | Скриншоты фактических результатов и этот PDF | Только сборка документа, не runtime |

Цена API офлайн-проверки — **$0**, потому что модель не вызывалась. Время проверок указано в validation.json. Затраты на подготовку, подписку IDE и работу человека не измерены и не включены в этот ноль. Для live-проекта сохраняются токены, модель, время вызова, известная сумма и неизвестные расходы; повторные и отдельные вызовы специалистов входят в журнал.

Помощь человека: поставлена задача, подтверждено отсутствие официального брифа, ролик отложен. Коммерческое решение и интервью с пользователями не проводились. Ошибки разработки и исправления описаны ниже.'''))
        section("Подтверждение работы", ''.join('<figure><img src="screenshots/' + name + '.png"><figcaption>' + title + '. Источник — сохранённый вывод проверок, без имитации интерфейса IDE.</figcaption></figure>' for name, title, _ in panels))
        for title, path in [
            ("Демонстрационный запрос", "examples/family-safety/brief.md"),
            ("Исследование и ограничения", "examples/family-safety/outputs/research.md"),
            ("Альтернативы и возражения", "examples/family-safety/outputs/options.md"),
            ("Продуктовая стратегия", "examples/family-safety/outputs/product-strategy.md"),
            ("Коммуникационная стратегия", "examples/family-safety/outputs/communication-strategy.md"),
            ("План проверки", "examples/family-safety/outputs/experiments.md"),
            ("Новые данные и пересмотр", "examples/family-safety/outputs/changes.md"),
            ("Ключевые инструкции агента", "prompts/system.md"),
            ("Критерии, измерения и пределы", "docs/EVALUATION.md"),
        ]:
            section(title, render_document((ROOT / path).read_text(encoding="utf-8"), path))
        section("Ошибки, ограничения и воспроизведение", md.render('''При разработке обнаружены и исправлены несовпадение единиц accounts/families, отсутствие учёта возвращаемых ошибок инструмента в маршрутизации, пропуск статуса revoked при утверждении и окно сбоя после оплаченного ответа. Регрессионные тесты проверяют соответствующее поведение. Валидатор навыков запускался с `python -X utf8` из-за системной кодировки Windows. Один тест символических ссылок пропускается на Windows без права их создания; проверка junction выполняется отдельно, если доступна в итоговом журнале.

Сайты могут запрещать чтение: недоступность МегаФона отмечена в материалах, сведения не додуманы. Наличие URL в конспекте не равно повторной загрузке оригинала. Публичные источники дают контекст и описание функций, не доказывают спрос или эффект концепта. Синтетика явно помечена; реальных интервью и экспериментов — 0.

Нативное распознавание изображений/аудио/видео, полная защита LLM от смысловой манипуляции, векторный поиск и превосходство над аналитиком не заявляются. Текстовые транскрипты и описания интерфейса используются в обозначенных границах.

Воспроизведение: `python scripts/verify.py`. Пересборка PDF после установки `requirements-docs.txt`: `python scripts/build_description.py` (нужен Chrome либо `python -m playwright install chromium`). Реальные команды и весь вывод лежат в `submission/checks.txt`; машинный результат — `submission/validation.json`. Скриншоты показывают сохранённые результаты этих команд.

Для окончательной подачи нужны опубликованный официальный бриф и обязательное видео до 10 минут. Живой прогон OpenRouter следует выполнить с собственным ключом и приложить фактическую стоимость. Максимальная оценка заранее не гарантируется.'''))
        css = '''@page{size:A4;margin:16mm 16mm 18mm}*{box-sizing:border-box}body{font-family:FONT;color:#152c3e;font-size:11px;line-height:1.6;margin:0}section{page-break-before:always}section:first-child{page-break-before:auto;padding-top:28mm}h1{font-size:28px;line-height:1.15;color:#173f52;margin:0 0 22px}h2{font-size:18px;margin-top:24px}h3{font-size:14px}h1,h2,h3{break-after:avoid}p,li{orphans:3;widows:3}.eyebrow{letter-spacing:2px;font-size:10px;color:#557583}.lead{font-size:26px;line-height:1.3;margin:30px 0}.stat{padding:22px;background:#e6f3ed;border-left:4px solid #238566;margin:24px 0;font-size:16px}table{border-collapse:collapse;width:100%;font-size:10px;margin:16px 0;table-layout:auto}th,td{padding:8px;text-align:left;border:1px solid #cddde2;vertical-align:top;overflow-wrap:anywhere}th{background:#e8f1f4}tr{break-inside:avoid}pre{white-space:pre-wrap;font-size:9px;background:#eef3f5;padding:14px}code{font-family:Consolas,monospace;overflow-wrap:anywhere}a{color:#156a7e;overflow-wrap:anywhere}blockquote{border-left:3px solid #91b4c0;padding-left:16px;color:#456171}figure{margin:16px 0;break-inside:avoid}figure img{width:100%;max-height:225mm;object-fit:contain}figcaption{font-size:9px;color:#667d87}.flow{display:flex;align-items:center;gap:10px;margin:20px 0}.flow div{background:#173f52;color:white;padding:18px;width:30%;font-size:14px;border-radius:6px}.flow small{font-size:10px;color:#bfdae5}.flow span{font-size:22px}'''.replace("FONT", font)
        css += 'td:first-child,th:first-child{min-width:38px}@media screen{body{max-width:1000px;margin:0 auto;padding:36px;background:#fff}html{background:#f1f5f6}section{margin-bottom:60px}}'
        document = '<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Продуктовый навигатор — описание работы</title><style>' + css + '</style></head><body>' + ''.join(sections) + '</body></html>'
        path = out / "description.html"
        path.write_text(document, encoding="utf-8")
        page.goto(path.as_uri())
        page.emulate_media(media="print")
        page.pdf(path=str(out / "description.pdf"), format="A4", print_background=True, display_header_footer=True, header_template='<span></span>', footer_template='<div style="width:100%;font-size:8px;color:#789;text-align:center;">Продуктовый навигатор · <span class="pageNumber"></span> / <span class="totalPages"></span></div>')
        page.screenshot(path=str(screenshots / "description-preview.png"), full_page=False)
        browser.close()
    print("Saved submission/description.html and submission/description.pdf")


def read_json(path, default=None):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else default


def clip(text, limit=1500):
    """Keep quotations verbatim; explicitly mark only the omitted suffix."""
    text = str(text or "")
    return text if len(text) <= limit else text[:limit].rstrip() + "\n[…] Фрагмент; полный текст — в исходном файле."


def transcript_excerpt(text, limit=1500, lines=26):
    """A readable prefix; line-heavy Markdown must not shrink the whole screenshot."""
    text = str(text or "")
    prefix = "\n".join(text[:limit].split("\n")[:lines]).rstrip()
    return prefix if prefix == text else prefix + "\n[…] Фрагмент; полный текст — в исходном файле."


def amount(value, digits=4):
    return "неизвестно" if value is None else f"${value:.{digits}f}"


def live_main(summary):
    """Build an evidence-led report from sanitized, saved API artifacts only."""
    from collections import Counter, defaultdict
    from markdown_it import MarkdownIt
    from playwright.sync_api import sync_playwright

    out = ROOT / "submission"
    live = out / "live"
    shots = out / "screenshots"
    shots.mkdir(exist_ok=True)
    validation = read_json(out / "validation.json", {})
    ledger = read_json(live / "ledger.json", [])
    if isinstance(ledger, dict):
        ledger = ledger.get("ledger", ledger.get("entries", []))
    if not ledger:
        raise SystemExit("Live-статус указан, но ledger.json пуст или отсутствует. Нужен журнал фактических вызовов.")
    events = [json.loads(line) for line in (live / "events.jsonl").read_text(encoding="utf-8-sig").splitlines() if line.strip()] if (live / "events.jsonl").exists() else []
    specialists = [(p, read_json(p, {})) for p in sorted((live / "specialists").glob("*.json"))]
    comparison = read_json(live / "comparison.json", {})
    strategy = read_json(live / "strategy.json", {})
    editorial = read_json(live / "editorial-revision.json", {})
    reconciliation = read_json(out / "cost-reconciliation.json", {})
    messages = read_json(live / "messages.json", [])
    md = MarkdownIt("commonmark", {"html": False}).enable("table")
    esc = html.escape
    repo = "https://github.com/temurysega/product-strategy-agent/blob/main/"

    def link(path, label=None):
        return '<a href="' + repo + quote(path) + '">' + esc(label or path) + '</a>'

    def render(text, relative="docs/LIVE_EVIDENCE.md"):
        if text.startswith("# "):
            text = text.split("\n", 1)[-1]
        tokens = md.parse(text)
        def visit(items):
            for token in items:
                if token.type == "link_open":
                    target = token.attrGet("href") or ""
                    if target and not target.startswith(("https://", "http://", "#", "mailto:")):
                        resolved = (ROOT / relative).parent.joinpath(target.split("#", 1)[0]).resolve()
                        if resolved.is_relative_to(ROOT):
                            token.attrSet("href", repo + quote(resolved.relative_to(ROOT).as_posix()))
                if token.children:
                    visit(token.children)
        visit(tokens)
        return md.renderer.render(tokens, md.options, {})

    def doc(path, before=None):
        text = (ROOT / path).read_text(encoding="utf-8-sig")
        if before:
            text = text.split(before, 1)[0]
        return render(text, path)

    def table(headers, rows):
        return '<table><thead><tr>' + ''.join('<th>' + esc(str(h)) + '</th>' for h in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>' + esc(str(c)) + '</td>' for c in row) + '</tr>' for row in rows) + '</tbody></table>'

    grouped = defaultdict(lambda: {"calls": 0, "cost": 0.0, "unknown": 0, "in": 0, "out": 0})
    for entry in ledger:
        key = (entry.get("purpose", "не указана"), entry.get("model", "не указана"))
        item = grouped[key]
        item["calls"] += 1
        item["cost"] += entry.get("cost_usd") or 0
        item["unknown"] += entry.get("cost_usd") is None
        item["in"] += entry.get("prompt_tokens") or 0
        item["out"] += entry.get("completion_tokens") or 0
    known_cost = sum(e.get("cost_usd") or 0 for e in ledger)
    unknown = sum(e.get("cost_usd") is None for e in ledger)
    elapsed = summary.get("elapsed_seconds", summary.get("wall_time_seconds"))
    elapsed_display = "не измерено" if elapsed is None else f"{elapsed:.1f} с"
    first_at = summary.get("started_at") or (ledger[0].get("started_at") if ledger else None) or "не записано"
    final_at = summary.get("finished_at") or summary.get("completed_at") or "не записано"
    state = summary.get("status", summary.get("final_status", "см. summary.json"))
    tests = validation.get("tests", {})
    role_names = {"orchestrator": "Оркестратор", "specialist:critic": "Критик", "specialist:analyst": "Аналитик", "specialist:interview_simulator": "Синтетический респондент", "specialist:ux_reviewer": "UX-разбор"}
    sections = []

    def section(title, body, tag="", cls=""):
        index = len(sections) + 1
        sections.append(f'<section class="{cls}"><div class="section-top"><span>ПРОДУКТОВЫЙ НАВИГАТОР</span><span>{index:02d} / {esc(tag or "ОПИСАНИЕ РАБОТЫ")}</span></div><h1>{esc(title)}</h1>{body}</section>')

    def note(text):
        return '<p class="note">' + text + '</p>'

    def figure(name, caption):
        return '<figure><img src="screenshots/' + name + '.png"><figcaption>' + esc(caption) + '</figcaption></figure>'

    browser = None
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="chrome", headless=True)
        except Exception:
            browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1200, "height": 900}, device_scale_factor=1)

        def screenshot(name, title, subtitle, cards, footnote):
            page.set_viewport_size({"width": 1000, "height": 850})
            cards_html = ''.join('<article><div class="label">' + esc(label) + '</div><pre>' + esc(text) + '</pre></article>' for label, text in cards)
            content = '''<!doctype html><html lang="ru"><meta charset="utf-8"><style>
            *{box-sizing:border-box}body{margin:0;background:#0e1c2a;color:#dfebef;font:18px/1.5 'Segoe UI',Arial;padding:38px}
            .brand{color:#78d8bf;letter-spacing:3px;font-size:13px;font-weight:700}h1{font-size:30px;margin:12px 0 8px;line-height:1.2}
            .sub{color:#a9bec9;font-size:15px;margin:0 0 24px}article{background:#172c3c;border:1px solid #315064;border-radius:12px;margin:16px 0;overflow:hidden}
            .label{padding:13px 20px;background:#203b4c;color:#8be3cc;font-size:14px;font-weight:600;overflow-wrap:anywhere}
            pre{font:16px/1.55 'Segoe UI',Arial;white-space:pre-wrap;overflow-wrap:anywhere;margin:0;padding:20px}
            footer{color:#a9bec9;font-size:13px;margin-top:24px;line-height:1.5}b{color:#dbe9ed}
            </style><div class="brand">ЖУРНАЛ АГЕНТА · СОХРАНЁННЫЕ ДАННЫЕ</div>'''
            content += '<h1>' + esc(title) + '</h1><p class="sub">' + esc(subtitle) + '</p>' + cards_html + '<footer>' + esc(footnote) + '</footer></html>'
            (shots / (name + ".html")).write_text(content, encoding="utf-8")
            page.set_content(content)
            page.screenshot(path=str(shots / (name + ".png")), full_page=True)

        cost_label = amount(known_cost) + (f" + {unknown} неизвестных" if unknown else "")
        cover = '<p class="eyebrow">ПЕРЕНОСИМЫЙ ИИ-АГЕНТ ДЛЯ РУКОВОДИТЕЛЯ ПРОДУКТА</p><p class="lead">Решение, которое можно<br>проверить и пересмотреть.</p>'
        cover += '<p class="intro">От открытых источников и расчётов — к альтернативам, продуктовой и коммуникационной стратегиям, выбору человека и памяти решения.</p>'
        cover += '<div class="metrics">' + ''.join('<div><b>' + esc(str(n)) + '</b><span>' + esc(t) + '</span></div>' for n, t in [(len(ledger), "реальных API-вызовов"), (len({e.get('model') for e in ledger}), "моделей в журнале"), (cost_label, "известная API-сумма"), (tests.get("passed", "—"), "пройденных тестов")]) + '</div>'
        cover += '<div class="callout"><b>Фактические обращения к OpenRouter сохранены.</b><br>Состояние: <code>' + esc(state) + '</code>. Скриншоты в документе показывают сохранённые вызовы и ответы в локальном просмотрщике журнала.</div>'
        if editorial:
            cover += '<p><b>Итоговая стратегия доработана после редакторской проверки Codex.</b> Это результат с вмешательством оператора; исходный модельный ответ сохранён отдельно.</p>'
        cover += '<p>Кейс: «Круг доверия», семейная цифровая безопасность. Официальный бриф не предоставлен. Стратегия остаётся черновиком до содержательного решения руководителя.</p>'
        cover += '<p class="small">' + link("README.md", "Репозиторий и быстрый старт") + ' · ' + link("submission/live/summary.json", "Фактический итог прогона") + '<br>Дата и время первого вызова: ' + esc(first_at) + '. Часовой пояс указан в исходной записи.</p>'
        section("Продуктовый\nнавигатор", cover, "РЕЗУЛЬТАТ", "cover")

        section("Какое решение помогает принять агент", render('''Руководителю нужно выбрать, **во что вложить следующий ресурс**, когда данные неполны, источники расходятся, а привлекательное обещание ещё не подтверждено продуктом.

Учебная постановка: падает активация семейного цифрового сервиса. Сравнить сохранение текущего решения, улучшение подключения, отдельную подписку и закрытие направления. Не превращать статистику мошенничества в оценку спроса на конкретную функцию.

| Вход | Работа агента | Выход для решения |
|---|---|---|
| Бриф, ограничения, материалы | Формулирует вопросы, меняющие выбор | Явные допущения и пробелы |
| Источники, таблицы, наблюдения | Сохраняет происхождение и локаторы; считает локально | Реестр проверяемых оснований |
| Альтернативы и возражения | Привлекает ограниченные роли специалистов | Различающиеся варианты и условия смены выбора |
| Выбор руководителя | Фиксирует решение и обязательства | Владелец, метрика, срок и стоп-условия |
| Новые сведения | Находит зависимые выводы | История пересмотра, а не молчаливая замена ответа |

**Ценность реализации:** расчёт и источник можно открыть отдельно от красивого текста; незавершённая работа сохраняется; существенный выбор остаётся у человека. Рыночный эффект и превосходство над аналитиком этим не доказаны.

Первый интерфейс — привычная среда Cursor/Codex. Для воспроизведения есть CLI; для подключения инструментов редактора — локальный MCP. Не требуются веб-сервер и отдельная база данных.
'''), "ЗАДАЧА")

        nodes = ''.join('<div class="node"><b>' + esc(role_names.get(role, role)) + '</b><code>' + esc(model) + '</code><small>' + str(data["calls"]) + ' выз. · ' + amount(data["cost"]) + '</small></div>' for (role, model), data in grouped.items())
        section("Ансамбль и разделение ответственности", '<div class="ensemble"><div class="human">Руководитель: задача, ограничения, содержательный выбор</div><div class="arrow">↓</div><div class="nodes">' + nodes + '</div><div class="arrow">↓ ↑</div><div class="tools">Python Toolbox · источники · расчёты · реестр выводов · стратегия</div><div class="arrow">↓ ↑</div><div class="memory">Контрольная точка · история сообщений · события · учёт расходов</div></div>' +
            table(["Слой", "Что обеспечивает"], [["AGENTS.md / prompts / skills", "Постоянные инструкции и повторяемые процедуры; материалы не могут их менять"], ["knowledge/", "Методика анализа, экономики, экспериментов, интервью и памяти"], ["materials/ → artifacts/", "Разделение входных данных, свидетельств и выводов"], ["state/", "Продолжение после паузы; платный ответ сохраняется до исполнения инструментов"], ["Codex, среда разработки", "Код, проверка и подготовка отчёта. Точный идентификатор модели и стоимость среды не предоставлены"]]) + note("Узлы модели построены по ledger.json, а не по настройкам маршрутов. Ответ специалиста — производный анализ, не первичный факт. Строка «Codex, среда разработки» описывает рабочую среду; модель OpenRouter с codex в имени учитывается отдельно по журналу."), "АРХИТЕКТУРА")

        event_counts = Counter(e.get("event", "unknown") for e in events)
        visible_events = [e for e in events if e.get("event") in {"model_started", "model_finished", "specialist_completed", "before_tool", "after_tool", "strategy_submitted", "needs_input", "awaiting_approval", "provider_error", "validation_error"}]
        excerpt = visible_events[:3] + (visible_events[-2:] if len(visible_events) > 3 else [])
        event_text = '\n'.join(str(e.get("at", "")) + '  ' + str(e.get("event", "")) + '\n' + json.dumps(e.get("details", {}), ensure_ascii=False) for e in excerpt)
        screenshot("live-events", "Реальный цикл: модель → инструмент → результат", f"{len(events)} событий · {len(ledger)} API-вызовов · {first_at}", [("ДОСЛОВНЫЕ ЗАПИСИ ИЗ events.jsonl · ВЫБОРКА", transcript_excerpt(event_text, 1700, 14))], "Локальный просмотрщик журнала. Источник: submission/live/events.jsonl. OpenRouter API; это не интерфейс Claude, Qwen или Codex. Между показанными записями есть пропуски; полный журнал приложен.")
        section("След выполнения вместо заявлений", figure("live-events", "Скриншот собственного просмотрщика реального журнала. API-вызовы, инструментальные события и время взяты из сохранённых данных; показана выборка.") + table(["Показатель", "Сохранённое значение"], [["Начало / сохранённое окончание", first_at + " / " + final_at], ["Сумма активных запусков цикла", elapsed_display], ["Итоговое состояние", state], ["Журнал", " · ".join(f"{k}: {v}" for k, v in event_counts.most_common(6))]]) + note("Время активных запусков не включает паузы на разработку и редакторскую проверку. " + link("submission/live/events.jsonl", "Полный журнал событий") + ' · ' + link("submission/live/ledger.json", "Все API-запросы и расходы")), "LIVE / ТРАССА")

        # Each actually invoked specialist has its own transcript evidence page.
        chosen = []
        for desired in ("critic", "interview_simulator", "analyst", "ux_reviewer"):
            match = next(((p, value) for p, value in specialists if value.get("role") == desired), None)
            if match:
                chosen.append(match)
        if not chosen:
            chosen = specialists[:3]
        for index, (path, specialist) in enumerate(chosen, 1):
            model = specialist.get("model", "не указан")
            role = specialist.get("role", "специалист")
            entry = next((e for e in ledger if e.get("provider_id") and e.get("provider_id") == specialist.get("provider_id")), None)
            if entry is None:
                entry = next((e for e in ledger if e.get("purpose") == "specialist:" + role and e.get("model") == model), {})
            stamp = entry.get("started_at", "время не записано")
            metadata = f"{stamp} · {amount(entry.get('cost_usd'), 6)} · вход {entry.get('prompt_tokens', '—')} / выход {entry.get('completion_tokens', '—')} токенов"
            question = None
            specialist_requests = {}
            for message in messages:
                for call in message.get("tool_calls") or []:
                    function = call.get("function", {})
                    if function.get("name") == "consult_specialist":
                        try:
                            arguments = json.loads(function.get("arguments", "{}"))
                        except (ValueError, TypeError):
                            continue
                        specialist_requests[call.get("id")] = arguments
                if message.get("role") == "tool":
                    try:
                        result = json.loads(message.get("content", "{}"))
                    except (ValueError, TypeError):
                        continue
                    if isinstance(result, dict) and result.get("provider_id") and result.get("provider_id") == specialist.get("provider_id"):
                        question = specialist_requests.get(message.get("tool_call_id"), {}).get("question")
                        break
            if not question:
                candidates = [args for args in specialist_requests.values() if args.get("role") == role]
                if len(candidates) == 1:
                    question = candidates[0].get("question")
            cards = [("ЗАДАНИЕ ОТ ОРКЕСТРАТОРА · ДОСЛОВНЫЙ ФРАГМЕНТ", transcript_excerpt(question, 360, 4))] if question else []
            cards.append(("ОТВЕТ МОДЕЛИ · ДОСЛОВНЫЙ ФРАГМЕНТ", transcript_excerpt(specialist.get("content", ""), 1500, 24 if question else 28)))
            name = f"live-specialist-{index}"
            screenshot(name, role_names.get("specialist:" + role, role) + " · " + model, metadata, cards, "Источник: submission/live/specialists/" + path.name + ". Локальный журнал агента; OpenRouter API, не интерфейс Claude/Qwen/Codex. Ответ LLM не считается первичным свидетельством спроса.")
            audit_note = ""
            if editorial and role in {"analyst", "critic"}:
                audit_note = '<p class="small"><b>Результат проверки:</b> в этом ответе смешаны активация и годовое удержание. Вывод о неокупаемости не принят как доказанный; оператор потребовал исправления. Ошибочный ответ сохранён для аудита, а не используется как обоснование итоговой стратегии.</p>'
            section("Отдельный вызов: " + role_names.get("specialist:" + role, role).lower(), figure(name, "Скриншот сохранённого ответа «" + model + "» в локальном просмотрщике. Фрагмент дословный; сокращение обозначено.") + audit_note + note("Идентификатор запроса: <code>" + esc(str(entry.get("id", specialist.get("provider_id", "не указан")))) + "</code>. " + link(path.relative_to(ROOT).as_posix(), "Полный ответ и происхождение") + ". Путь к файлу промпта и поле prompt_sha256 доступны в артефакте, когда они предоставлены runtime."), "LIVE / РОЛИ")

        if strategy:
            draft_fields = [("Продуктовая стратегия", strategy.get("product_strategy", "")), ("Коммуникационная стратегия", strategy.get("communication_strategy", "")), ("Проверка", strategy.get("verification_plan", ""))]
            result_body = ''.join('<h2>' + esc(title) + '</h2><blockquote>' + esc(clip(value, 750)).replace('\n', '<br>') + '</blockquote>' for title, value in draft_fields if value)
            result_body += '<p><b>Рекомендованный ID:</b> <code>' + esc(str(strategy.get("recommended_option", "не указан"))) + '</code>. <b>Сохранённый статус:</b> ' + esc(str(strategy.get("status", state))) + '.</p>'
            gaps = strategy.get("gaps", [])
            if gaps:
                result_body += '<h2>' + ("Непроверенные условия итоговой стратегии" if editorial else "Пробелы, которые признала модель") + '</h2><ul>' + ''.join('<li>' + esc(str(v)) + '</li>' for v in gaps[:5]) + '</ul>'
        else:
            saved = (live / "strategy.md").read_text(encoding="utf-8-sig") if (live / "strategy.md").exists() else "Файл стратегии отсутствует. Факт API-вызова не означает готовность стратегии."
            result_body = '<blockquote>' + esc(clip(saved, 3500)).replace('\n', '<br>') + '</blockquote>'
        if editorial:
            result_body = '<p class="badge">ПОСЛЕ РЕДАКТОРСКОЙ ПРОВЕРКИ CODEX · НЕ АВТОНОМНЫЙ РЕЗУЛЬТАТ</p>' + result_body
            result_body += note("Выдержки из итоговой редакции. Модельный черновик сохранён дословно: " + link("submission/live/model-generated-final.md", "до редактуры") + ". Итог: " + link("submission/live/strategy.md", "после проверки") + ". " + link("submission/live/editorial-revision.json", "Автор, перечень правок и хеши версий") + ". Следующие страницы — отдельный авторский демонстрационный кейс, не ответ модели.")
            section("Стратегия после редакторской проверки", result_body, "LIVE / РЕЗУЛЬТАТ")
        else:
            section("Что выдала модель в этом прогоне", result_body + note("Выдержки именно из live-артефакта. Полный результат: " + link("submission/live/strategy.md", "strategy.md") + ". Следующие страницы показывают авторский демонстрационный кейс; он подготовлен отдельно и не выдается за текст этого ответа."), "LIVE / РЕЗУЛЬТАТ")

        section("Исследование: основания и ограничения", '<p class="badge">АВТОРСКИЙ КЕЙС · ОТКРЫТЫЕ ИСТОЧНИКИ + ПОМЕЧЕННАЯ СИНТЕТИКА</p>' + doc("examples/family-safety/outputs/research.md", "## UX:") + note("Полное исследование, UX-наблюдения и происхождение: " + link("examples/family-safety/outputs/research.md") + ". Сведения источника описывают его утверждения; готовность платить и причинный эффект не измерены."), "КЕЙС / ИССЛЕДОВАНИЕ", "dense")
        section("Четыре пути, включая отказ", doc("examples/family-safety/outputs/options.md"), "КЕЙС / ВЫБОР")
        section("Продуктовая стратегия", doc("examples/family-safety/outputs/product-strategy.md"), "КЕЙС / ПРОДУКТ")
        section("Обещание соответствует продукту", doc("examples/family-safety/outputs/communication-strategy.md"), "КЕЙС / КОММУНИКАЦИЯ")
        section("Как проверить пользу и не навредить", doc("examples/family-safety/outputs/experiments.md"), "КЕЙС / ЭКСПЕРИМЕНТ")

        demo_checks = [c for c in validation.get("checks", []) if "demo.py" in c.get("command", "")]
        revision = demo_checks[-1].get("output", {}) if demo_checks else {}
        screenshot("offline-revision", "Изменилось основание — пересмотрен вывод", "OFFLINE FIXTURE · локальные инструменты · модель не вызывалась", [("СОХРАНЁННЫЙ ВЫВОД scripts/demo.py --phase revise", json.dumps(revision, ensure_ascii=False, indent=2))], "Это проверка механики пересмотра на учебных данных. Источник: submission/validation.json. Не live-ответ LLM и не наблюдаемый результат продуктового эксперимента.")
        section("Память решения: цена нового основания", render('''В отдельном офлайн-тесте агент получает новое **синтетическое** условие: дополнительная годовая маржа меняется с 600 до 100 ₽ на семью. При бюджете 900 000 ₽ порог меняется с 1500 до 9000 дополнительно сохранённых семей.

Прежнее экономическое основание отзывается; зависимый вывод становится устаревшим. Обновляются расчёт и стратегия, исходный черновик остаётся в истории. Следующее состояние — запрос решения, а не автоматическое утверждение новой стратегии.
''') + figure("offline-revision", "Скриншот настоящего вывода офлайн-проверки. Статусы, affected_claims и новый расчёт взяты из validation.json.") + note(link("examples/family-safety/outputs/changes.md", "Полная логика пересмотра") + ' · ' + link("submission/replay/strategy-before-revision.json", "До") + ' · ' + link("submission/replay/strategy.json", "После")), "OFFLINE / ПЕРЕСМОТР")

        comparison_body = '<p>Сравнение относится к одному учебному корпусу и конкретным настройкам. Его нельзя переносить на все задачи, модели и команды.</p>'
        if editorial:
            comparison_body += '<p class="badge">BASELINE СРАВНИВАЕТСЯ С МОДЕЛЬНЫМ ЧЕРНОВИКОМ ДО ФИНАЛЬНОЙ РЕДАКТУРЫ</p>'
        if comparison:
            display_rows = comparison.get("rows") or comparison.get("metrics")
            measured_pair = isinstance(display_rows, dict) and isinstance(display_rows.get("baseline"), dict) and isinstance(display_rows.get("agent"), dict)
            if measured_pair:
                baseline, agent = display_rows["baseline"], display_rows["agent"]
                def seconds(value):
                    return "не измерено" if value is None else f"{value:.1f} с"
                def tokens(value):
                    return "неизвестно" if value is None else f"{value:,.0f}".replace(",", " ")
                comparison_body += table(["Показатель", "Обычный чат", "Агент"], [
                    ["Модели", baseline.get("returned_model") or baseline.get("requested_model", "—"), ", ".join(agent.get("model_ids", []))],
                    ["API-вызовы", 1 if baseline.get("paid_call_attempted") else 0, agent.get("paid_requests_recorded", "—")],
                    ["API-стоимость", amount(baseline.get("cost_usd"), 6), amount(agent.get("cost_usd"), 6)],
                    ["Длительность", seconds(baseline.get("wall_time_seconds")), seconds(agent.get("wall_time_seconds"))],
                    ["Токены вход / выход", tokens(baseline.get("prompt_tokens")) + " / " + tokens(baseline.get("completion_tokens")), tokens(agent.get("prompt_tokens")) + " / " + tokens(agent.get("completion_tokens"))],
                    ["Лимит расходов", amount(baseline.get("budget_usd")), amount(agent.get("budget_usd"))],
                    ["Ручные исправления", "не измерены", "не измерены"],
                ])
                protocol = comparison.get("protocol", {})
                same_input = comparison.get("same_raw_input_at_summary")
                comparison_body += '<p><b>Совпадение исходного корпуса при сверке:</b> ' + ("да" if same_input is True else "нет" if same_input is False else "не проверено") + '. Один ответ чата без инструментов и повторной генерации; готовые выводы агента не входят в запрос baseline. Прогон агента включал указания оператора. Разные процессы и бюджетные лимиты не образуют контролируемое сравнение архитектур.</p>'
                automatic = comparison.get("automatic_checks", {})
                auto_baseline, auto_agent = automatic.get("baseline", {}), automatic.get("agent", {})
                checks_to_show = [("schema_valid", "Структура ответа соответствует схеме"), ("three_option_kinds", "Есть статус-кво, изменение и закрытие"), ("option_descriptions_and_objections", "У вариантов записаны описания и возражения"), ("strategies_and_experiment_present", "Заполнены обе стратегии и план проверки")]
                def observed(value):
                    return "да" if value is True else "нет" if value is False else "нет записи"
                comparison_body += '<h2>Автоматические наблюдения, без оценки смысла</h2>' + table(["Наблюдение", "Чат", "Агент"], [[title, observed(auto_baseline.get(key, {}).get("passed")), observed(auto_agent.get(key, {}).get("passed"))] for key, title in checks_to_show])
                manual = comparison.get("manual_assessment", {})
                comparison_body += '<p><b>Содержательная оценка:</b> ' + ("ещё не выполнена" if manual.get("status") == "pending" else esc(str(manual.get("status", "не записана")))) + '. Наличие цитаты не доказывает поддержку утверждения; заполненное поле не доказывает корректность эксперимента.</p>'
                if manual.get("conclusion"):
                    comparison_body += '<p>' + esc(str(manual["conclusion"])) + '</p>'
                comparison_body += '<p>n=1. Время чата — время модельного запроса; время агента — измеренные запуски цикла. Человек-аналитик не измерялся. Суммарная известная API-стоимость обоих режимов: <b>' + amount(display_rows.get("combined_cost_usd"), 6) + '</b>.</p>'
            elif isinstance(display_rows, list) and display_rows and isinstance(display_rows[0], dict):
                keys = list(display_rows[0])
                comparison_body += table(keys, [[r.get(k, "—") for k in keys] for r in display_rows])
            elif isinstance(display_rows, dict):
                comparison_body += table(["Показатель", "Результат"], [[k, json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v] for k, v in display_rows.items()])
            else:
                comparison_body += '<pre>' + esc(clip(json.dumps(comparison, ensure_ascii=False, indent=2), 5000)) + '</pre>'
            for field in ("interpretation", "conclusion", "limitations", "notes"):
                if measured_pair and field == "limitations":
                    continue
                value = comparison.get(field)
                if value:
                    if isinstance(value, list):
                        comparison_body += '<ul>' + ''.join('<li>' + esc(str(v)) + '</li>' for v in value) + '</ul>'
                    else:
                        comparison_body += '<p>' + esc(str(value)) + '</p>'
        else:
            comparison_body += render('''**Измеренное сопоставление ещё не приложено.** Честный протокол требует одного брифа и корпуса, сопоставимых ограничений времени/бюджета и независимых критериев оценки.

| Режим | Что измерять |
|---|---|
| Обычный чат | Один запрос на том же корпусе; токены, время, стоимость, ссылки и обещания |
| Агент | Тот же бриф; дополнительно воспроизводимость расчётов и сохранение состояния |
| Аналитик | Фактическое время человека и явно согласованная ставка; сейчас не измерены |
''')
        comparison_body += note("Наличие реестра и инструментов — наблюдаемое отличие реализации; само по себе оно не доказывает более высокое содержательное качество. Время разработки и расходы среды Codex в стоимость OpenRouter не включены. " + link("submission/live/comparison.json", "Сырые результаты сравнения") + ' · ' + link("submission/benchmark/baseline.md", "Ответ обычного чата") + ' · ' + link("docs/EVALUATION.md", "Протокол"))
        section("Обычный чат и агент: наблюдаемая разница", comparison_body, "СРАВНЕНИЕ")

        model_rows = [[role_names.get(role, role), model, v["calls"], str(v["in"]) + " / " + str(v["out"]), amount(v["cost"], 6) + (f" + {v['unknown']} неизвестных" if v["unknown"] else "")] for (role, model), v in grouped.items()]
        cost_body = table(["Роль", "Модель из журнала", "Выз.", "Токены вход/выход", "Известная сумма"], model_rows)
        cost_body += '<div class="callout"><b>Итого OpenRouter: ' + esc(cost_label) + '.</b> Активные запуски цикла: ' + esc(elapsed_display) + '. Неизвестных стоимостей: ' + str(unknown) + '.</div>'
        cost_body += '<p>Это расходы показанного агентного прогона. Базовый чат, если он проведён, учитывается отдельно в сравнении. Подписка среды разработки, труд человека и разработка агента не измерены и не включены. Число токенов и цена берутся из ответа провайдера, а не из прайс-листа.</p>'
        if reconciliation:
            cost_body += '<p><b>Сверка общего расхода:</b> журнал агента + базовый чат = ' + amount(reconciliation.get("recorded_total_usd"), 8) + '; использование API по ответу OpenRouter = ' + amount(reconciliation.get("openrouter_key_usage_usd"), 8) + '. Разница: ' + amount(reconciliation.get("difference_usd"), 8) + '. ' + link("submission/cost-reconciliation.json", "Снимок сверки без секретов и идентификаторов аккаунта") + '.</p>'
        if editorial:
            cost_body += '<p><b>Финальная редактура:</b> отдельная проверка агентом разработки нашла смысловые недочёты в модельной стратегии. Codex внёс явные правки в итоговые файлы; исходный ответ и история сообщений сохранены. Это операторская доработка, а не автономное исправление модели. ' + link("submission/live/editorial-revision.json", "Перечень правок и контрольные хеши") + '.</p>'
        interventions = summary.get("human_interventions", [])
        failures = summary.get("failures", [])
        if interventions:
            intervention_rows = []
            for item in interventions:
                if not isinstance(item, dict):
                    intervention_rows.append(["—", str(item)])
                    continue
                at = item.get("at", "Начало")
                if "T" in at:
                    at = at.split("T", 1)[1].split("+", 1)[0] + " UTC"
                action = item.get("action", "")
                if action.startswith("Paused after 12 planning steps"):
                    action = "После 12 шагов исправлены постоянный дорогой маршрут Claude и учёт ошибок инструментов. Исходный журнал сохранён."
                elif action.startswith("Archived and compacted 50 messages"):
                    action = "Архивированы 50 сообщений и сокращён контекст. Запрошены исправления периода источника и смешения активации с годовым удержанием; выдуманные примеры критика отклонены."
                elif action.startswith("Independent audit rejected first submission"):
                    action = "Первый черновик отклонён после проверки. Синтез переключён на Claude; запрошены исправления периода, метрик, A/B-критериев и неподтверждённых обещаний."
                elif item.get("kind") == "explicit_editorial_revision":
                    action = "Финальная редактура Codex: отделены спрос и статистика; уточнены причинность, экономика, обещания, эксперимент и условия пересмотра. Исходный ответ сохранён."
                intervention_rows.append([at, action or item.get("reason", "См. исходную запись")])
            cost_body += '<h2>Вмешательства оператора Codex</h2>' + table(["Время", "Действие — краткое изложение журнала"], intervention_rows)
            cost_body += '<p class="small">Это действия оператора проверки, не утверждение бизнес-решения руководителем. Дословные действия, причины и исполнители — в summary.json и истории сообщений.</p>'
        else:
            cost_body += '<h2>Участие человека</h2><p>Пользователь поставил задачу и разрешил подготовку; выполнение и тестирование организованы в Codex. Минуты ручных исправлений не измерены. Бизнес-решение не утверждается этим отчётом.</p>'
        if failures:
            failure_groups = Counter()
            for failure in failures:
                if isinstance(failure, dict):
                    details = failure.get("details", {})
                    key = details.get("message") or details.get("code") or details.get("error") or failure.get("error") or failure.get("event", "ошибка")
                else:
                    key = str(failure)
                failure_groups[str(key)] += 1
            cost_body += '<h2>Зарегистрированные ошибки</h2>' + table(["Ошибка / ограничение", "Случаев"], [[key, count] for key, count in failure_groups.items()])
            cost_body += '<p class="small">Повторы сгруппированы по одинаковому сообщению. Полные записи и последующие действия: ' + link("submission/live/summary.json", "summary.json") + ' и ' + link("submission/live/events.jsonl", "events.jsonl") + '. Ошибочный экономический сценарий сохранён в economics-rejected.json и исключён из активных данных после проверки.</p>'
        else:
            error_events = [e for e in events if "error" in e.get("event", "") or "failed" in e.get("event", "")]
            cost_body += '<p>Событий ошибки в сохранённом журнале: ' + str(len(error_events)) + '. Это не утверждение об отсутствии всех возможных ошибок рассуждения.</p>'
        section("Расходы, ограничения и вмешательства", cost_body, "УЧЁТ", "cost-page")

        tests_body = table(["Проверка", "Что действительно подтверждено"], [["Автотесты", f"{tests.get('passed', '—')} пройдено; {len(tests.get('skipped', []))} пропущено; ошибок: {tests.get('errors', '—')}; падений: {tests.get('failures', '—')}."], ["Офлайн-воспроизведение", "Пауза, продолжение, расчёт, отзыв основания, ожидание выбора человека; API = $0 только для этой проверки"], ["Live OpenRouter", f"{len(ledger)} сохранённых запросов; {len(specialists)} отдельных артефактов специалистов; порядок инструментов записан в событиях"], ["Новая SaaS-задача", "Отдельная проверка среды разработки: обещание +20% остаётся неподтверждённым прогнозом; задан существенный вопрос"], ["MCP", "Локальный handshake, список/вызов инструментов и сохранение вопроса между процессами"]])
        tests_body += render('''### Известные границы

Реальные интервью, продуктовые эксперименты и бизнес-эффект не измерены. Синтетический респондент формулирует гипотезы. Текстовая UX-инструкция не считается просмотром интерфейса. Нативное распознавание изображений, аудио и видео не заявлено; PDF требует текстового слоя.

Существование ссылки не доказывает, что она поддерживает вывод. Локальная защита путей и тесты инъекций не означают абсолютной устойчивости LLM к смысловой манипуляции. Недоступность сайта сохраняется как ограничение, а не восполняется выдуманными сведениями.

### Что исправлялось при разработке

Несовпадение единиц accounts/families; обработка возвращаемых ошибок инструментов; запрет утверждения с отозванными основаниями; сохранение оплаченного ответа перед исполнением; сохранение вопроса из MCP. Конкретные регрессии проверяются автотестами. На Windows тест симлинков может пропускаться без системного разрешения; список пропусков сохранён.
''')
        tests_body += note(link("submission/validation.json", "Итог локальной проверки") + ' · ' + link("submission/checks.txt", "Команды и вывод") + ' · ' + link("docs/FORWARD_TEST.md", "Независимый сценарий новой задачи"))
        section("Качество проверено на разных уровнях", tests_body, "ВАЛИДАЦИЯ")

        section("Запуск и карта доказательств", render('''```bash
python -m strategy_agent doctor
python scripts/demo.py --project workspace/demo --phase pause
python scripts/demo.py --project workspace/demo --phase finish
python scripts/demo.py --project workspace/demo --phase revise
```

Офлайн-запуск не требует ключа. Для live-режима модель и секрет задаются через локальное окружение по README; ключи не попадают в отчёт и артефакты. Создавайте новую папку проекта. Продолжение: `status`, `answer`, `resume`; утверждение варианта выполняется отдельной командой с владельцем, сроком и метрикой.

| Критерий | Проверяемое свидетельство |
|---|---|
| Проработанность | Реестр источников, альтернативы, две согласованные стратегии, экономика и план проверки |
| Нейротехнологии | Живой цикл инструментов, фактические модели и роли, ограниченные контексты, навыки и память |
| Имплементация | CLI/MCP над одним ядром, тесты, пауза/продолжение, перенос на новую задачу |
| Качество | Фактические время/расходы, признанные пробелы, запрос решения, сохранённые артефакты |

Таблица связывает критерии с доказательствами, а не присваивает баллы. Максимальную оценку определяет жюри. Для окончательной подачи остаются сверка с официальным брифом после его получения и обязательный видеоролик, отложенный по запросу владельца.

Пересборка отчёта: `python scripts/build_description.py` после установки `requirements-docs.txt` и Chromium/Chrome. Генератор читает только подготовленные артефакты и не делает платных запросов.
''') + note(link("README.md", "README: полный запуск") + ' · ' + link("docs/LIVE_EVIDENCE.md", "Происхождение скриншотов и протокол live") + '<br>' + link("submission/live/summary.json") + ' · ' + link("submission/live/ledger.json") + ' · ' + link("submission/live/events.jsonl")), "ВОСПРОИЗВЕДЕНИЕ")

        css = '''@page{size:A4;margin:14mm 15mm 17mm}*{box-sizing:border-box}body{font-family:'Segoe UI',Arial,sans-serif;font-size:10.2px;line-height:1.46;color:#173243;margin:0}section{break-before:page}section:first-child{break-before:auto}h1{font-size:27px;line-height:1.12;margin:17px 0 19px;color:#123e50;white-space:pre-line}h2{font-size:14px;margin:17px 0 7px;color:#1e5c65}h3{font-size:12px;margin:16px 0 6px}h1,h2,h3{break-after:avoid}p{margin:9px 0}p,li{orphans:3;widows:3}ul,ol{padding-left:19px}li{margin:4px 0}.section-top{display:flex;justify-content:space-between;color:#63838e;font-size:8px;letter-spacing:1.4px;padding-bottom:10px;border-bottom:1px solid #b9d4d9}.eyebrow{font-size:9px;letter-spacing:1.5px;color:#47727d}.lead{font-size:32px;line-height:1.2;font-weight:600;margin:34px 0 24px}.intro{font-size:16px;line-height:1.5;max-width:550px}.cover h1{font-size:48px;margin-top:38px}.cover .metrics{margin:32px 0}.metrics{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}.metrics div{padding:17px;background:#eaf4f2;border-top:3px solid #27977e}.metrics b{display:block;font-size:26px;line-height:1.2;color:#145f53}.metrics span{display:block;font-size:11px;margin-top:7px}.callout{background:#eaf4f2;border-left:4px solid #26987c;padding:15px 18px;margin:16px 0;font-size:12px}.small,.note{font-size:9px;color:#5a7580}.note{border-top:1px solid #d4e3e7;padding-top:10px;margin-top:15px}.badge{font-size:8px;font-weight:600;letter-spacing:1.2px;color:#2a7f71;background:#edf7f2;padding:9px 11px}table{width:100%;border-collapse:collapse;font-size:9px;margin:12px 0;table-layout:auto}th,td{padding:7px;border-bottom:1px solid #c9dce1;vertical-align:top;text-align:left;overflow-wrap:anywhere}th{background:#eaf1f3;color:#235268;font-weight:600}tr{break-inside:avoid}pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:14px;background:#ecf2f4;font:9px/1.5 Consolas,monospace}code{font-family:Consolas,monospace;font-size:.95em;overflow-wrap:anywhere}a{color:#187b88;text-decoration:none;overflow-wrap:anywhere}blockquote{border-left:3px solid #58a995;background:#f0f7f5;margin:10px 0;padding:12px 15px;font-size:10px;line-height:1.5}figure{margin:12px 0;break-inside:avoid}figure img{display:block;width:100%;max-height:196mm;object-fit:contain;object-position:top}figcaption{font-size:8px;color:#5c7680;line-height:1.4;margin:6px 0}.ensemble{text-align:center;margin:18px 0}.human,.tools,.memory{padding:13px;border-radius:7px;background:#173f52;color:#eef7f8}.memory{background:#e8f3ef;color:#226c5a}.arrow{font-size:19px;color:#348b78;margin:3px}.nodes{display:flex;flex-wrap:wrap;justify-content:center;gap:9px}.node{padding:14px 10px;border:1px solid #a7cfc4;background:#eef7f4;border-radius:7px;flex:1;min-width:150px}.node b{display:block;color:#176e5e;font-size:12px}.node code{display:block;font-size:9px;margin:7px 0}.node small{font-size:8px;color:#5a7980}@media screen{html{background:#e9f0f2}body{max-width:1000px;background:white;margin:auto;padding:40px}section{margin-bottom:65px}}'''
        css += '.dense{font-size:9.6px;line-height:1.4}.dense table{font-size:8.6px}.dense th,.dense td{padding:6px}.dense td:first-child{min-width:28px}.cost-page{font-size:9.2px;line-height:1.35}.cost-page table{font-size:8.3px}.cost-page th,.cost-page td{padding:5px}.cost-page h2{font-size:13px;margin-top:13px}.cost-page .callout{font-size:11px;padding:11px 14px}.cost-page .small{font-size:8px}'
        document = '<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Продуктовый навигатор — проверяемый агент</title><style>' + css + '</style></head><body>' + ''.join(sections) + '</body></html>'
        target = out / "description.html"
        target.write_text(document, encoding="utf-8")
        page.goto(target.as_uri())
        page.emulate_media(media="print")
        page.pdf(path=str(out / "description.pdf"), format="A4", print_background=True, display_header_footer=True, header_template='<span></span>', footer_template='<div style="width:100%;font:8px Arial;color:#69838c;text-align:center;">Продуктовый навигатор · Фактические данные и обозначенные ограничения · <span class="pageNumber"></span> / <span class="totalPages"></span></div>')
        page.screenshot(path=str(shots / "description-preview.png"), full_page=False)
        browser.close()
    print(f"Saved live description: {len(sections)} sections, {len(ledger)} recorded API calls, known cost {amount(known_cost, 6)}")


def main():
    summary = read_json(ROOT / "submission/live/summary.json", {})
    # A file or a nonempty ledger alone is not a claim that the live check passed.
    if summary.get("live_openrouter_generation_tested") is True or summary.get("live_generation_tested") is True:
        live_main(summary)
    else:
        offline_main()


if __name__ == "__main__":
    main()
