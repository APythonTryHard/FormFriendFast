"""Language picker markup and whitelist checks; never contacts a provider."""
import re
import unittest
from unittest.mock import patch
from app import app, LANGUAGES


class LanguagePickerMarkupTests(unittest.TestCase):
    def test_expanded_native_language_choices_and_simple_topbar(self):
        self.assertGreaterEqual(len(LANGUAGES), 65)
        self.assertLessEqual(len(LANGUAGES), 75)
        for code in ('am', 'so', 'ne', 'km', 'kn', 'ml', 'fi', 'ha', 'yo'):
            self.assertIn(code, LANGUAGES)
        with patch.dict('app.os.environ', {}, clear=True):
            page = app.test_client().get('/').get_data(as_text=True)
        topbar = re.search(r'<header class="topbar">(.*?)</header>', page, re.S).group(1)
        self.assertNotIn('model-pill', topbar)
        self.assertNotIn('Cloud', topbar)
        self.assertNotIn('gpt-', topbar)
        self.assertIn('for="language-select"', topbar)
        self.assertIn('data-english="Spanish"', topbar)
        self.assertIn('Español', topbar)
        self.assertNotIn('hidden', re.search(r'<select[^>]*>', topbar).group(0))
        self.assertLess(page.index('/static/app.js'), page.index('/static/language-picker.js'))
        self.assertIn('Images and selected PDF pages are sent to Anthropic for analysis.', page)


if __name__ == '__main__':
    unittest.main()
