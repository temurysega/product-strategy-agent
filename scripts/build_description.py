"""Render the actual local verification, research and architecture into HTML/PDF."""
from pathlib import Path
import html
import json
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]


def main():
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


if __name__ == "__main__":
    main()
