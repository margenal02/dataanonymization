import zipfile
import re
from difflib import SequenceMatcher
from pathlib import Path, PurePosixPath

import xlrd
from charset_normalizer import from_bytes
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


def _extract_pdf_text(source):
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
    pages = [page.extract_text() or "" for page in reader.pages]
    if not any(page.strip() for page in pages):
        raise ProcessingError("PDF 未检测到可提取文本，扫描件请先进行 OCR。")
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


def process_pdf(source, destination, transform):
    pages = _extract_pdf_text(source)
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


def process_file(source, destination, transform):
    extension = Path(source).suffix.lower()
    if extension not in PROCESSORS:
        raise ProcessingError(f"不支持的文件格式：{extension}")
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    PROCESSORS[extension](source, destination, transform)
    if not Path(destination).exists() or Path(destination).stat().st_size == 0:
        raise ProcessingError("处理结果为空，请检查源文件。")
