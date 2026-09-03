"""极简单用户认证模块。

- 支持环境变量 AUTH_USERNAME / AUTH_PASSWORD（docker run 时提供）
- 未配置环境变量时，允许首次访问网页注册唯一账号
- 密码以 PBKDF2 哈希存 SQLite settings；会话使用 Flask session + 随机 secret
"""
import hashlib
import hmac
import secrets

from . import config, database


class AuthError(Exception):
    """认证业务错误，message 可直接展示给前端。"""


def _env_credentials():
    """返回 (username, password)；环境变量必须成对配置才生效。"""
    u = config.AUTH_USERNAME
    p = config.AUTH_PASSWORD
    if u and p:
        return u, p
    return None, None


def account_exists() -> bool:
    """是否存在可登录的账号（环境变量账号或数据库注册账号）。"""
    env_u, _ = _env_credentials()
    if env_u:
        return True
    return bool(database.get_setting("auth_username"))


def verify(username: str, password: str) -> bool:
    env_u, env_p = _env_credentials()
    username = username or ""
    password = password or ""

    if env_u:
        return hmac.compare_digest(username, env_u) and hmac.compare_digest(password, env_p)

    stored_user = database.get_setting("auth_username")
    if not stored_user:
        return False
    if not hmac.compare_digest(stored_user, username):
        return False
    stored_hash = database.get_setting("auth_password_hash")
    return stored_hash and _verify_password(password, stored_hash)


def register(username: str, password: str):
    if _env_credentials()[0]:
        raise AuthError("当前已通过环境变量配置账号，不能重复注册")
    if database.get_setting("auth_username"):
        raise AuthError("账号已存在，请直接登录")

    username = (username or "").strip()
    if len(username) < 2:
        raise AuthError("用户名至少 2 个字符")
    if len(username) > 32:
        raise AuthError("用户名不能超过 32 个字符")
    if len(password or "") < 4:
        raise AuthError("密码至少 4 个字符")
    if len(password or "") > 128:
        raise AuthError("密码不能超过 128 个字符")

    database.set_setting("auth_username", username)
    database.set_setting("auth_password_hash", _hash_password(password))
    database.set_setting("auth_registered_at", "registered")
    return username


def get_or_create_session_secret() -> str:
    if config.SESSION_SECRET:
        return config.SESSION_SECRET
    secret = database.get_setting("auth_session_secret")
    if not secret:
        secret = secrets.token_hex(32)
        database.set_setting("auth_session_secret", secret)
    return secret


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), 120_000
    ).hex()
    return f"{salt}${digest}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, expected = stored.split("$", 1)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), 120_000
    ).hex()
    return hmac.compare_digest(digest, expected)
