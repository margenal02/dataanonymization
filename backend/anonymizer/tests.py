import io
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

import xlrd
import xlwt
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from .file_processors import process_file
from .models import AnonymizationTask
from .recognizer import MappingBuilder, restore_text


class MappingBuilderTests(TestCase):
    def test_detects_tobacco_entities_and_restores_exactly(self):
        source = "单位：中国烟草总公司\n联系人：张三\n电话：13800138000"
        builder = MappingBuilder("abcd1234")
        anonymized = builder.anonymize(source)
        self.assertNotIn("中国烟草总公司", anonymized)
        self.assertNotIn("张三", anonymized)
        self.assertNotIn("13800138000", anonymized)
        self.assertIn("【单位_ABCD_001】", anonymized)
        self.assertEqual(restore_text(anonymized, builder.export()), source)

    def test_detects_entities_in_real_tobacco_document_language(self):
        source = (
            "云南中烟工业有限责任公司与红云红河烟草（集团）有限责任公司签订采购合同，"
            "项目负责人王建国，李娜负责复核，送货至云南省昆明市五华区红锦路123号，"
            "联系电话0871-63568888。"
        )
        builder = MappingBuilder("real1234")
        anonymized = builder.anonymize(source)

        for sensitive_value in (
            "云南中烟工业有限责任公司",
            "红云红河烟草（集团）有限责任公司",
            "王建国",
            "李娜",
            "云南省昆明市五华区红锦路123号",
            "0871-63568888",
        ):
            self.assertNotIn(sensitive_value, anonymized)
        self.assertEqual(builder.counts(), {"单位": 2, "人名": 2, "地址": 1, "电话": 1})
        self.assertEqual(restore_text(anonymized, builder.export()), source)

    def test_detects_names_on_standalone_table_like_lines_and_name_lists(self):
        source = "人员名单：张三、李四、王五\n\n欧阳娜\n部门：财务部"
        builder = MappingBuilder("table123")
        anonymized = builder.anonymize(source)

        for sensitive_value in ("张三", "李四", "王五", "欧阳娜", "财务部"):
            self.assertNotIn(sensitive_value, anonymized)
        self.assertEqual(builder.counts(), {"人名": 4, "单位": 1})
        self.assertEqual(restore_text(anonymized, builder.export()), source)

    def test_detects_pdf_style_spaces_inside_entities(self):
        source = "单 位：中 国 烟 草 总 公 司\n联 系 人：张 三\n138 0013 8000"
        builder = MappingBuilder("space123")
        anonymized = builder.anonymize(source)

        self.assertNotIn("中 国 烟 草 总 公 司", anonymized)
        self.assertNotIn("张 三", anonymized)
        self.assertNotIn("138 0013 8000", anonymized)
        self.assertEqual(builder.counts(), {"单位": 1, "人名": 1, "电话": 1})
        self.assertEqual(restore_text(anonymized, builder.export()), source)

    def test_does_not_treat_common_status_words_as_people(self):
        source = "审核状态：合格\n审批意见：同意\n项目\n方案\n申请\n费用\n单价\n说明\n文件\n安全\n管理"
        builder = MappingBuilder("safe1234", ["person"])
        self.assertEqual(builder.anonymize(source), source)
        self.assertEqual(builder.counts(), {})


class FileProcessorTests(TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.source_text = "单位：中国烟草总公司\n联系人：张三\n电话：13800138000"

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def _roundtrip(self, source, extension):
        builder = MappingBuilder("1234abcd")
        anonymized = self.directory / f"anonymous{extension}"
        restored = self.directory / f"restored{extension}"
        process_file(source, anonymized, builder.anonymize)
        self.assertTrue(anonymized.exists())
        process_file(anonymized, restored, lambda text: restore_text(text, builder.export()))
        self.assertTrue(restored.exists())
        return anonymized, restored

    def test_txt_roundtrip(self):
        source = self.directory / "sample.txt"
        source.write_text(self.source_text, encoding="utf-8")
        _, restored = self._roundtrip(source, ".txt")
        self.assertIn("中国烟草总公司", restored.read_text(encoding="utf-8"))

    def test_docx_roundtrip(self):
        source = self.directory / "sample.docx"
        document = Document()
        document.add_paragraph(self.source_text)
        document.save(source)
        anonymized, restored = self._roundtrip(source, ".docx")
        self.assertNotIn("张三", "\n".join(p.text for p in Document(anonymized).paragraphs))
        self.assertIn("张三", "\n".join(p.text for p in Document(restored).paragraphs))

    def test_docx_text_box_content_is_processed(self):
        source = self.directory / "textbox.docx"
        document = Document()
        text_box = parse_xml(
            f'<w:txbxContent {nsdecls("w")}>'
            '<w:p><w:r><w:t>项目负责人王建国，单位：中国烟草总公司</w:t></w:r></w:p>'
            '</w:txbxContent>'
        )
        document._element.body.append(text_box)
        document.save(source)

        anonymized, restored = self._roundtrip(source, ".docx")
        anonymized_text = "".join(
            node.text or "" for node in Document(anonymized)._element.xpath(".//w:txbxContent//w:t")
        )
        restored_text = "".join(
            node.text or "" for node in Document(restored)._element.xpath(".//w:txbxContent//w:t")
        )
        self.assertNotIn("王建国", anonymized_text)
        self.assertNotIn("中国烟草总公司", anonymized_text)
        self.assertIn("王建国", restored_text)
        self.assertIn("中国烟草总公司", restored_text)

    def test_xls_roundtrip(self):
        source = self.directory / "sample.xls"
        book = xlwt.Workbook()
        sheet = book.add_sheet("数据")
        sheet.write(0, 0, self.source_text)
        book.save(source)
        anonymized, restored = self._roundtrip(source, ".xls")
        self.assertNotIn("张三", xlrd.open_workbook(anonymized).sheet_by_index(0).cell_value(0, 0))
        self.assertIn("张三", xlrd.open_workbook(restored).sheet_by_index(0).cell_value(0, 0))

    def test_ofd_xml_roundtrip(self):
        source = self.directory / "sample.ofd"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("OFD.xml", f"<ofd:OFD xmlns:ofd='x'><ofd:Text>{self.source_text}</ofd:Text></ofd:OFD>")
        anonymized, restored = self._roundtrip(source, ".ofd")
        with zipfile.ZipFile(anonymized) as archive:
            self.assertNotIn("张三", archive.read("OFD.xml").decode())
        with zipfile.ZipFile(restored) as archive:
            self.assertIn("张三", archive.read("OFD.xml").decode())

    def test_ofd_split_text_code_nodes_are_processed(self):
        source = self.directory / "split-text.ofd"
        xml = (
            "<ofd:OFD xmlns:ofd='urn:ofd:test'><!-- vendor comment --><ofd:TextObject>"
            "<ofd:TextCode>联</ofd:TextCode><ofd:TextCode>系人：</ofd:TextCode>"
            "<ofd:TextCode>张</ofd:TextCode><ofd:TextCode>三</ofd:TextCode>"
            "</ofd:TextObject></ofd:OFD>"
        )
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("OFD.xml", xml)

        anonymized, restored = self._roundtrip(source, ".ofd")
        with zipfile.ZipFile(anonymized) as archive:
            anonymized_xml = archive.read("OFD.xml").decode()
        with zipfile.ZipFile(restored) as archive:
            restored_xml = archive.read("OFD.xml").decode()
        self.assertNotIn("张三", anonymized_xml)
        self.assertIn("【人名_1234_001】", anonymized_xml)
        self.assertIn("张三", restored_xml)

    def test_pdf_roundtrip(self):
        source = self.directory / "sample.pdf"
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        pdf = canvas.Canvas(str(source), pagesize=A4)
        pdf.setFont("STSong-Light", 12)
        pdf.drawString(50, 790, self.source_text.replace("\n", "  "))
        pdf.save()
        anonymized, restored = self._roundtrip(source, ".pdf")
        self.assertNotIn("张三", "".join(page.extract_text() or "" for page in __import__('pypdf').PdfReader(anonymized).pages))
        self.assertIn("张三", "".join(page.extract_text() or "" for page in __import__('pypdf').PdfReader(restored).pages))


class TaskApiTests(TestCase):
    def setUp(self):
        self.media_directory = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media_directory, MAPPING_ENCRYPTION_KEY="test-mapping-key")
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media_directory, ignore_errors=True)

    def test_txt_anonymize_and_restore_api(self):
        source = "单位：中国烟草总公司\n联系人：张三\n电话：13800138000"
        upload = SimpleUploadedFile("项目清单.txt", source.encode("utf-8"), content_type="text/plain")
        response = self.client.post("/api/tasks/", {
            "file": upload,
            "categories": json.dumps(["organization", "person", "phone"]),
            "custom_entities": "",
        })
        self.assertEqual(response.status_code, 201, response.content)
        task = response.json()
        self.assertEqual(task["task_name"], "项目清单")
        self.assertEqual(task["stored_files"], {"original": True, "anonymized": True, "restore_input": False, "restored": False})
        download = self.client.get(task["anonymized_download_url"])
        anonymized = b"".join(download.streaming_content)
        self.assertNotIn("张三".encode(), anonymized)

        restore_upload = SimpleUploadedFile("AI处理稿.txt", anonymized + "\nAI补充内容".encode("utf-8"), content_type="text/plain")
        response = self.client.post(f"/api/tasks/{task['id']}/restore/", {"file": restore_upload})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["stored_files"], {"original": True, "anonymized": True, "restore_input": True, "restored": True})
        restored_download = self.client.get(response.json()["restored_download_url"])
        restored = b"".join(restored_download.streaming_content).decode("utf-8")
        self.assertIn("中国烟草总公司", restored)
        self.assertIn("张三", restored)
        self.assertIn("AI补充内容", restored)

    def test_api_returns_counts_for_realistic_unlabeled_content(self):
        source = (
            "云南中烟工业有限责任公司与红云红河烟草（集团）有限责任公司签订合同，"
            "项目负责人王建国，李娜负责复核，联系电话0871-63568888。"
        )
        upload = SimpleUploadedFile("真实公文语句.txt", source.encode("utf-8"), content_type="text/plain")
        response = self.client.post("/api/tasks/", {
            "file": upload,
            "categories": json.dumps(["organization", "person", "phone"]),
            "custom_entities": "",
        })

        self.assertEqual(response.status_code, 201, response.content)
        task = response.json()
        self.assertEqual(task["entity_counts"], {"单位": 2, "人名": 2, "电话": 1})
        download = self.client.get(task["anonymized_download_url"])
        anonymized = b"".join(download.streaming_content).decode("utf-8")
        for sensitive_value in ("云南中烟工业有限责任公司", "红云红河烟草（集团）有限责任公司", "王建国", "李娜"):
            self.assertNotIn(sensitive_value, anonymized)

    def test_delete_requires_confirmation_and_removes_files(self):
        upload = SimpleUploadedFile("采购方案_匿名.txt", "联系人：张三".encode("utf-8"), content_type="text/plain")
        response = self.client.post("/api/tasks/", {"file": upload, "categories": json.dumps(["person"])})
        self.assertEqual(response.status_code, 201, response.content)
        task_data = response.json()
        task = AnonymizationTask.objects.get(id=task_data["id"])
        task_directory = Path(self.media_directory) / "tasks" / str(task.id)
        self.assertEqual(task.task_name, "采购方案")
        self.assertTrue(task_directory.exists())

        response = self.client.delete(f"/api/tasks/{task.id}/")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(AnonymizationTask.objects.filter(id=task.id).exists())

        response = self.client.delete(f"/api/tasks/{task.id}/", HTTP_X_TASK_DELETE_CONFIRM=str(task.id))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(AnonymizationTask.objects.filter(id=task.id).exists())
        self.assertFalse(task_directory.exists())

    def test_rejects_spoofed_pdf(self):
        upload = SimpleUploadedFile("伪造.pdf", b"not really a PDF", content_type="application/pdf")
        response = self.client.post("/api/tasks/", {"file": upload})
        self.assertEqual(response.status_code, 400)
        self.assertIn("PDF", response.json()["detail"])

    def test_rejects_unsafe_ofd_archive_path(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("OFD.xml", "<OFD/>")
            archive.writestr("../escape.xml", "bad")
        upload = SimpleUploadedFile("恶意.ofd", buffer.getvalue(), content_type="application/octet-stream")
        response = self.client.post("/api/tasks/", {"file": upload})
        self.assertEqual(response.status_code, 400)
        self.assertIn("不安全", response.json()["detail"])
