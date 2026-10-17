"""Fictional provider fixtures only; never makes an inference request."""
import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
from app import app


class FieldExampleTests(unittest.TestCase):
    def analyze(self, fields, language='en', raw=None):
        image = io.BytesIO()
        Image.new('RGB', (80, 100), 'white').save(image, format='PNG')
        image.seek(0)
        completion = SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content=raw if raw is not None else json.dumps({'fields': fields})))])
        with patch.dict('app.os.environ', {'OPENAI_API_KEY': 'fictional-test-key'}, clear=True), patch('app.OpenAI') as client, redirect_stdout(io.StringIO()):
            client.return_value.chat.completions.create.return_value = completion
            response = app.test_client().post('/api/analyze', data={'image': (image, 'fictional.png'), 'language': language})
        self.prompt = client.return_value.chat.completions.create.call_args.kwargs['messages'][0]['content']
        return response

    def field(self, **extra):
        return dict(label='Full name', guidance='Enter your full name.', box=[10, 20, 100, 80], **extra)

    def test_short_example_is_returned_without_changing_box(self):
        response = self.analyze([self.field(example='Alex Smith')])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['fields'][0].get('example'), 'Alex Smith')
        self.assertEqual(response.json['fields'][0]['box'], [10, 20, 90, 60])

    def test_legacy_model_response_without_example_remains_valid(self):
        response = self.analyze([self.field()])
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json['fields'][0].get('example'))

    def test_examples_are_requested_in_selected_language(self):
        response = self.analyze([self.field(example='Ana Pérez')], 'es')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['fields'][0].get('example'), 'Ana Pérez')
        self.assertIn('Spanish', self.prompt)
        self.assertIn('example', self.prompt.lower())

    def test_nontext_example_cannot_break_valid_field(self):
        response = self.analyze([self.field(example={'bad': 'value'})])
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json['fields'][0].get('example'))

    def test_excessively_long_example_is_not_displayed_unbounded(self):
        response = self.analyze([self.field(example='A' * 1000)])
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(response.json['fields'][0].get('example') or ''), 80)


if __name__ == '__main__':
    unittest.main()
