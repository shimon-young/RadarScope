"""RadarScope 服务入口。

    python service.py                       # 单机模式 127.0.0.1:8000
    python service.py --host 0.0.0.0        # 局域网模式
    python service.py --results-dir D:/x    # 自定义产物目录

局域网模式务必确认所在网络可信（无鉴权）。

日志策略：控制台 + logs/server.log 双写。用 start_server.bat 启动时，
服务窗口会实时滚动显示启动信息、用户连接与业务操作；关闭窗口即停止服务。
"""

from __future__ import annotations

import argparse
import logging
import logging.config
import os
import sys
import time

import uvicorn


def _enforce_offline() -> None:
    """钉死"零外网"：所有权重/词表/BERT 均已随仓库本地提供，推理全程不需要联网。

    这些变量必须在 import transformers / huggingface_hub 之前设置。
    设为离线的好处是：将来若有人误改代码触发下载，会立刻报明确错误，
    而不是在国内网络下默默卡住几十秒超时。
    """
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
    # torch/monai 不做任何外网检查，此处一并关掉可能的遥测
    os.environ.setdefault("MONAI_ALLOW_MISSING", "0")


def _setup_logging() -> dict:
    """构建控制台 + 文件双写日志配置（uvicorn 与业务日志共用）。"""
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "server.log")
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"default": {"format": fmt, "datefmt": "%H:%M:%S"}},
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "default",
            },
            "file": {
                "class": "logging.FileHandler",
                "filename": log_path,
                "encoding": "utf-8",
                "formatter": "default",
            },
        },
        "root": {"level": "INFO", "handlers": ["console", "file"]},
        "loggers": {
            "uvicorn": {"handlers": ["console", "file"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["console", "file"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["console", "file"], "level": "INFO", "propagate": False},
            "radar": {"handlers": ["console", "file"], "level": "INFO", "propagate": False},
        },
    }
    logging.config.dictConfig(log_config)
    return log_config


def main() -> int:
    parser = argparse.ArgumentParser(description="RadarScope 推理服务")
    parser.add_argument("--host", default=os.environ.get("RADAR_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("RADAR_PORT", "8000")))
    parser.add_argument("--results-dir", default=os.environ.get("RADAR_RESULTS_DIR"))
    parser.add_argument("--reload", action="store_true", help="开发用热重载")
    parser.add_argument(
        "--api-docs",
        action="store_true",
        help="开启 /docs 交互文档（默认关闭：它依赖 cdn.jsdelivr.net，国内网络可能加载失败）",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="服务就绪后自动用默认浏览器打开界面（本机部署用；局域网服务器模式不要开）",
    )
    args = parser.parse_args()

    _enforce_offline()

    os.environ["RADAR_HOST"] = args.host
    os.environ["RADAR_PORT"] = str(args.port)
    os.environ["RADAR_API_DOCS"] = "1" if args.api_docs else "0"
    if args.results_dir:
        os.environ["RADAR_RESULTS_DIR"] = args.results_dir

    log_config = _setup_logging()
    logger = logging.getLogger("radar")

    # 把仓库根加入 sys.path：保证 `import radar` 与 inference_demo 可用
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from radar.app import VERSION, create_app

    lan_mode = args.host not in ("127.0.0.1", "localhost", "::1")
    logger.info("============================================================")
    logger.info(" RadarScope v%s  服务启动", VERSION)
    logger.info(" 模式     : %s", "局域网 (绑定 %s)" % args.host if lan_mode else "单机 (仅本机)")
    logger.info(" 访问地址 : http://%s:%s/", args.host, args.port)
    logger.info(" 产物目录 : %s", os.environ.get("RADAR_RESULTS_DIR", "(默认 results/jobs)"))
    logger.info(" 日志     : 本窗口实时显示 + logs/server.log 落盘")
    logger.info(" 停止     : 关闭本窗口 或 Ctrl+C")
    logger.info("============================================================")
    if lan_mode:
        logger.warning("[安全] 局域网模式无鉴权，仅限可信网络使用！")

    app = create_app()

    if args.open:
        # 等端口就绪再开浏览器：权重加载要十几秒，过早打开只会看到连接被拒。
        # 守护线程轮询 TCP 连接，uvicorn 主循环不受影响；Ctrl+C 时线程随进程退出。
        import socket
        import threading
        import webbrowser

        probe_host = "127.0.0.1" if lan_mode else args.host
        probe_port = args.port

        def _open_when_ready() -> None:
            url = f"http://{probe_host}:{probe_port}"
            for _ in range(240):  # 最多等 2 分钟
                try:
                    with socket.create_connection((probe_host, probe_port), timeout=0.5):
                        webbrowser.open(url)
                        logger.info("已在默认浏览器打开 %s", url)
                        return
                except OSError:
                    time.sleep(0.5)
            logger.info("服务迟迟未就绪，放弃自动打开浏览器（可手动访问 %s）", url)

        threading.Thread(target=_open_when_ready, daemon=True).start()

    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="info", log_config=log_config)
    except KeyboardInterrupt:
        logger.info("[boot] 已停止")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
