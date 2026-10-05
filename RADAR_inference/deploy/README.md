# RadarScope 服务端部署与管理

**产品名**：RadarScope（原 RADAR Desktop）。架构：**服务端一个包，客户端就是浏览器**。服务启动后自带完整前端页面（`http://<服务地址>:8125`），
客户端零安装、零配置。同一份包覆盖两种场景：

| 场景 | 命令 | 访问方式 |
|---|---|---|
| 局域网服务器（GPU 工作站等，**默认**） | `start_server.bat`（或 `.sh`） | 网内任意电脑浏览器访问 `http://<服务器IP>:8125` |
| 个人电脑（单机，可选） | `start_server.bat local` | 本机浏览器自动打开 `http://127.0.0.1:8125` |

> ⚠️ 局域网模式**无鉴权**（设计约定），请只在可信网络内开放；面向不可信网络时需在前置反向代理层加认证。

## 分发包

| 产物 | 命名 |
|---|---|
| 源码/包目录 | `RadarScope/` |
| 分发包 | `RadarScope.zip` |

包内只有平台无关文件，`setup_env` / `start_server` 各自带 `.bat` 与 `.sh` 两份，
**同一个 zip 在 Windows 和 Linux 上都能直接部署**，因此包名不带平台后缀。

## 首次部署：安装 Python 环境（分发包必做）

分发包**不再内置 Python / PyTorch / 依赖库**，首次部署前在**包根目录**运行环境安装脚本：

```bat
setup_env.bat          REM Windows（双击或命令行均可）
```

```bash
./setup_env.sh         REM Linux
```

脚本流程（每一步都会自动跳过已完成的部分，**可反复运行、断点续装**）：

1. 扫描本机 Python（py 启动器 / PATH / 常见安装目录 / conda），也可手动粘贴完整路径；仅接受 **3.10.x**（打包验证版本为 3.10.18）；
2. 在 `RADAR_inference\env` 创建专用虚拟环境——启动脚本的解析顺序正好覆盖这个位置，**无需任何配置**；
3. 询问 PyPI 镜像源（默认清华）；
4. 安装 PyTorch：自动探测 NVIDIA 显卡，可选 CUDA 12.9 版（约 2.5 GB，来自 download.pytorch.org）或 CPU 版；
5. 按 `requirements-desktop.txt`（按实际验证过的运行环境冻结的清单）安装其余依赖，失败自动重试 3 次；
6. 检查 `ckpt/` 下的模型权重：**缺失时询问是否立即下载**（走 hf-mirror.com 镜像，
   支持断点续传）；若 plus 权重已就位而文本嵌入缺失，自动用 MERLIN 官方提示词现算生成。

> 提示：torch 官方 wheel 依赖 Microsoft Visual C++ Redistributable（VC++ 2015-2019 x64），
> 若导入 torch 报 `DLL load failed`，先安装 VC++ 运行库再重跑脚本。

### 单独下载权重

```bash
# main 最小可用集（默认，约 1.9 GB）；--preset 可选 main / plus / all
python RADAR_inference/scripts/download_weights.py --preset main
# 只看计划不下流量
python RADAR_inference/scripts/download_weights.py --dry-run
```

脚本默认走 `hf-mirror.com`；换镜像：`HF_ENDPOINT=<镜像> python ... download_weights.py`。
服务端管理页的「模型权重」下载按钮调用的是同一个脚本。

## Windows

```bat
deploy\start_server.bat           REM 局域网模式（默认，不自动开浏览器）
deploy\start_server.bat lan 9000  REM 局域网模式 + 自定义端口
deploy\start_server.bat local     REM 单机模式，服务就绪后自动打开浏览器
deploy\start_server.bat local 9000 REM 单机模式 + 自定义端口

deploy\stop_server.bat            REM 停止（按端口 8125 找进程）
deploy\stop_server.bat 9000       REM 停止指定端口
```

服务以前台窗口运行（标题 **RadarScope Server**）：窗口内**实时滚动显示**启动信息、用户连接（来源 IP + 请求）与业务操作日志（上传 / 删除 / 取消 / 置顶任务、后台登录等）；关闭该窗口即停止服务，也可以用 `stop_server.bat`。
日志同时落盘 `logs\server.log`（UTF-8）。

**多网卡机器**：`start_server.bat`（局域网模式）启动时会先列出全部 IPv4 网卡，
让你选择绑定哪一张（直接回车 = 绑定全部 `0.0.0.0`）。绑到指定网卡后，网内其他电脑
只能通过该网卡的 IP 访问（如 `http://192.168.x.x:8125`，x 为该网卡实际地址）。

## Linux

```bash
./deploy/start_server.sh          # 局域网模式（默认）
./deploy/start_server.sh lan 9000 # 局域网模式 + 自定义端口
./deploy/start_server.sh local    # 单机模式
./deploy/stop_server.sh           # 停止（pid 文件 + 端口兜底）
```

后台运行（nohup），pid 记录在 `logs/server.pid`，日志 `logs/server.log`。

## Python 环境解析顺序

1. 环境变量 `RADAR_PYTHON`（显式指定解释器）；
2. `RADAR_inference/env/` 专用虚拟环境（Windows: `env\python.exe`，Linux: `env/bin/python`）——由包根目录的 `setup_env.bat` / `setup_env.sh` 首次部署时创建；
3. 若两者都不存在，启动脚本会**直接报错并提示先运行 setup_env 脚本**（不再静默回退到 PATH 上的 python，避免用到缺少依赖的解释器）。

因此开发仓库与用户部署后的目录用**同一套脚本**，无需修改。

## 服务常驻（可选，局域网服务器推荐）

- **Windows**：用 [NSSM](https://nssm.cc/) 把 `service.py` 注册为 Windows 服务，开机自启、崩溃自动拉起：
  `nssm install RADARServer <python路径> service.py --host 0.0.0.0 --port 8125`
- **Linux**：`systemd` unit 或 `@reboot` crontab。

MVP 默认不注册服务，脚本手动启停即可。

## 可选权重：`checkpoint_radar_plus.pth`（plus_scratch 槽位）

分发包默认只带 `checkpoint_radar_pretrain.pth`（main）与
`checkpoint_radar_plus_finetuned_on_merlin.pth`（plus）。官方还提供了一个
**在 Merlin-CT-Train 上从头训练**的 `checkpoint_radar_plus.pth`（官方 AUC 0.888，
低于微调版的 0.918）。用下面的命令直接下载到 `ckpt/`：

```bash
python RADAR_inference/scripts/download_weights.py \
    --include-patterns checkpoint_radar_plus.pth
```

下载后**必须现算一份文本嵌入**（plus 随包的那份是给 finetuned 权重用的）：

```bash
cd RADAR_inference
python -m radar.engine.text_embed --items merlin20 \
    --checkpoint ../ckpt/checkpoint_radar_plus.pth \
    --out ../ckpt/infer_text_embedding_plus_scratch.pt
```

原因：文本嵌入是"用哪个权重、配哪套提示词"算出来的，**不能跨权重通用**。
`infer_text_embedding_merlin_en.pt` 是用 *finetuned* 权重算的，虽然两个权重架构与
词表完全相同（都是英文 `bert-base-uncased` / 30522，文件仅差 1.4 KB），
但文本编码器参数不同，直接套用等于又一次空间错配。

想省这一步可先验证：现算后与 `merlin_en.pt` 比对同名项 cosine，若 ≈1.0 说明
两个权重的文本编码器一致、可通用；否则必须用自己现算的那份。

> 官方训练指南（Training Guide）明确："We use the official prompts released by MERLIN
> during inference." —— 即用 MERLIN 官方提示词现算嵌入，正是本 CLI 的做法。

## 相关参数（service.py）

| 参数 | 说明 | 默认 |
|---|---|---|
| `--host` | `127.0.0.1` 单机 / `0.0.0.0` 局域网 | `127.0.0.1` |
| `--port` | 服务端口 | `8000`（脚本默认 `8125`） |
| `--open` | 就绪后自动打开浏览器（仅单机模式用） | 关 |
| `--results-dir` | 产物目录 | `<仓库根>/results` |
| `RADAR_FRONTEND_DIST` | 前端静态目录覆盖（绿色版自定义布局用） | `frontend/dist` |
