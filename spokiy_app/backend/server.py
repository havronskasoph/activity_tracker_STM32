import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response


def now():
    return datetime.now(timezone.utc)


def iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


class APIError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def fail(status, message):
    raise APIError(status, message)


def text(value, name, maximum=200):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        fail(400, f'Invalid {name}')
    return value.strip()


def timestamp(value):
    if not isinstance(value, str) or not re.match(r'^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$', value):
        fail(400, 'Timestamp must be ISO 8601 with timezone')
    try:
        return iso(datetime.fromisoformat(value.replace('Z', '+00:00')))
    except ValueError:
        fail(400, 'Timestamp must be ISO 8601 with timezone')


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def create_app(database_path=None, origin=None, secure=None):
    database_path = database_path or os.getenv('DATABASE_PATH', './data/spokiy.sqlite')
    origin = origin or os.getenv('FRONTEND_ORIGIN', 'http://localhost:8443')
    secure = secure if secure is not None else os.getenv('COOKIE_SECURE') == 'true'
    if database_path != ':memory:':
        Path(database_path).resolve().parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(database_path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript('''PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT NOT NULL UNIQUE,password TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS profiles(user_id TEXT PRIMARY KEY REFERENCES users(id),data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),expires INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),identifier TEXT NOT NULL,name TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(user_id,identifier));
    CREATE TABLE IF NOT EXISTS measurements(device_id TEXT NOT NULL REFERENCES devices(id),sample_id TEXT NOT NULL,recorded_at TEXT NOT NULL,steps INTEGER NOT NULL,heart_rate REAL,battery REAL,PRIMARY KEY(device_id,sample_id));
    CREATE INDEX IF NOT EXISTS measurements_time ON measurements(device_id,recorded_at);''')
    if 'role' not in {row['name'] for row in db.execute('PRAGMA table_info(users)')}:
        db.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS monitoring_grants(user_id TEXT NOT NULL REFERENCES users(id), admin_id TEXT NOT NULL REFERENCES users(id), PRIMARY KEY(user_id, admin_id));
    CREATE TABLE IF NOT EXISTS live_predictions(user_id TEXT PRIMARY KEY REFERENCES users(id), activity TEXT NOT NULL, confidence REAL NOT NULL, device_time INTEGER NOT NULL, received_at TEXT NOT NULL);
    """)
    limits = {}

    @asynccontextmanager
    async def lifespan(app):
        yield
        db.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def dispatch(request: Request, call_next):
        headers = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}
        request_origin = request.headers.get('origin')
        if request_origin == origin:
            headers.update({'Access-Control-Allow-Origin': origin, 'Access-Control-Allow-Credentials': 'true', 'Vary': 'Origin'})
        try:
            if request_origin and request_origin != origin:
                fail(403, 'Origin not allowed')
            if request.method == 'OPTIONS':
                response = Response(status_code=204, headers={'Access-Control-Allow-Methods': 'GET,POST,PATCH,OPTIONS', 'Access-Control-Allow-Headers': 'Content-Type'})
            else:
                if request.method in ('POST', 'PATCH'):
                    if not request.headers.get('content-type', '').startswith('application/json'):
                        fail(415, 'Use application/json')
                    data = bytearray()
                    async for chunk in request.stream():
                        data.extend(chunk)
                        if len(data) > 262144:
                            fail(413, 'Request too large')
                    try:
                        body = json.loads(data)
                    except (ValueError, UnicodeDecodeError):
                        fail(400, 'Invalid JSON')
                    if not isinstance(body, dict):
                        fail(400, 'Expected JSON object')
                    request.state.body = body
                response = await call_next(request)
        except APIError as error:
            response = JSONResponse({'error': error.message}, status_code=error.status)
        for key, value in headers.items():
            response.headers[key] = value
        return response

    @app.exception_handler(APIError)
    async def api_error(request, error):
        return JSONResponse({'error': error.message}, status_code=error.status)

    @app.exception_handler(404)
    async def not_found(request, error):
        return JSONResponse({'error': 'Endpoint not found'}, status_code=404)

    def user_for(request):
        token = request.cookies.get('spokiy_session', '')
        user = db.execute('SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>?', (hashlib.sha256(token.encode()).hexdigest(), int(time.time() * 1000))).fetchone()
        if not user:
            fail(401, 'Sign in required')
        return user

    def public(user):
        return {'id': user['id'], 'email': user['email'], 'createdAt': user['created_at'], 'role': user['role']}

    @app.get('/api/health')
    async def health():
        return {'status': 'ok'}

    @app.post('/api/auth/{action}')
    async def auth(action: str, request: Request):
        body = request.state.body
        if action in ('register', 'login'):
            current = time.time()
            limits_copy = list(limits.items())
            for key, (_, until) in limits_copy:
                if until < current:
                    del limits[key]
            key = request.client.host if request.client else ''
            count, until = limits.get(key, (0, current + 60))
            limits[key] = (count + 1, until)
            if count >= 20:
                fail(429, 'Too many attempts; retry after one minute')
            email = text(body.get('email'), 'email', 254).lower()
            if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
                fail(400, 'Invalid email')
            password = body.get('password')
            if not isinstance(password, str) or not 12 <= len(password) <= 128:
                fail(400, 'Password must contain 12–128 characters')
            user = db.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
            if action == 'register':
                if user:
                    fail(409, 'Email already registered')
                role = body.get('role', 'user')
                if role not in ('user', 'admin'):
                    fail(400, 'Invalid role')
                salt = secrets.token_hex(16)
                digest = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=64).hex()
                uid, created = str(uuid.uuid4()), iso(now())
                try:
                    with db:
                        db.execute('INSERT INTO users(id,email,password,created_at,role) VALUES(?,?,?,?,?)', (uid, email, f'{salt}:{digest}', created, role))
                        db.execute('INSERT INTO profiles VALUES(?,?)', (uid, json.dumps({'firstName': '', 'lastName': '', 'dailyStepGoal': 10000})))
                except sqlite3.IntegrityError:
                    fail(409, 'Email already registered')
                user = db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
            else:
                salt, digest = (user['password'] if user else '0'*32 + ':' + '0'*128).split(':')
                actual = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=64).hex()
                if not hmac.compare_digest(actual, digest) or not user:
                    fail(401, 'Invalid email or password')
            token = secrets.token_hex(32)
            millis = int(time.time() * 1000)
            with db:
                db.execute('DELETE FROM sessions WHERE expires<=?', (millis,))
                db.execute('INSERT INTO sessions VALUES(?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), user['id'], millis + 7*86400000))
            response = JSONResponse({'user': public(user)}, status_code=201 if action == 'register' else 200)
            response.set_cookie('spokiy_session', token, max_age=7*86400, httponly=True, samesite='lax', secure=secure, path='/')
            return response
        user_for(request)
        if action == 'logout':
            with db:
                db.execute('DELETE FROM sessions WHERE token=?', (hashlib.sha256(request.cookies.get('spokiy_session', '').encode()).hexdigest(),))
            response = JSONResponse({'ok': True})
            response.set_cookie('spokiy_session', '', max_age=0, httponly=True, samesite='lax', secure=secure, path='/')
            return response
        fail(404, 'Endpoint not found')

    @app.get('/api/auth/me')
    async def me(request: Request):
        return {'user': public(user_for(request))}

    @app.api_route('/api/profile', methods=['GET', 'PATCH'])
    async def profile(request: Request):
        user = user_for(request)
        result = json.loads(db.execute('SELECT data FROM profiles WHERE user_id=?', (user['id'],)).fetchone()['data'])
        if request.method == 'PATCH':
            strings = ('firstName', 'lastName', 'phone', 'dateOfBirth', 'location')
            numbers = {'heightCm': (30, 300), 'weightKg': (1, 700), 'dailyStepGoal': (1, 1000000)}
            for key, value in request.state.body.items():
                if key in strings:
                    if not isinstance(value, str) or len(value) > 200:
                        fail(400, f'Invalid {key}')
                    if key == 'dateOfBirth' and value:
                        try:
                            valid = bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)) and date.fromisoformat(value) <= now().date()
                        except ValueError:
                            valid = False
                        if not valid:
                            fail(400, 'Invalid dateOfBirth')
                elif key in numbers:
                    low, high = numbers[key]
                    if not number(value) or not low <= value <= high or (key == 'dailyStepGoal' and value % 1):
                        fail(400, f'Invalid {key}')
                else:
                    fail(400, f'Unknown profile field: {key}')
                result[key] = value
            with db:
                db.execute('UPDATE profiles SET data=? WHERE user_id=?', (json.dumps(result), user['id']))
        return {'profile': result, 'email': user['email']}

    @app.api_route('/api/devices', methods=['GET', 'POST'])
    async def devices(request: Request):
        user = user_for(request)
        if request.method == 'GET':
            return {'devices': [dict(row) for row in db.execute('SELECT id,identifier,name,created_at FROM devices WHERE user_id=?', (user['id'],))]}
        identifier = text(request.state.body.get('identifier'), 'identifier')
        name = text(request.state.body.get('name'), 'name')
        existing = db.execute('SELECT * FROM devices WHERE user_id=? AND identifier=?', (user['id'], identifier)).fetchone()
        if existing:
            return {'device': dict(existing)}
        device = {'id': str(uuid.uuid4()), 'identifier': identifier, 'name': name, 'created_at': iso(now())}
        with db:
            db.execute('INSERT INTO devices VALUES(?,?,?,?,?)', (device['id'], user['id'], identifier, name, device['created_at']))
        return JSONResponse({'device': device}, status_code=201)

    @app.post('/api/devices/{device_id}/measurements')
    async def measurements(device_id: str, request: Request):
        user = user_for(request)
        if not db.execute('SELECT id FROM devices WHERE id=? AND user_id=?', (device_id, user['id'])).fetchone():
            fail(404, 'Device not found')
        items = request.state.body.get('measurements')
        if not isinstance(items, list) or not 1 <= len(items) <= 500:
            fail(400, 'Provide 1–500 measurements')
        rows = []
        for item in items:
            if not isinstance(item, dict):
                fail(400, 'Invalid measurement')
            sid, stamp = text(item.get('sampleId'), 'sampleId', 128), timestamp(item.get('recordedAt'))
            if stamp > iso(now() + timedelta(minutes=5)):
                fail(400, 'Measurement is in the future')
            steps = item.get('steps')
            if not number(steps) or steps % 1 or not 0 <= steps <= 1000000:
                fail(400, 'Invalid step increment')
            for key, maximum in (('heartRate', 300), ('battery', 100)):
                value = item.get(key)
                if value is not None and (not number(value) or not 0 <= value <= maximum):
                    fail(400, f'Invalid {key}')
            rows.append((device_id, sid, stamp, steps, item.get('heartRate'), item.get('battery')))
        with db:
            inserted = sum(db.execute('INSERT INTO measurements VALUES(?,?,?,?,?,?) ON CONFLICT(device_id,sample_id) DO NOTHING', row).rowcount for row in rows)
        return {'inserted': inserted, 'duplicates': len(rows)-inserted}

    @app.api_route('/api/monitoring/grants', methods=['GET', 'POST', 'DELETE'])
    async def grants(request: Request):
        user = user_for(request)
        if user['role'] != 'user':
            fail(403, 'Only users can manage monitoring access')
        if request.method == 'GET':
            return {'admins': [dict(row) for row in db.execute('SELECT u.id,u.email FROM monitoring_grants g JOIN users u ON u.id=g.admin_id WHERE g.user_id=? ORDER BY u.email', (user['id'],))]}
        if request.method == 'DELETE':
            admin_id = request.query_params.get('adminId', '')
            with db:
                db.execute('DELETE FROM monitoring_grants WHERE user_id=? AND admin_id=?', (user['id'], admin_id))
            return {'ok': True}
        email = text(request.state.body.get('email'), 'email', 254).lower()
        admin = db.execute("SELECT id,email FROM users WHERE email=? AND role='admin'", (email,)).fetchone()
        if not admin:
            fail(404, 'Administrator not found')
        with db:
            db.execute('INSERT OR IGNORE INTO monitoring_grants VALUES(?,?)', (user['id'], admin['id']))
        return {'admin': dict(admin)}

    @app.post('/api/predictions')
    async def save_prediction(request: Request):
        user = user_for(request)
        if user['role'] != 'user':
            fail(403, 'Only users can send activity predictions')
        body = request.state.body
        if body.get('userId') != user['id']:
            fail(403, 'Prediction account does not match the signed-in user')
        label = text(body.get('activity'), 'activity', 80)
        confidence = body.get('confidence')
        device_time = body.get('deviceTime')
        if not number(confidence) or not 0 <= confidence <= 1:
            fail(400, 'Invalid confidence')
        if not number(device_time) or device_time % 1 or not 0 <= device_time <= 4294967295:
            fail(400, 'Invalid deviceTime')
        received = iso(now())
        with db:
            db.execute('INSERT INTO live_predictions VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET activity=excluded.activity,confidence=excluded.confidence,device_time=excluded.device_time,received_at=excluded.received_at', (user['id'], label, confidence, device_time, received))
        return {'ok': True, 'receivedAt': received}

    @app.get('/api/monitoring/users')
    async def monitoring(request: Request):
        user = user_for(request)
        if user['role'] != 'admin':
            fail(403, 'Administrator account required')
        rows = db.execute('SELECT u.id,u.email,p.activity,p.confidence,p.device_time AS deviceTime,p.received_at AS receivedAt FROM monitoring_grants g JOIN users u ON u.id=g.user_id LEFT JOIN live_predictions p ON p.user_id=u.id WHERE g.admin_id=? ORDER BY u.email', (user['id'],))
        return {'users': [dict(row) for row in rows]}

    @app.get('/api/activity/{kind}')
    async def activity(kind: str, request: Request):
        user = user_for(request)
        if kind not in ('summary', 'history'):
            fail(404, 'Endpoint not found')
        start = timestamp(request.query_params.get('from') or now().strftime('%Y-%m-%dT00:00:00Z'))
        end = timestamp(request.query_params.get('to') or iso(now()))
        if start >= end or datetime.fromisoformat(end.replace('Z', '+00:00')) - datetime.fromisoformat(start.replace('Z', '+00:00')) > timedelta(days=366):
            fail(400, 'Use a time range greater than zero and at most 366 days')
        where = ' FROM measurements m JOIN devices d ON d.id=m.device_id WHERE d.user_id=? AND m.recorded_at>=? AND m.recorded_at<?'
        if kind == 'summary':
            row = db.execute('SELECT COALESCE(SUM(m.steps),0) AS steps, AVG(m.heart_rate) AS averageHeartRate, COUNT(*) AS samples' + where, (user['id'], start, end)).fetchone()
            return {'from': start, 'to': end, **dict(row)}
        rows = db.execute('SELECT substr(m.recorded_at,1,10) AS date,SUM(m.steps) AS steps,AVG(m.heart_rate) AS averageHeartRate' + where + ' GROUP BY date ORDER BY date', (user['id'], start, end))
        return {'from': start, 'to': end, 'days': [dict(row) for row in rows]}

    return app

