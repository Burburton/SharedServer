from flask import Flask, render_template, request, send_file, jsonify
from pathlib import Path
import os
import socket
import mimetypes
import shutil
from datetime import datetime
from functools import wraps

app = Flask(__name__)

# 设置上传文件夹为SharedFolder
# 如果结构是: d:\SharedServer (app在这里) 和 d:\SharedFolder (要共享)
# 使用下面这行：
UPLOAD_FOLDER = Path(__file__).parent / 'SharedFolder'
# 如果要改为其他路径，改为绝对路径即可，比如：
# UPLOAD_FOLDER = Path('d:/your/path/to/folder')

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024 * 1024  # 10GB 最大文件大小
LAN_DOMAIN = os.getenv('LAN_DOMAIN', '').strip()  # 可选：局域网域名，如 files.home

# 确保文件夹存在
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

def get_local_ip():
    """获取本机局域网IP"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def get_file_info():
    """获取文件列表及其信息"""
    files = []
    ignore_files = ['app.py', 'requirements.txt']
    ignore_dirs = ['__pycache__', '.git', 'venv', 'env']
    
    for item in UPLOAD_FOLDER.iterdir():
        if item.name in ignore_files or item.name in ignore_dirs:
            continue
        if item.is_file():
            stat = item.stat()
            files.append({
                'name': item.name,
                'size': format_size(stat.st_size),
                'size_bytes': stat.st_size,
                'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                'type': 'file'
            })
        elif item.is_dir():
            size = sum(f.stat().st_size for f in item.rglob('*') if f.is_file())
            files.append({
                'name': item.name,
                'size': format_size(size),
                'size_bytes': size,
                'modified': datetime.fromtimestamp(item.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                'type': 'folder'
            })
    
    return sorted(files, key=lambda x: (x['type'] != 'folder', x['name'].lower()))

def format_size(size):
    """格式化文件大小"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f'{size:.1f}{unit}' if size < 100 else f'{int(size)}{unit}'
        size /= 1024
    return f'{size:.1f}PB'

@app.route('/')
def index():
    """主页"""
    files = get_file_info()
    ip = get_local_ip()
    return render_template(
        'index.html',
        files=files,
        server_ip=ip,
        server_port=5000,
        server_domain=LAN_DOMAIN
    )

@app.route('/api/files')
def api_files():
    """获取文件列表API"""
    files = get_file_info()
    return jsonify(files)

@app.route('/api/disk-space')
def api_disk_space():
    """获取磁盘空间信息"""
    disk_stat = shutil.disk_usage(UPLOAD_FOLDER)
    return jsonify({
        'total': disk_stat.total,
        'used': disk_stat.used,
        'free': disk_stat.free,
        'free_formatted': format_size(disk_stat.free)
    })

@app.route('/download/<path:filename>')
def download(filename):
    """下载文件"""
    # 安全检查：防止目录遍历攻击
    file_path = (UPLOAD_FOLDER / filename).resolve()
    if not str(file_path).startswith(str(UPLOAD_FOLDER.resolve())):
        return "Invalid file path", 403
    
    if not file_path.exists():
        return "File not found", 404
    
    if file_path.is_file():
        return send_file(file_path, as_attachment=True, download_name=filename)
    
    # 如果是目录，创建zip文件下载
    zip_path = UPLOAD_FOLDER / f"{filename}.zip"
    shutil.make_archive(str(zip_path.with_suffix('')), 'zip', file_path)
    return send_file(zip_path, as_attachment=True, download_name=f"{filename}.zip")

@app.route('/upload', methods=['POST'])
def upload():
    """上传文件"""
    if 'files' not in request.files:
        return jsonify({'success': False, 'message': 'No files provided'}), 400
    
    files = request.files.getlist('files')
    
    # 检查磁盘空间
    disk_stat = shutil.disk_usage(UPLOAD_FOLDER)
    free_space = disk_stat.free
    
    # 计算要上传的总大小
    total_upload_size = 0
    for file in files:
        if file.filename == '':
            continue
        file.seek(0, os.SEEK_END)
        total_upload_size += file.tell()
        file.seek(0)
    
    # 检查空间是否足够（预留1MB缓冲）
    if total_upload_size > free_space - (1 * 1024 * 1024):
        return jsonify({
            'success': False,
            'message': f'磁盘空间不足！需要 {format_size(total_upload_size)}，但只有 {format_size(free_space - 1024*1024)} 可用'
        }), 413
    
    uploaded_files = []
    
    for file in files:
        if file.filename == '':
            continue
        
        # 防止恶意文件名
        safe_filename = Path(file.filename).name
        if safe_filename in ['app.py', 'requirements.txt']:
            continue
        
        file_path = UPLOAD_FOLDER / safe_filename
        file.save(file_path)
        uploaded_files.append({
            'name': safe_filename,
            'size': format_size(file_path.stat().st_size)
        })
    
    if uploaded_files:
        return jsonify({
            'success': True,
            'message': f'Successfully uploaded {len(uploaded_files)} file(s)',
            'files': uploaded_files
        })
    else:
        return jsonify({'success': False, 'message': 'No files uploaded'}), 400

@app.route('/delete/<path:filename>', methods=['POST'])
def delete(filename):
    """删除文件"""
    file_path = (UPLOAD_FOLDER / filename).resolve()
    if not str(file_path).startswith(str(UPLOAD_FOLDER.resolve())):
        return jsonify({'success': False, 'message': 'Invalid path'}), 403
    
    if file_path.name in ['app.py', 'requirements.txt']:
        return jsonify({'success': False, 'message': 'Cannot delete system files'}), 403
    
    try:
        if file_path.is_file():
            file_path.unlink()
        elif file_path.is_dir():
            shutil.rmtree(file_path)
        return jsonify({'success': True, 'message': 'File deleted'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

if __name__ == '__main__':
    # 获取IP地址
    ip = get_local_ip()
    storage_path = UPLOAD_FOLDER.resolve()
    print(f'\n════════════════════════════════════════')
    print(f'🚀 文件共享服务器已启动!')
    print(f'🧭 第一次运行请先在本机打开一次页面完成初始化')
    print(f'📍 本地访问: http://127.0.0.1:5000')
    print(f'🌐 网络访问: http://{ip}:5000')
    if LAN_DOMAIN:
        print(f'🏷️ 域名访问: http://{LAN_DOMAIN}:5000')
    else:
        print(f'🏷️ 域名访问: 未配置（可设置环境变量 LAN_DOMAIN）')
    print(f'📁 文件上传/存储目录: {storage_path}')
    print(f'════════════════════════════════════════\n')
    
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
