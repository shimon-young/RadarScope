"""后台管理：账号密码鉴权 + 官方 HF 仓库文件清单。

鉴权设计（局域网单机场景，刻意从简）：
- 账号唯一（默认 admin/admin），密码修改后以 `salt + sha256` 落盘
  results/admin_auth.json，重启仍生效；明文绝不落盘。
- 登录成功发内存 token（secrets.token_hex，12 小时过期），服务重启即全部失效。
- 所有 /api/admin/*（除 /login）都必须带 `Authorization: Bearer <token>`。

官方仓库清单：
- 运行时从镜像（HF_ENDPOINT，默认 hf-mirror.com）拉取 radar-generalist/RADAR
  的完整文件树并缓存 10 分钟；逐文件探测本地 ckpt 目录的就绪状态。
- 文本特征 `infer_text_embedding_radar.pt` 为官方发布文件（在官方仓库 `ckpt/` 下），
  随权重一起获取，不在待下载清单内。
- `infer_text_embedding_merlin_en.pt` 由安装后现算生成，同样不在清单内。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .schemas import RepoFileInfo

REPO_ID = "radar-generalist/RADAR"
HF_MIRROR = "https://hf-mirror.com"
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASSWORD = "admin"
TOKEN_TTL_S = 12 * 3600
REPO_CACHE_TTL_S = 600

# 官方仓库中与本程序无关的展示噪音
_REPO_EXCLUDE = {".gitattributes", "README.md", "radar_fig0.png"}


def _hash(salt: str, password: str) -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


class AdminAuth:
    """单账号鉴权（线程安全；token 在内存，密码哈希在磁盘）。"""

    def __init__(self, auth_file: Path) -> None:
        self._file = auth_file
        self._lock = threading.Lock()
        self._tokens: dict[str, float] = {}  # token -> 过期时间戳
        self._username, self._salt, self._hash = self._load()

    def _load(self) -> tuple[str, str, str]:
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            return (
                str(data.get("username") or DEFAULT_ADMIN_USER),
                str(data.get("salt") or ""),
                str(data.get("password_hash") or ""),
            )
        except Exception:  # noqa: BLE001 - 文件缺失/损坏 → 出厂默认
            return DEFAULT_ADMIN_USER, "", ""

    @property
    def is_default_password(self) -> bool:
        return not (self._salt and self._hash)

    @property
    def username(self) -> str:
        return self._username

    def verify_password(self, password: str) -> bool:
        """只校验密码（改密时用）；默认态比对出厂密码，否则比对哈希。"""
        with self._lock:
            if self.is_default_password:
                return hmac.compare_digest(password, DEFAULT_ADMIN_PASSWORD)
            return hmac.compare_digest(_hash(self._salt, password), self._hash)

    def verify(self, username: str, password: str) -> bool:
        """默认态比对出厂账号密码；改过密后比对哈希。"""
        with self._lock:
            if username != self._username:
                return False
            if self.is_default_password:
                return hmac.compare_digest(username, DEFAULT_ADMIN_USER) and hmac.compare_digest(
                    password, DEFAULT_ADMIN_PASSWORD
                )
            return hmac.compare_digest(_hash(self._salt, password), self._hash)

    def set_password(self, new_password: str) -> None:
        with self._lock:
            self._salt = secrets.token_hex(8)
            self._hash = _hash(self._salt, new_password)
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(
                json.dumps(
                    {
                        "username": self._username,
                        "salt": self._salt,
                        "password_hash": self._hash,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            self._tokens.clear()  # 改密后强制全部重新登录

    def login(self, username: str, password: str) -> str | None:
        if not self.verify(username, password):
            return None
        token = secrets.token_hex(32)
        with self._lock:
            self._purge_expired_locked()
            self._tokens[token] = time.time() + TOKEN_TTL_S
        return token

    def logout(self, token: str) -> None:
        with self._lock:
            self._tokens.pop(token, None)

    def verify_token(self, token: str) -> bool:
        with self._lock:
            exp = self._tokens.get(token)
            if exp is None:
                return False
            if exp < time.time():
                del self._tokens[token]
                return False
            return True

    def _purge_expired_locked(self) -> None:
        now = time.time()
        for t in [t for t, exp in self._tokens.items() if exp < now]:
            del self._tokens[t]


def list_repo_files(ckpt_dir: Path) -> tuple[list[RepoFileInfo], str | None]:
    """拉官方仓库完整文件树并探测本地状态；失败返回 (错误信息, None)。

    推理服务默认 HF_HUB_OFFLINE=1（模型加载不联网）；清单拉取必须联网，
    这里临时解除（huggingface_hub 在调用时读 constants.HF_HUB_OFFLINE），
    finally 恢复，绝不影响模型加载行为。
    """
    try:
        import huggingface_hub.constants as hf_const
        from huggingface_hub import HfApi

        prev_flag = hf_const.HF_HUB_OFFLINE
        prev_env = os.environ.get("HF_HUB_OFFLINE")
        hf_const.HF_HUB_OFFLINE = False
        os.environ["HF_HUB_OFFLINE"] = "0"
        try:
            api = HfApi(endpoint=os.environ.get("HF_ENDPOINT", HF_MIRROR))
            files: list[RepoFileInfo] = []
            for item in api.list_repo_tree(REPO_ID, recursive=True):
                path = getattr(item, "path", None)
                if not path or path in _REPO_EXCLUDE:
                    continue
                size = getattr(item, "size", None)
                if size is None:  # RepoFolder 等非文件节点
                    continue
                local = ckpt_dir / path
                files.append(
                    RepoFileInfo(
                        path=path,
                        size=int(size),
                        local_exists=local.is_file(),
                        local_size=local.stat().st_size if local.is_file() else None,
                    )
                )
            return files, None
        finally:
            hf_const.HF_HUB_OFFLINE = prev_flag
            if prev_env is None:
                os.environ.pop("HF_HUB_OFFLINE", None)
            else:
                os.environ["HF_HUB_OFFLINE"] = prev_env
    except Exception as exc:  # noqa: BLE001 - 网络/镜像问题原样上报
        return [], f"{type(exc).__name__}: {exc}"


class RepoCache:
    """仓库清单缓存（TTL 10 分钟；首次失败不缓存，下次请求重试）。"""

    def __init__(self, ckpt_dir: Path) -> None:
        self._ckpt = ckpt_dir
        self._lock = threading.Lock()
        self._files: list[RepoFileInfo] = []
        self._error: str | None = None
        self._fetched_at: datetime | None = None
        self._ts: float = 0.0

    def get(self, force: bool = False) -> tuple[list[RepoFileInfo], str | None, datetime | None]:
        with self._lock:
            fresh = (time.time() - self._ts) < REPO_CACHE_TTL_S
            if fresh and self._error is None and not force:
                return self._files, None, self._fetched_at
            files, err = list_repo_files(self._ckpt)
            if err is None:
                self._files, self._error, self._fetched_at = files, None, datetime.now(timezone.utc)
                self._ts = time.time()
            else:
                # 失败不更新缓存时间：镜像恢复后下一个请求立即重试
                self._error = err
            return self._files, self._error, self._fetched_at

    def validate_pattern(self, pattern: str) -> list[str]:
        """校验下载 pattern 是否指向官方仓库真实文件，返回解析出的文件列表。

        支持两种形态：精确文件路径（checkpoint_unet.pth）、目录前缀
        （bert-base-chinese/*）。官方清单拉不到时一律拒绝，避免任意下载。
        """
        files, err, _ = self.get()
        if err is not None or not files:
            raise LookupError(f"官方仓库清单不可用：{err}")
        paths = [f.path for f in files]
        if pattern in paths:
            return [pattern]
        if pattern.endswith("/*"):
            prefix = pattern[:-2]
            hits = [p for p in paths if p.startswith(prefix + "/")]
            if hits:
                return hits
        raise LookupError(f"官方仓库中不存在该文件或目录：{pattern}")
