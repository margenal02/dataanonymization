import zipfile
import re
import shutil
# Only fixed local OCR binaries are invoked with list arguments and without a shell.
import subprocess  # nosec B404
import tempfile
from difflib import SequenceMatcher
from pathlib import Path, PurePosixPath

import xlrd
from charset_normalizer import from_bytes
from django.conf import settings
from docx import Document
from docx.oxml.ns import qn
from lxml import etree
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas
from xlutils.copy import copy as copy_xls


SUPPORTED_EXTENSIONS = {".txt", ".docx", ".pdf", ".xls", ".ofd"}
OLE_HEADER = bytes.fromhex("D0CF11E0A1B11AE1")
MAX_ARCHIVE_ENTRIES = 5000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
MAX_ARCHIVE_ENTRY_BYTES = 80 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200


class ProcessingError(Exception):
    pass


def _validate_archive(upload, extension):
    try:
        with zipfile.ZipFile(upload, "r") as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_ENTRIES:
                raise ProcessingError("压缩容器包含过多文件，已拒绝处理。")
            total_size = 0
            names = set()
            for info in infos:
                normalized = info.filename.replace("\\", "/")
                path = PurePosixPath(normalized)
                if path.is_absolute() or ".." in path.parts or re.match(r"^[A-Za-z]:", normalized):
                    raise ProcessingError("文件包含不安全的内部路径，已拒绝处理。")
                if info.flag_bits & 0x1:
                    raise ProcessingError("暂不支持内部条目加密的文件。")
                if info.file_size > MAX_ARCHIVE_ENTRY_BYTES:
                    raise ProcessingError("文件中的单个内容项过大，已拒绝处理。")
                total_size += info.file_size
                compressed = max(info.compress_size, 1)
                if info.file_size / compressed > MAX_COMPRESSION_RATIO:
                    raise ProcessingError("文件压缩比异常，可能存在压缩炸弹。")
                names.add(normalized.lower())
            if total_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                raise ProcessingError("文件解压后的总体积过大，已拒绝处理。")
            if extension == ".docx" and not {"[content_types].xml", "word/document.xml"}.issubset(names):
                raise ProcessingError("文件扩展名为 DOCX，但内容不是有效的 Word 文档。")
            if extension == ".ofd" and not any(name == "ofd.xml" or name.endswith("/ofd.xml") for name in names):
                raise ProcessingError("文件扩展名为 OFD，但缺少 OFD.xml。")
    except zipfile.BadZipFile as exc:
        raise ProcessingError(f"文件扩展名为 {extension.upper()}，但内容不是有效的压缩文档。") from exc
    finally:
        upload.seek(0)


def validate_upload_content(upload):
    """Verify file signatures and reject dangerous archive structures."""
    extension = Path(upload.name).suffix.lower()
    upload.seek(0)
    header = upload.read(1024)
    upload.seek(0)
    if extension == ".pdf" and not header.lstrip().startswith(b"%PDF-"):
        raise ProcessingError("文件扩展名为 PDF，但内容不是有效的 PDF。")
    if extension == ".xls" and not header.startswith(OLE_HEADER):
        raise ProcessingError("文件扩展名为 XLS，但内容不是有效的 Excel 97-2003 文件。")
    if extension in {".docx", ".ofd"}:
        _validate_archive(upload, extension)
    if extension == ".txt":
        if b"\x00" in header:
            raise ProcessingError("TXT 文件包含二进制内容，已拒绝处理。")
        match = from_bytes(header).best()
        if header and match is None:
            raise ProcessingError("TXT 文件编码无法识别。")
    upload.seek(0)


XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def _set_text_node(node, value):
    node.text = value
    if value and (value[0].isspace() or value[-1].isspace()):
        node.set(XML_SPACE, "preserve")
    else:
        node.attrib.pop(XML_SPACE, None)


def _replace_text_nodes(text_nodes, transform):
    """Replace only changed spans while preserving the surrounding XML run nodes."""
    if not text_nodes:
        return
    original_parts = [node.text or "" for node in text_nodes]
    original = "".join(original_parts)
    changed = transform(original)
    if changed == original:
        return

    ranges = []
    cursor = 0
    for part in original_parts:
        ranges.append((cursor, cursor + len(part)))
        cursor += len(part)
    result_parts = list(original_parts)

    def anchor_for(offset):
        for index, (start, end) in enumerate(ranges):
            if start <= offset < end:
                return index
            if start == offset and start == end:
                return index
        return max(0, len(ranges) - 1)

    edits = [
        opcode for opcode in SequenceMatcher(None, original, changed, autojunk=False).get_opcodes()
        if opcode[0] != "equal"
    ]
    for _, source_start, source_end, changed_start, changed_end in reversed(edits):
        anchor = anchor_for(source_start)
        anchor_start = ranges[anchor][0]
        insertion_offset = max(0, source_start - anchor_start)
        for index, (node_start, node_end) in enumerate(ranges):
            overlap_start = max(source_start, node_start)
            overlap_end = min(source_end, node_end)
            if overlap_start >= overlap_end:
                continue
            local_start = overlap_start - node_start
            local_end = overlap_end - node_start
            result_parts[index] = result_parts[index][:local_start] + result_parts[index][local_end:]
        replacement = changed[changed_start:changed_end]
        result_parts[anchor] = (
            result_parts[anchor][:insertion_offset]
            + replacement
            + result_parts[anchor][insertion_offset:]
        )

    for node, value in zip(text_nodes, result_parts):
        _set_text_node(node, value)


def _transform_docx_xml_parts(document, transform):
    """Process text boxes and other Word text that python-docx does not expose as paragraphs."""
    seen_paragraphs = set()
    for part in document.part.package.parts:
        root = getattr(part, "element", None)
        if root is None:
            root = getattr(part, "_element", None)
        if root is None or not hasattr(root, "iter"):
            continue
        for paragraph in root.iter(qn("w:p")):
            paragraph_id = id(paragraph)
            if paragraph_id in seen_paragraphs:
                continue
            seen_paragraphs.add(paragraph_id)
            text_nodes = list(paragraph.iter(qn("w:t")))
            if not text_nodes:
                continue
            original = "".join(node.text or "" for node in text_nodes)
            if original:
                _replace_text_nodes(text_nodes, transform)


def process_docx(source, destination, transform):
    document = Document(source)
    _transform_docx_xml_parts(document, transform)
    document.save(destination)


def _read_text(source):
    raw = Path(source).read_bytes()
    match = from_bytes(raw).best()
    if match is None:
        return raw.decode("utf-8", errors="replace"), "utf-8"
    return str(match), match.encoding or "utf-8"


def process_txt(source, destination, transform):
    content, encoding = _read_text(source)
    try:
        Path(destination).write_text(transform(content), encoding=encoding)
    except (LookupError, UnicodeEncodeError):
        Path(destination).write_text(transform(content), encoding="utf-8-sig")


def process_xls(source, destination, transform):
    try:
        book = xlrd.open_workbook(source, formatting_info=True)
        writable = copy_xls(book)
        for sheet_index in range(book.nsheets):
            source_sheet = book.sheet_by_index(sheet_index)
            target_sheet = writable.get_sheet(sheet_index)
            for row in range(source_sheet.nrows):
                for col in range(source_sheet.ncols):
                    cell = source_sheet.cell(row, col)
                    if cell.ctype == xlrd.XL_CELL_TEXT:
                        changed = transform(cell.value)
                        if changed != cell.value:
                            target_sheet.write(row, col, changed)
        writable.save(destination)
    except Exception as exc:
        raise ProcessingError(f"XLS 文件解析失败：{exc}") from exc


def _notify_progress(progress_callback, **payload):
    if progress_callback:
        progress_callback(payload)


def _ocr_pdf_page(source, page_number):
    pdftoppm = shutil.which("pdftoppm")
    tesseract = shutil.which("tesseract")
    if not pdftoppm or not tesseract:
        raise ProcessingError("扫描 PDF 需要本地 OCR 组件，请重新运行一键安装脚本更新后端镜像。")

    dpi = max(72, min(300, int(getattr(settings, "PDF_OCR_DPI", 180))))
    max_dimension = max(1200, min(5000, int(getattr(settings, "PDF_OCR_MAX_IMAGE_DIMENSION", 3508))))
    timeout_seconds = max(30, min(600, int(getattr(settings, "PDF_OCR_PAGE_TIMEOUT_SECONDS", 180))))
    languages = str(getattr(settings, "PDF_OCR_LANGUAGES", "chi_sim+eng"))
    if not re.fullmatch(r"[A-Za-z0-9_+.-]{3,80}", languages):
        raise ProcessingError("PDF_OCR_LANGUAGES 配置无效，只允许 OCR 语言代码及加号。")
    with tempfile.TemporaryDirectory(prefix="data-ocr-") as directory:
        image_prefix = Path(directory) / "page"
        image_path = image_prefix.with_suffix(".png")
        render_command = [
            pdftoppm,
            "-f", str(page_number),
            "-l", str(page_number),
            "-r", str(dpi),
            "-scale-to", str(max_dimension),
            "-png",
            "-singlefile",
            str(source),
            str(image_prefix),
        ]
        try:
            # The executable is resolved by fixed name and no shell is involved.
            rendered = subprocess.run(  # nosec B603
                render_command,
                capture_output=True,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProcessingError(f"PDF 第 {page_number} 页渲染超过 {timeout_seconds} 秒，已停止 OCR。") from exc
        if rendered.returncode != 0 or not image_path.exists():
            detail = rendered.stderr.decode("utf-8", errors="replace").strip()[-300:]
            raise ProcessingError(f"PDF 第 {page_number} 页渲染失败：{detail or '未生成页面图像'}")

        ocr_command = [
            tesseract,
            str(image_path),
            "stdout",
            "-l", languages,
            "--oem", "1",
            "--psm", "3",
        ]
        try:
            # The executable is resolved by fixed name and no shell is involved.
            recognized = subprocess.run(  # nosec B603
                ocr_command,
                capture_output=True,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProcessingError(f"PDF 第 {page_number} 页 OCR 超过 {timeout_seconds} 秒，已停止处理。") from exc
        if recognized.returncode != 0:
            detail = recognized.stderr.decode("utf-8", errors="replace").strip()[-300:]
            raise ProcessingError(f"PDF 第 {page_number} 页 OCR 失败：{detail or '识别程序返回错误'}")
        return recognized.stdout.decode("utf-8", errors="replace").replace("\x0c", "").strip()


def extract_pdf_pages(source, progress_callback=None):
    try:
        reader = PdfReader(source)
    except Exception as exc:
        raise ProcessingError("PDF 文件结构无效或已损坏。") from exc
    if len(reader.pages) > 1000:
        raise ProcessingError("PDF 页数超过 1000 页，已拒绝处理。")
    if reader.is_encrypted:
        try:
            if reader.decrypt("") == 0:
                raise ProcessingError("暂不支持带密码的 PDF 文件。")
        except ProcessingError:
            raise
        except Exception as exc:
            raise ProcessingError("暂不支持带密码的 PDF 文件。") from exc
    _notify_progress(
        progress_callback,
        percent=5,
        stage="pdf_extract",
        detail=f"正在检查 PDF 文本层，共 {len(reader.pages)} 页",
        pdf_page_count=len(reader.pages),
    )
    pages = [page.extract_text() or "" for page in reader.pages]
    minimum_chars = int(getattr(settings, "PDF_OCR_MIN_TEXT_CHARS", 12))
    ocr_indexes = [
        index for index, page_text in enumerate(pages)
        if len(re.sub(r"\s+", "", page_text)) < minimum_chars
    ]
    if ocr_indexes:
        if not bool(getattr(settings, "PDF_OCR_ENABLED", True)):
            page_list = "、".join(str(index + 1) for index in ocr_indexes[:8])
            raise ProcessingError(f"PDF 第 {page_list} 页没有可提取文本，且本地 OCR 已关闭。")
        max_pages = int(getattr(settings, "PDF_OCR_MAX_PAGES", 300))
        if len(ocr_indexes) > max_pages:
            raise ProcessingError(
                f"PDF 需要 OCR 的页面为 {len(ocr_indexes)} 页，超过上限 {max_pages} 页，请拆分文件后处理。"
            )
        total_ocr_pages = len(ocr_indexes)
        for completed, page_index in enumerate(ocr_indexes, start=1):
            _notify_progress(
                progress_callback,
                percent=8 + int(47 * (completed - 1) / max(total_ocr_pages, 1)),
                stage="pdf_ocr",
                detail=f"本地 OCR 正在识别第 {page_index + 1}/{len(pages)} 页（OCR {completed}/{total_ocr_pages}）",
                current_page=page_index + 1,
                pdf_page_count=len(pages),
                ocr_page_count=total_ocr_pages,
            )
            pages[page_index] = _ocr_pdf_page(source, page_index + 1)
        _notify_progress(
            progress_callback,
            percent=55,
            stage="pdf_ocr",
            detail=f"本地 OCR 完成，共识别 {total_ocr_pages} 页",
            pdf_page_count=len(pages),
            ocr_page_count=total_ocr_pages,
        )

    max_characters = int(getattr(settings, "PDF_OCR_MAX_TOTAL_CHARS", 500000))
    total_characters = sum(len(page) for page in pages)
    if total_characters > max_characters:
        raise ProcessingError(
            f"PDF 提取及 OCR 文字共 {total_characters} 字符，超过上限 {max_characters}，请拆分文件后处理。"
        )
    if not any(page.strip() for page in pages):
        raise ProcessingError("PDF 本地 OCR 未识别出文字，请提高扫描清晰度或拆分后重试。")
    return pages


def _draw_wrapped_line(pdf, text, x, y, max_width, font_name, font_size, leading):
    lines = []
    current = ""
    for char in text:
        candidate = current + char
        if pdfmetrics.stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = char
    lines.append(current)
    for line in lines:
        pdf.drawString(x, y, line)
        y -= leading
    return y


def process_pdf(source, destination, transform, pages=None, progress_callback=None):
    pages = pages if pages is not None else extract_pdf_pages(source, progress_callback)
    font_name = "STSong-Light"
    try:
        pdfmetrics.registerFont(UnicodeCIDFont(font_name))
    except KeyError:
        pass
    pdf = canvas.Canvas(str(destination), pagesize=A4)
    width, height = A4
    margin = 46
    font_size = 10.5
    leading = 17
    pdf.setTitle(Path(destination).stem)
    for page_index, page_text in enumerate(pages):
        _notify_progress(
            progress_callback,
            percent=72 + int(23 * (page_index + 1) / max(len(pages), 1)),
            stage="pdf_write",
            detail=f"正在生成安全 PDF，第 {page_index + 1}/{len(pages)} 页",
            current_page=page_index + 1,
            pdf_page_count=len(pages),
        )
        if page_index:
            pdf.showPage()
        pdf.setFont(font_name, font_size)
        y = height - margin
        for source_line in transform(page_text).splitlines() or [""]:
            if y < margin + leading:
                pdf.showPage()
                pdf.setFont(font_name, font_size)
                y = height - margin
            y = _draw_wrapped_line(pdf, source_line, margin, y, width - 2 * margin, font_name, font_size, leading)
    pdf.save()


def _xml_local_name(node):
    tag = getattr(node, "tag", "")
    if not isinstance(tag, str):
        return ""
    return etree.QName(tag).localname


def process_ofd(source, destination, transform):
    if not zipfile.is_zipfile(source):
        raise ProcessingError("OFD 文件结构无效或已损坏。")
    with zipfile.ZipFile(source, "r") as input_zip, zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as output_zip:
        for info in input_zip.infolist():
            data = input_zip.read(info.filename)
            if info.filename.lower().endswith(".xml"):
                try:
                    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=False)
                    root = etree.fromstring(data, parser=parser)
                    processed = set()

                    # OFD producers often split one visible value across several TextCode
                    # elements. Join nodes within the same TextObject before recognition.
                    for text_object in root.iter():
                        if _xml_local_name(text_object) != "TextObject":
                            continue
                        text_nodes = [
                            node for node in text_object.iter()
                            if _xml_local_name(node) == "TextCode" and node.text
                        ]
                        if not text_nodes:
                            continue
                        original = "".join(node.text or "" for node in text_nodes)
                        if original:
                            _replace_text_nodes(text_nodes, transform)
                        processed.update(text_nodes)

                    # Metadata and simpler OFD variants may store content directly in
                    # ordinary XML text nodes rather than TextObject/TextCode pairs.
                    for node in root.iter():
                        if node in processed or not node.text:
                            continue
                        node.text = transform(node.text)

                    encoding = root.getroottree().docinfo.encoding or "UTF-8"
                    data = etree.tostring(
                        root,
                        encoding=encoding,
                        xml_declaration=data.lstrip().startswith(b"<?xml"),
                    )
                except (etree.XMLSyntaxError, LookupError, UnicodeError):
                    # Keep malformed or vendor-specific XML unchanged rather than risking
                    # corruption of the OFD package.
                    pass
            output_zip.writestr(info, data)


PROCESSORS = {
    ".txt": process_txt,
    ".docx": process_docx,
    ".pdf": process_pdf,
    ".xls": process_xls,
    ".ofd": process_ofd,
}


def process_file(source, destination, transform, *, pdf_pages=None, progress_callback=None):
    extension = Path(source).suffix.lower()
    if extension not in PROCESSORS:
        raise ProcessingError(f"不支持的文件格式：{extension}")
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    if extension == ".pdf":
        process_pdf(
            source,
            destination,
            transform,
            pages=pdf_pages,
            progress_callback=progress_callback,
        )
    else:
        PROCESSORS[extension](source, destination, transform)
    if not Path(destination).exists() or Path(destination).stat().st_size == 0:
        raise ProcessingError("处理结果为空，请检查源文件。")
