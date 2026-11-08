import io
import tempfile
import unittest
from pathlib import Path
import sys

from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app


class StubDetector:
    model = None

    def predict(self, image):
        return image.copy(), [{'class_name': 'bicycle', 'confidence': .9, 'box': [1, 1, 20, 20]}]


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app({'TESTING': True, 'DATA_DIR': self.temp.name}, StubDetector())
        self.client = self.app.test_client()
        self.assertEqual(self.client.get('/').status_code, 200)
        with self.client.session_transaction() as session:
            self.headers = {'X-CSRF-Token': session['csrf']}

    def tearDown(self):
        self.temp.cleanup()

    def test_vehicle_crud_and_literal_search(self):
        record = {'plate': "DEMO-' OR 1=1--", 'vehicle_type': '自行车', 'note': '<script>test</script>'}
        response = self.client.post('/api/vehicles', json=record, headers=self.headers)
        self.assertEqual(response.status_code, 201)
        identity = response.json['id']
        self.assertEqual(self.client.post('/api/vehicles', json=record, headers=self.headers).status_code, 409)
        found = self.client.get('/api/vehicles', query_string={'q': "' OR 1=1--"}).json['records']
        self.assertEqual(len(found), 1)
        record['note'] = 'updated'
        self.assertEqual(self.client.put(f'/api/vehicles/{identity}', json=record, headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get('/api/vehicles').json['records'][0]['note'], 'updated')
        self.assertEqual(self.client.delete(f'/api/vehicles/{identity}', headers=self.headers).status_code, 204)
        self.assertEqual(self.client.get('/api/vehicles').json['records'], [])
        self.assertEqual(self.client.delete(f'/api/vehicles/{identity}', headers=self.headers).status_code, 404)

    def test_invalid_input_and_csrf(self):
        self.assertEqual(self.client.post('/api/vehicles', json={}).status_code, 403)
        for body in [{}, {'plate': 12}, {'plate': 'x' * 33, 'vehicle_type': 'bicycle'}, []]:
            self.assertEqual(self.client.post('/api/vehicles', json=body, headers=self.headers).status_code, 400)
        self.assertEqual(self.client.get('/api/vehicles?page=invalid').status_code, 400)
        self.assertEqual(self.client.get('/images/../../app.py').status_code, 404)

    def test_image_detection_persistence_and_deletion(self):
        image = io.BytesIO()
        Image.new('RGB', (32, 32), 'white').save(image, format='PNG')
        image.seek(0)
        response = self.client.post('/api/detect', data={'image': (image, 'image.png')}, headers=self.headers)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json['count'], 1)
        with self.client.get(response.json['image_url']) as result_image:
            self.assertEqual(result_image.status_code, 200)
        self.assertEqual(len(self.client.get('/api/detections').json['records']), 1)
        identity = response.json['id']
        self.assertEqual(self.client.delete(f'/api/detections/{identity}', headers=self.headers).status_code, 204)
        self.assertEqual(self.client.get(response.json['image_url']).status_code, 404)
        self.assertEqual(self.client.get('/api/detections').json['records'], [])

    def test_bad_images_and_size_limit(self):
        self.assertEqual(self.client.post('/api/detect', headers=self.headers).status_code, 400)
        self.assertEqual(self.client.post('/api/detect', data={'image': (io.BytesIO(b'not image'), 'fake.png')}, headers=self.headers).status_code, 400)
        self.assertEqual(self.client.post('/api/detect', data={'image': (io.BytesIO(b'x' * (8 * 1024 * 1024)), 'big.png')}, headers=self.headers).status_code, 413)


if __name__ == '__main__':
    unittest.main()
