import hashlib
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from server import create_app

class APITest(unittest.TestCase):
    def test_contract_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'test.sqlite')
            with TestClient(create_app(path)) as client:
                self.assertEqual(client.get('/api/health').status_code, 200)
                self.assertEqual(client.get('/api/profile').status_code, 401)
                self.assertEqual(client.get('/api/health', headers={'Origin': 'https://evil.example'}).status_code, 403)
                account = {'email': 'alex@example.com', 'password': 'a-secure-password'}
                register = client.post('/api/auth/register', json=account)
                self.assertEqual(register.status_code, 201)
                self.assertNotIn('password', register.json()['user'])
                self.assertIn('HttpOnly', register.headers['set-cookie'])
                self.assertEqual(client.post('/api/auth/register', json=account).status_code, 409)
                self.assertEqual(client.post('/api/auth/login', json={**account, 'password': 'wrong-password'}).status_code, 401)
                self.assertEqual(client.patch('/api/profile', json={'firstName': 'Alex', 'dailyStepGoal': 8000}).status_code, 200)
                self.assertEqual(client.patch('/api/profile', json={'dateOfBirth': '2020-02-31'}).status_code, 400)
                device_body = {'identifier': 'stm32', 'name': 'Tracker'}
                device = client.post('/api/devices', json=device_body).json()['device']
                self.assertEqual(client.post('/api/devices', json=device_body).json()['device']['id'], device['id'])
                endpoint = f"/api/devices/{device['id']}/measurements"
                sample = {'sampleId': 'boot:1', 'recordedAt': '2026-01-01T12:00:00Z', 'steps': 50, 'heartRate': 75}
                self.assertEqual(client.post(endpoint, json={'measurements': [sample, {**sample, 'steps': -1}]}).status_code, 400)
                self.assertEqual(client.post(endpoint, json={'measurements': [sample]}).json(), {'inserted': 1, 'duplicates': 0})
                self.assertEqual(client.post(endpoint, json={'measurements': [sample]}).json(), {'inserted': 0, 'duplicates': 1})
                bounds = '?from=2026-01-01T00:00:00Z&to=2026-01-02T00:00:00Z'
                self.assertEqual(client.get('/api/activity/summary'+bounds).json()['steps'], 50)
                self.assertEqual(client.get('/api/activity/history'+bounds).json()['days'][0]['averageHeartRate'], 75)
                self.assertEqual(client.post('/api/auth/logout', json={}).status_code, 200)
                self.assertEqual(client.get('/api/auth/me').status_code, 401)
            with closing(sqlite3.connect(path)) as db, db:
                salt = '0123456789abcdef0123456789abcdef'
                digest = hashlib.scrypt(b'node-password-123', salt=salt.encode(), n=16384, r=8, p=1, dklen=64).hex()
                db.execute('UPDATE users SET password=?', (salt + ':' + digest,))
            with TestClient(create_app(path)) as client:
                self.assertEqual(client.post('/api/auth/login', json={'email': 'alex@example.com', 'password': 'node-password-123'}).status_code, 200)
                self.assertEqual(client.get('/api/profile').json()['profile']['firstName'], 'Alex')
                self.assertEqual(client.get('/api/activity/summary'+bounds).json()['steps'], 50)
                self.assertEqual(client.post('/api/auth/logout', content='{}').status_code, 415)
                self.assertEqual(client.post('/api/auth/logout', content='{', headers={'content-type': 'application/json'}).status_code, 400)
    def test_monitoring_requires_explicit_access_and_revocation(self):
        with tempfile.TemporaryDirectory() as directory:
            with TestClient(create_app(str(Path(directory) / 'monitor.sqlite'))) as user:
                account = user.post('/api/auth/register', json={'email': 'user@example.com', 'password': 'a-secure-password', 'role': 'user'}).json()['user']
                self.assertEqual(account['role'], 'user')
                # Multiple browser sessions share this application's database.
                from fastapi.testclient import TestClient as Client
                admin = Client(user.app)
                stranger = Client(user.app)
                if True:
                    result = admin.post('/api/auth/register', json={'email': 'admin@example.com', 'password': 'a-secure-password', 'role': 'admin'})
                    self.assertEqual(result.json()['user']['role'], 'admin')
                    stranger.post('/api/auth/register', json={'email': 'other@example.com', 'password': 'a-secure-password', 'role': 'admin'})
                    self.assertEqual(user.get('/api/monitoring/users').status_code, 403)
                    self.assertEqual(admin.get('/api/monitoring/users').json()['users'], [])
                    payload = {'userId': account['id'], 'activity': 'Walking', 'confidence': 0.9, 'deviceTime': 123}
                    self.assertEqual(user.post('/api/predictions', json={**payload, 'userId': 'other'}).status_code, 403)
                    self.assertEqual(admin.post('/api/predictions', json=payload).status_code, 403)
                    self.assertEqual(user.post('/api/predictions', json=payload).status_code, 200)
                    grant = user.post('/api/monitoring/grants', json={'email': 'admin@example.com'})
                    self.assertEqual(grant.status_code, 200)
                    self.assertEqual(admin.get('/api/monitoring/users').json()['users'][0]['activity'], 'Walking')
                    self.assertEqual(stranger.get('/api/monitoring/users').json()['users'], [])
                    self.assertEqual(user.post('/api/predictions', json={**payload, 'activity': 'Lying'}).status_code, 200)
                    self.assertEqual(admin.get('/api/monitoring/users').json()['users'][0]['activity'], 'Lying')
                    self.assertEqual(user.delete('/api/monitoring/grants', params={'adminId': grant.json()['admin']['id']}).status_code, 200)
                    self.assertEqual(admin.get('/api/monitoring/users').json()['users'], [])


if __name__ == '__main__':
    unittest.main()
