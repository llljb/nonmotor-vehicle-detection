"""Local Flask course project: image inference, camera preview and SQLite CRUD."""
import io
import json
import os
import secrets
import sqlite3
import warnings
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from uuid import uuid4

from flask import Flask, Response, abort, jsonify, render_template, request, send_from_directory, session
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.exceptions import HTTPException
from detector import Detector


def create_app(config=None, detector=None):
    app = Flask(__name__)
    app.config.update(SECRET_KEY=os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32),
                      MAX_CONTENT_LENGTH=8 * 1024 * 1024,
                      DATA_DIR=str(Path(__file__).resolve().parent / 'runtime'),
                      SESSION_COOKIE_SAMESITE='Strict', CSRF_ENABLED=True)
    if config:
        app.config.update(config)
    directory = Path(app.config['DATA_DIR'])
    directory.mkdir(parents=True, exist_ok=True)
    images_dir = directory / 'images'
    images_dir.mkdir(exist_ok=True)
    db_path, predictor, camera_lock = directory / 'records.sqlite3', detector or Detector(), Lock()

    @contextmanager
    def connect():
        connection = sqlite3.connect(db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    with connect() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS detections (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, image_name TEXT NOT NULL,
                count INTEGER NOT NULL, objects TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS vehicles (
                id INTEGER PRIMARY KEY AUTOINCREMENT, plate TEXT NOT NULL UNIQUE,
                vehicle_type TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL);
        ''')

    @app.before_request
    def check_csrf():
        if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} and app.config['CSRF_ENABLED']:
            token = request.headers.get('X-CSRF-Token', '')
            if not session.get('csrf') or not secrets.compare_digest(token, session['csrf']):
                abort(403, description='页面已失效，请刷新后重试。')

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.get('/')
    def index():
        session.setdefault('csrf', secrets.token_hex(24))
        return render_template('index.html', csrf_token=session['csrf'])

    @app.get('/api/health')
    def health():
        return jsonify(status='ok', model_loaded=predictor.model is not None)

    @app.post('/api/detect')
    def detect():
        import cv2
        import numpy as np
        upload = request.files.get('image')
        if not upload or not upload.filename:
            abort(400, description='请选择图片。')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(upload.read())) as source:
                    if source.format not in {'JPEG', 'PNG', 'WEBP'} or source.width * source.height > 20_000_000:
                        abort(400, description='请上传不超过2000万像素的JPEG、PNG或WebP图片。')
                    image = ImageOps.exif_transpose(source).convert('RGB')
                    image.thumbnail((1920, 1920))
                    frame = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            abort(400, description='无法读取图片，请检查文件格式。')
        try:
            annotated, objects = predictor.predict(frame)
        except Exception:
            app.logger.exception('YOLO inference failed')
            abort(503, description='模型尚未就绪，请检查依赖、网络、权重与模型路径。')
        identity = uuid4().hex
        filename = identity + '.jpg'
        success, buffer = cv2.imencode('.jpg', annotated)
        if not success:
            abort(500, description='检测结果编码失败。')
        destination = images_dir / filename
        destination.write_bytes(buffer.tobytes())
        try:
            with connect() as db:
                db.execute('INSERT INTO detections VALUES (?, ?, ?, ?, ?)',
                           (identity, datetime.now(timezone.utc).isoformat(), filename, len(objects),
                            json.dumps(objects, ensure_ascii=False)))
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return jsonify(id=identity, count=len(objects), objects=objects, image_url='/images/' + filename), 201

    @app.get('/images/<filename>')
    def image_result(filename):
        return send_from_directory(images_dir, filename)

    @app.get('/api/detections')
    def list_detections():
        with connect() as db:
            rows = db.execute('SELECT * FROM detections ORDER BY created_at DESC LIMIT 100').fetchall()
        records = []
        for row in rows:
            record = dict(row)
            record['objects'] = json.loads(record['objects'])
            record['image_url'] = '/images/' + record.pop('image_name')
            records.append(record)
        return jsonify(records=records)

    @app.delete('/api/detections/<identity>')
    def delete_detection(identity):
        with connect() as db:
            row = db.execute('SELECT image_name FROM detections WHERE id=?', (identity,)).fetchone()
            if row is None:
                abort(404, description='记录不存在。')
            db.execute('DELETE FROM detections WHERE id=?', (identity,))
        (images_dir / row['image_name']).unlink(missing_ok=True)
        return '', 204

    def vehicle_payload():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            abort(400, description='请提交JSON对象。')
        result = {}
        for name, maximum, required in [('plate', 32, True), ('vehicle_type', 32, True), ('note', 300, False)]:
            value = data.get(name, '')
            if not isinstance(value, str) or len(value.strip()) > maximum or (required and not value.strip()):
                abort(400, description=f'{name} 字段为空或长度超限。')
            result[name] = value.strip()
        return result

    @app.get('/api/vehicles')
    def list_vehicles():
        query = request.args.get('q', '')[:64]
        try:
            page = max(1, int(request.args.get('page', '1')))
        except ValueError:
            abort(400, description='页码无效。')
        with connect() as db:
            rows = db.execute('SELECT * FROM vehicles WHERE instr(plate, ?) > 0 ORDER BY id DESC LIMIT 50 OFFSET ?',
                              (query, (page - 1) * 50)).fetchall()
        return jsonify(records=[dict(row) for row in rows], page=page)

    @app.route('/api/vehicles', methods=['POST'])
    @app.route('/api/vehicles/<int:identity>', methods=['PUT'])
    def save_vehicle(identity=None):
        data = vehicle_payload()
        try:
            with connect() as db:
                if identity is None:
                    cursor = db.execute('INSERT INTO vehicles(plate,vehicle_type,note,created_at) VALUES (?,?,?,?)',
                                        (data['plate'], data['vehicle_type'], data['note'], datetime.now(timezone.utc).isoformat()))
                    identity = cursor.lastrowid
                else:
                    cursor = db.execute('UPDATE vehicles SET plate=?,vehicle_type=?,note=? WHERE id=?',
                                        (data['plate'], data['vehicle_type'], data['note'], identity))
                    if cursor.rowcount == 0:
                        abort(404, description='记录不存在。')
        except sqlite3.IntegrityError:
            abort(409, description='该车辆编号已存在。')
        return jsonify(id=identity, **data), 201 if request.method == 'POST' else 200

    @app.delete('/api/vehicles/<int:identity>')
    def delete_vehicle(identity):
        with connect() as db:
            cursor = db.execute('DELETE FROM vehicles WHERE id=?', (identity,))
            if cursor.rowcount == 0:
                abort(404, description='记录不存在。')
        return '', 204

    @app.get('/video_feed')
    def video_feed():
        import cv2
        if not camera_lock.acquire(blocking=False):
            abort(409, description='摄像头正在使用，请先关闭其他预览。')
        capture = None
        try:
            capture = cv2.VideoCapture(int(os.environ.get('CAMERA_INDEX', '0')))
            if not capture.isOpened():
                abort(503, description='摄像头不可用，请检查设备权限及CAMERA_INDEX。')
            success, first = capture.read()
            if not success:
                abort(503, description='无法读取摄像头画面。')
            first, _ = predictor.predict(first)
        except Exception as error:
            if capture is not None:
                capture.release()
            camera_lock.release()
            if isinstance(error, HTTPException):
                raise
            app.logger.exception('Camera/model startup failed')
            abort(503, description='摄像头或模型初始化失败，请检查本地配置。')

        released = False

        def release_camera():
            nonlocal released
            if not released:
                released = True
                capture.release()
                camera_lock.release()

        def frames():
            try:
                annotated = first
                while True:
                    ok, encoded = cv2.imencode('.jpg', annotated)
                    if not ok:
                        break
                    yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + encoded.tobytes() + b'\r\n'
                    ok, frame = capture.read()
                    if not ok:
                        break
                    annotated, _ = predictor.predict(frame)
            finally:
                release_camera()
        response = Response(frames(), mimetype='multipart/x-mixed-replace; boundary=frame')
        response.call_on_close(release_camera)
        response.headers['Cache-Control'] = 'no-store'
        return response

    return app


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=5000, threaded=True, debug=False)
