import json
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import service_pages
import storefront


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.elements = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


class ServiceTests(unittest.TestCase):
    def test_every_menu_service_has_a_local_document(self):
        entries = [e for e in storefront.ROUTES.values() if e['kind'] == 'services']
        self.assertEqual(len(entries), 127)
        for entry in entries:
            with self.subTest(source=entry['item']['source']):
                page = service_pages.page_for(entry['item']['source'])
                self.assertIsNotNone(page)
                self.assertTrue((ROOT / 'static/assets/services' / page['file']).is_file())
                self.assertIn('iframe', service_pages.render(entry['item']['source'], entry['item']['label']))

    def test_documents_have_local_assets_and_no_source_execution(self):
        pages = json.loads((ROOT / 'data/service-pages.json').read_text(encoding='utf-8'))
        self.assertEqual(len(pages), 123)
        for page in pages.values():
            with self.subTest(page=page['file']):
                document = Document((ROOT / 'static/assets/services' / page['file']).read_text(encoding='utf-8'))
                for tag, attrs in document.elements:
                    self.assertFalse(any(key.startswith('on') for key in attrs))
                    self.assertNotIn(tag, {'iframe', 'object', 'embed'})
                    if tag == 'script':
                        self.assertEqual(attrs.get('src'), '/frontend/service-document.js')
                    if tag == 'form':
                        self.assertNotIn('action', attrs)
                    if tag in {'img', 'script', 'link'}:
                        url = attrs.get('src') or attrs.get('href', '')
                        self.assertTrue(url.startswith(('/', 'data:')), url)
                        if url.startswith('/'):
                            self.assertTrue((ROOT / url.lstrip('/')).is_file(), url)


if __name__ == '__main__':
    unittest.main()
