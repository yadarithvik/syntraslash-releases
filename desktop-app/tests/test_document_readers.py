from pathlib import Path
import tempfile
import unittest
import zipfile

from pypdf import PdfWriter
import document_readers


class DocumentTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()

    def test_pdf_pages_and_scan_warning(self):
        file=self.root/'scan.pdf';writer=PdfWriter();writer.add_blank_page(width=100,height=100)
        with file.open('wb') as stream:writer.write(stream)
        result=document_readers.read_document(file)
        self.assertEqual(result['pages'],1);self.assertIn('no embedded text',result['warning'])
        with self.assertRaises(ValueError):document_readers.read_document(file,2)

    def test_docx_paragraphs(self):
        file=self.root/'notes.docx'
        with zipfile.ZipFile(file,'w') as archive:
            archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Project Lotus 8274</w:t></w:r></w:p></w:body></w:document>')
        self.assertIn('Lotus 8274',document_readers.read_document(file)['output'])

    def test_csv_quoting_and_row_bound(self):
        file=self.root/'rows.csv';file.write_text('name,value\n"A, B",731\n'+'C,1\n'*100)
        result=document_readers.read_document(file)
        self.assertEqual(result['rows'][1],['A, B','731']);self.assertEqual(len(result['rows']),50)

    def test_text_is_bounded_and_binary_rejected(self):
        file=self.root/'large.txt';file.write_text('x'*15000)
        self.assertEqual(len(document_readers.read_document(file)['output']),12000)
        file.write_bytes(b'bad\0binary')
        with self.assertRaises(ValueError):document_readers.read_document(file)

    def test_file_byte_limit(self):
        file=self.root/'large.pdf'
        with file.open('wb') as stream:stream.truncate(17*1024*1024)
        with self.assertRaises(ValueError):document_readers.read_document(file)


if __name__=='__main__':unittest.main()
