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
