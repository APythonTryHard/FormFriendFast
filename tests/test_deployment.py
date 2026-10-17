"""Deployment checks that never call a cloud provider."""
import unittest

from app import app


class DeploymentTests(unittest.TestCase):
    def test_health_check_is_public_and_does_not_require_api_key(self):
        response = app.test_client().get('/healthz')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {'status': 'ok'})
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_debug_is_disabled_by_default(self):
        self.assertFalse(app.debug)
