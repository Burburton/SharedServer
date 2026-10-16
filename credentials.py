"""Local password persistence. Only a salted password hash is stored."""
import getpass
import json
import os
from pathlib import Path
import tempfile
from werkzeug.security import generate_password_hash, check_password_hash

CONFIG_PATH = Path(__file__).parent / '.sharedserver.json'


def load_hash(path=CONFIG_PATH):
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding='utf-8'))['password_hash']
        if not isinstance(value, str) or not value.startswith('scrypt:'):
            raise ValueError('unsupported hash')
        return value
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError(f'密码配置损坏：{path}，请使用 --reset-password 重新设置') from error


def save_password(password, path=CONFIG_PATH):
    if len(password) < 6:
        raise ValueError('密码至少需要 6 个字符')
    hashed = generate_password_hash(password)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, prefix='.password-', delete=False) as file:
            temporary = Path(file.name)
            json.dump({'password_hash': hashed}, file)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return hashed


def configure_password(reset=False, path=CONFIG_PATH):
    if not reset:
        existing = load_hash(path)
        if existing:
            return existing
    print('首次使用请设置固定密码。' if not reset else '请设置新的访问密码。')
    while True:
        password = getpass.getpass('密码（至少 6 个字符，输入不显示）：')
        confirmation = getpass.getpass('再次输入密码：')
        if password != confirmation:
            print('两次密码不一致，请重试。')
        elif len(password) < 6:
            print('密码至少需要 6 个字符。')
        else:
            return save_password(password, path)
