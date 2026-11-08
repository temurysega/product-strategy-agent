"""Bounded document readers and HTTPS fetcher. Source text is always untrusted data."""
from __future__ import annotations

import csv
import hashlib
import html
from html.parser import HTMLParser
import http.client
import io
import ipaddress
from pathlib import Path
import re
import socket
import ssl
from urllib.parse import urlsplit, urljoin
import xml.etree.ElementTree as ET
import zipfile

MAX_BYTES = 2_000_000
MAX_EXPANDED = 20_000_000


class MaterialError(ValueError):
    pass


def material_path(project: Path, relative: str) -> Path:
    """Only regular material files, never secret or outside paths, including symlinks."""
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise MaterialError("Укажите относительный путь materials/… с прямыми слешами.")
    p = Path(relative)
    if p.is_absolute() or ".." in p.parts or not p.parts or p.parts[0] != "materials":
        raise MaterialError("Разрешены только файлы внутри materials/.")
    if any(part.startswith(".") or part.lower() in {"secrets", "credentials"} for part in p.parts):
        raise MaterialError("Скрытые файлы и секреты недоступны инструментам.")
    project = project.resolve()
    current = project
    for part in p.parts:
        current = current / part
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise MaterialError("Символические ссылки и junction не разрешены.")
    target = (project / p).resolve()
    if not target.is_relative_to(project / "materials"):
        raise MaterialError("Файл находится вне materials/.")
    if not target.is_file():
        raise MaterialError("Материал не найден.")
    if target.stat().st_size > MAX_BYTES:
        raise MaterialError(f"Материал больше {MAX_BYTES} байт; разделите его.")
    return target


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden += 1
        if tag in {"p", "div", "li", "h1", "h2", "h3", "br", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_html(text: str) -> str:
    reader = PlainHTML()
    reader.feed(text)
    return "\n".join(line.strip() for line in "".join(reader.parts).splitlines() if line.strip())


def _xml(data: bytes):
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise MaterialError("DTD и XML entities не разрешены.")
    return ET.fromstring(data)


def _office(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        if sum(item.file_size for item in archive.infolist()) > MAX_EXPANDED:
            raise MaterialError("Слишком большой распакованный документ.")
        if path.suffix.lower() == ".docx":
            root = _xml(archive.read("word/document.xml"))
            return "\n".join("".join(p.itertext()) for p in root.iter() if p.tag.endswith("}p"))
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = _xml(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(node.itertext()) for node in root if node.tag.endswith("}si")]
        chunks = []
        for filename in sorted(archive.namelist()):
            if not re.fullmatch(r"xl/worksheets/sheet\d+\.xml", filename):
                continue
            chunks.append(f"Лист: {filename}")
            root = _xml(archive.read(filename))
            for row in root.iter():
                if not row.tag.endswith("}row"):
                    continue
                cells = []
                for cell in row:
                    values = [n.text or "" for n in cell.iter() if n.tag.endswith("}v") or n.tag.endswith("}t")]
                    value = " ".join(values)
                    if cell.attrib.get("t") == "s" and value:
                        value = shared[int(value)]
                    cells.append(f"{cell.attrib.get('r', '?')}={value}")
                chunks.append(" | ".join(cells))
        return "\n".join(chunks)


def read_document(path: Path) -> dict:
    suffix = path.suffix.lower()
    data = path.read_bytes()
    warnings = []
    if suffix in {".docx", ".xlsx"}:
        content = _office(path)
        if suffix == ".xlsx":
            warnings.append("Формулы не вычисляются: читаются сохранённые значения и координаты ячеек; для расчётов экспортируйте CSV.")
    elif suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise MaterialError("PDF требует optional dependency pypdf; либо экспортируйте текст в UTF-8. OCR не выполняется.") from exc
        reader = PdfReader(str(path))
        if len(reader.pages) > 100:
            raise MaterialError("PDF больше 100 страниц; разделите документ.")
        content = "\n".join(f"Страница {i + 1}\n{page.extract_text() or ''}" for i, page in enumerate(reader.pages))
        warnings.append("PDF: текстовый слой без OCR; пустые страницы не являются свидетельством отсутствия информации.")
    elif suffix in {".txt", ".md", ".csv", ".json", ".html", ".htm", ".vtt", ".srt"}:
        try:
            content = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise MaterialError("Нужен UTF-8; преобразуйте кодировку материала.") from exc
        if suffix in {".html", ".htm"}:
            content = plain_html(content)
    else:
        raise MaterialError("Формат не поддерживается. Изображения/аудио/видео требуют подписанной расшифровки или описания с координатами/таймкодами; агент не делает вид, что видел материал.")
    if not content.strip():
        raise MaterialError("Нет извлечённого текста; нужен текстовый слой или расшифровка.")
    if len(content) > MAX_EXPANDED:
        raise MaterialError("Извлечённый текст слишком велик.")
    return {"content": content, "sha256": hashlib.sha256(data).hexdigest(), "warnings": warnings, "format": suffix[1:]}


def validated_endpoint(url: str, allowed_domains: list[str]) -> tuple[str, str, str]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise MaterialError("Разрешены только HTTPS URL без credentials и нестандартного порта.")
    host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    if host not in {d.lower().rstrip(".") for d in allowed_domains}:
        raise MaterialError("Домен отсутствует в sources-policy.json: allowed_domains; разрешение задаёт человек.")
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise MaterialError("Не удалось разрешить DNS источника.") from exc
    ips = {item[4][0] for item in addresses}
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise MaterialError("Локальные, частные и служебные IP запрещены.")
    return host, sorted(ips)[0], (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to validated IP, keeping hostname for certificate checking/SNI."""
    def __init__(self, host: str, ip: str):
        super().__init__(host, timeout=15, context=ssl.create_default_context())
        self.validated_ip = ip

    def connect(self):
        sock = socket.create_connection((self.validated_ip, 443), timeout=self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def fetch_text(url: str, allowed_domains: list[str]) -> dict:
    original = url
    for attempt in range(4):
        host, address, target = validated_endpoint(url, allowed_domains)
        connection = PinnedHTTPSConnection(host, address)
        try:
            connection.request("GET", target, headers={"User-Agent": "ProductStrategyAgent/1.0 (+research)", "Accept": "text/html,text/plain,application/json", "Accept-Encoding": "identity"})
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location:
                    raise MaterialError("Перенаправление без Location.")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise MaterialError(f"Источник вернул HTTP {response.status}; недоступность не означает отсутствие фактов.")
            mime = response.getheader("Content-Type", "text/plain").split(";")[0].strip().lower()
            if mime not in {"text/html", "text/plain", "text/csv", "application/json", "application/xhtml+xml"}:
                raise MaterialError("Веб-источник не текстовый; скачайте разрешённый документ вручную в materials/.")
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise MaterialError("Веб-источник превышает лимит размера.")
            encoding_match = re.search(r"charset=([\w-]+)", response.getheader("Content-Type", ""), re.I)
            encoding = encoding_match.group(1) if encoding_match else "utf-8"
            try:
                content = data.decode(encoding)
            except (LookupError, UnicodeDecodeError) as exc:
                raise MaterialError("Не удалось декодировать веб-источник.") from exc
            if mime in {"text/html", "application/xhtml+xml"}:
                content = plain_html(content)
            return {"content": content, "sha256": hashlib.sha256(data).hexdigest(), "locator": url, "origin_url": original, "mime": mime, "warnings": []}
        finally:
            connection.close()
    raise MaterialError("Слишком много перенаправлений.")
