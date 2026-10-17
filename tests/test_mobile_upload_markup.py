"""Upload choice markup checks; never contacts a provider."""
import re
import unittest

from app import app

FILE_ACCEPT = ("application/pdf,.pdf,image/*,.heic,.heif,.avif,.bmp,.tif,.tiff,.gif,.ico,"
               ".jp2,.jxl,.psd,.tga,.ppm,.pgm,.pbm,.qoi")


class MobileUploadMarkupTests(unittest.TestCase):
    def setUp(self):
        self.page = app.test_client().get('/').get_data(as_text=True)

    def tag(self, element_id):
        match = re.search(rf'<[a-z]+[^>]*\bid="{element_id}"[^>]*>', self.page)
        self.assertIsNotNone(match, element_id)
        return match.group(0)

    def test_file_picker_keeps_existing_types(self):
        self.assertIn(f'accept="{FILE_ACCEPT}"', self.tag('image-input'))

    def test_photo_picker_allows_library_or_camera(self):
        photo = self.tag('photo-input')
        self.assertIn('type="file"', photo)
        self.assertIn('accept="image/*"', photo)
        self.assertNotIn('capture', photo, 'Forcing capture would hide the photo library')
        self.assertNotIn('multiple', photo)

    def test_drop_zone_is_keyboard_accessible(self):
        drop_zone = self.tag('drop-zone')
        self.assertIn('for="image-input"', drop_zone)
        self.assertIn('tabindex="0"', drop_zone)
        self.assertIn('role="button"', drop_zone)

    def test_choice_sheet_has_labelled_actions(self):
        sheet = re.search(r'<dialog[^>]*id="upload-sheet"[^>]*>(.*?)</dialog>', self.page, re.S)
        self.assertIsNotNone(sheet)
        self.assertRegex(sheet.group(0), r'aria-label(ledby)?="')
        body = sheet.group(1)
        self.assertIn('data-upload-choice="photo"', body)
        self.assertIn('data-upload-choice="file"', body)
        self.assertIn('data-upload-cancel', body)
        self.assertEqual(len(re.findall(r'<button[^>]*type="button"', body)), 3)

    def test_scripts_load_in_order(self):
        self.assertLess(self.page.index('/static/app.js'), self.page.index('/static/upload-choice.js'))


if __name__ == '__main__':
    unittest.main()
