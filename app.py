from flask import Flask, render_template, request, send_file, jsonify, Response, abort
from pathlib import Path
from datetime import datetime
import hmac
import os
import io
import argparse
import qrcode
import qrcode.image.svg
from credentials import load_hash, configure_password, check_password_hash
import shutil
import socket
import tempfile
import zipfile

app = Flask(__name__)
UPLOAD_FOLDER = Path(os.getenv('SHARED_FOLDER', str(Path(__file__).parent / 'SharedFolder'))).expanduser().resolve()
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
app.config.update(UPLOAD_FOLDER=UPLOAD_FOLDER, MAX_CONTENT_LENGTH=int(os.getenv('MAX_UPLOAD_BYTES', 10 * 1024**3)))
ACCESS_TOKEN = os.getenv('SHARED_PASSWORD')
PASSWORD_HASH = None
PORT = int(os.getenv('PORT', '5000'))
LAN_DOMAIN = os.getenv('LAN_DOMAIN', '').strip()


@app.before_request
def authorize():
    auth = request.authorization
    valid_password = False
    if auth and auth.type.lower() == 'basic':
        if ACCESS_TOKEN:
            valid_password = hmac.compare_digest((auth.password or '').encode(), ACCESS_TOKEN.encode())
        else:
            saved_hash = PASSWORD_HASH or load_hash()
            if saved_hash:
                valid_password = check_password_hash(saved_hash, auth.password or '')
    if not auth or auth.username != 'shared' or not valid_password:
        return Response('请使用账号 shared 和你设置的固定密码登录', 401, {'WWW-Authenticate': 'Basic realm="SharedServer", charset="UTF-8"'})
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('Origin')
        if request.headers.get('Sec-Fetch-Site') == 'cross-site' or (origin and origin != request.host_url.rstrip('/')):
            abort(403)
        if request.headers.get('X-SharedServer') != '1':
            abort(403)


@app.after_request
def secure_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.errorhandler(413)
def too_large(error):
    return jsonify(success=False, message='上传请求超过大小上限或磁盘空间不足'), 413


@app.errorhandler(OSError)
def storage_error(error):
    app.logger.exception('Storage operation failed')
    return jsonify(success=False, message='文件操作失败，请检查磁盘空间和权限'), 500


def root():
    return Path(app.config['UPLOAD_FOLDER']).resolve()


def safe_path(filename):
    base = root()
    candidate = base / filename
    if not filename or '\\' in filename or Path(filename).is_absolute():
        abort(403)
    if any(part.startswith('.') for part in Path(filename).parts):
        abort(403)
    current = base
    for part in Path(filename).parts:
        current = current / part
        if current.is_symlink():
            abort(403)
    resolved = candidate.resolve()
    if resolved == base or not resolved.is_relative_to(base):
        abort(403)
    return resolved


def get_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(('8.8.8.8', 80))
            return sock.getsockname()[0]
    except OSError:
        return '127.0.0.1'


def format_size(size):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f'{size:.1f}{unit}'
        size /= 1024
    return f'{size:.1f}PB'


def get_file_info():
    files = []
    for item in root().iterdir():
        if item.name.startswith('.') or item.is_symlink():
            continue
        try:
            stat = item.stat()
            files.append(dict(name=item.name, size=format_size(stat.st_size) if item.is_file() else '文件夹', size_bytes=stat.st_size if item.is_file() else None,
                              modified=datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'), type='folder' if item.is_dir() else 'file'))
        except FileNotFoundError:
            continue
    return sorted(files, key=lambda item: (item['type'] != 'folder', item['name'].lower()))


@app.get('/')
def index():
    return render_template('index.html', server_ip=get_local_ip(), server_port=PORT, server_domain=LAN_DOMAIN, lan_url=lan_url())


def lan_url():
    return f'http://{LAN_DOMAIN or get_local_ip()}:{PORT}'


@app.get('/access-qr.svg')
def access_qr():
    output = io.BytesIO()
    qrcode.make(lan_url(), image_factory=qrcode.image.svg.SvgPathImage).save(output)
    return Response(output.getvalue(), mimetype='image/svg+xml')


@app.get('/api/files')
def api_files():
    return jsonify(get_file_info())


@app.get('/api/disk-space')
def disk_space():
    total, used, free = shutil.disk_usage(root())
    return jsonify(total=total, used=used, free=free, free_formatted=format_size(free))


@app.get('/download/<path:filename>')
def download(filename):
    path = safe_path(filename)
    if not path.exists():
        abort(404)
    if path.is_file():
        return send_file(path, as_attachment=True, download_name=path.name, conditional=True)
    # Temporary archive lives outside the shared directory and is closed after streaming.
    archive = tempfile.TemporaryFile()
    try:
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as zipped:
            for directory, dirs, files in os.walk(path, followlinks=False):
                dirs[:] = [name for name in dirs if not name.startswith('.') and not (Path(directory) / name).is_symlink()]
                relative = Path(directory).relative_to(path)
                if relative.parts:
                    zipped.writestr(relative.as_posix() + '/', b'')
                for name in files:
                    item = Path(directory) / name
                    if name.startswith('.') or item.is_symlink():
                        continue
                    safe_path(str(item.relative_to(root())))
                    zipped.write(item, item.relative_to(path))
        length = archive.tell()
        archive.seek(0)
        def chunks():
            try:
                while block := archive.read(1024 * 1024):
                    yield block
            finally:
                archive.close()
        response = Response(chunks(), mimetype='application/zip')
        response.headers.set('Content-Disposition', 'attachment', filename=path.name + '.zip')
        response.content_length = length
        response.call_on_close(archive.close)
        return response
    except BaseException:
        archive.close()
        raise


@app.post('/upload')
def upload():
    incoming = request.files.getlist('files')
    if not incoming or not any(file.filename for file in incoming):
        return jsonify(success=False, message='请选择文件'), 400
    uploaded = []
    for file in incoming:
        if not file.filename:
            continue
        name = file.filename
        if '/' in name or '\\' in name or name.startswith('.'):
            return jsonify(success=False, message='文件名不合法', files=uploaded), 400
        safe_path(name)
        with tempfile.NamedTemporaryFile(dir=root(), prefix='.upload-', delete=False) as temporary:
            temporary_path = Path(temporary.name)
            try:
                while block := file.stream.read(1024 * 1024):
                    if shutil.disk_usage(root()).free < len(block) + 1024 * 1024:
                        abort(413)
                    temporary.write(block)
                temporary.flush()
                # Atomic no-overwrite publication also handles concurrent uploads.
                index = 0
                while True:
                    final_name = name if index == 0 else f'{Path(name).stem} ({index}){Path(name).suffix}'
                    destination = root() / final_name
                    try:
                        os.link(temporary_path, destination)
                        break
                    except FileExistsError:
                        index += 1
                uploaded.append(dict(name=final_name, size=format_size(destination.stat().st_size)))
            finally:
                temporary_path.unlink(missing_ok=True)
    return jsonify(success=True, message=f'已上传 {len(uploaded)} 个文件（同名文件自动重命名）', files=uploaded)


@app.post('/delete/<path:filename>')
def delete(filename):
    path = safe_path(filename)
    if not path.exists():
        abort(404)
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return jsonify(success=True, message='已删除')


if __name__ == '__main__':
    from waitress import serve
    parser = argparse.ArgumentParser(description='局域网文件共享服务器')
    parser.add_argument('--reset-password', action='store_true', help='重新设置保存的访问密码')
    args = parser.parse_args()
    if args.reset_password or not ACCESS_TOKEN:
        try:
            PASSWORD_HASH = configure_password(reset=args.reset_password)
        except (EOFError, KeyboardInterrupt):
            raise SystemExit('密码设置已取消，服务未启动。')
    print(f'本机：http://127.0.0.1:{PORT}\n局域网：{lan_url()}\n共享目录：{root()}\n账号：shared', flush=True)
    print('密码：使用 SHARED_PASSWORD 环境变量设置的密码' if ACCESS_TOKEN else '密码：使用你设置的固定密码（已保存，重启不变）')
    print('手机扫码打开网页，再输入账号密码：')
    qr = qrcode.QRCode(border=2)
    qr.add_data(lan_url())
    qr.make(fit=True)
    qr.print_ascii(invert=True)
    print('手机需能访问上述局域网地址；二维码不包含密码。', flush=True)
    serve(app, host=os.getenv('HOST', '0.0.0.0'), port=PORT, threads=8, max_request_body_size=app.config['MAX_CONTENT_LENGTH'])
