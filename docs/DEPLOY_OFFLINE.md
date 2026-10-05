# RadarScope 离线与网络依赖说明

> 结论先行：**部署后的运行期零外网访问**，已用 socket 层探针 + 浏览器抓包双向验证。
> 需要联网的只有**开发期装包**（npm / pip），且均可切国内镜像。

---

## 一、运行期：零外网（已验证）

### 验证方法 1：后端 socket 探针

```bash
cd RADAR_inference
python scripts/netprobe.py          # main（146 项）
python scripts/netprobe.py plus     # plus（20 项）
```

脚本 hook `socket` 层（覆盖 requests / urllib3 / transformers / huggingface_hub 全部上层），
记录任何目标地址非本机/局域网的连接，并清除代理环境变量模拟"部署机裸网络"。
退出码 `0` = 零外网通过，`1` = 发现外部连接。

实测结果：

| 组合 | 加载 | 推理 | 输出 | 外网连接 |
|---|---|---|---|---|
| main + radar146 | 1.70 s | 4.99 s | 146 项 / 2 窗 | **0** |
| plus + merlin20 | 2.33 s | 4.92 s | 20 项 / 2 窗 | **0** |

在同一进程内额外设置 `TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1`
重跑，结果一致 —— 说明并非"恰好命中缓存"才没联网。

### 验证方法 2：前端浏览器抓包

完整交互（打开页面 → 加载 98 MB CT → 加载分割掩膜 → 渲染三视图 + 30 项图例 + 阳性结果）
后抓取全部网络请求，**无一例外全部指向 `127.0.0.1:8124`**：

```
GET /                                    (Document)
GET /assets/index-*.js / cornerstone-*.js / index-*.css
GET /api/system  /api/jobs?limit=30
GET /api/jobs/{id}/input.nii.gz          (98 MB 影像)
GET /api/jobs/{id}/result  /log
GET /api/jobs/{id}/segmentation.nii.gz   (分割掩膜)
blob:http://127.0.0.1:8124/...           (本地解码)
```

构建产物中不含任何 CDN / 在线字体 / 图标外链：
- `index.html` 仅引用本地 `/assets/*`，favicon 是内嵌 `data:image/svg+xml`
- JS 里能搜到的 `github.com` / `kitware.com` / `mozilla.org` 等全是第三方源码注释与许可证头，不产生运行时请求

---

## 二、运行期的两处外网相关设置

### 1. FastAPI `/docs`（Swagger UI）：默认关闭

`/docs`、`/redoc`、`/openapi.json` 会从 `cdn.jsdelivr.net` 拉 Swagger UI 资源，
是国内网络下页面空白或长时间等待的常见原因。

`Settings.api_docs` 默认 `False`，三个端点默认不挂载（访问会落到前端兜底页）。
需要时显式开启：

```bash
python service.py --api-docs          # 或 RADAR_API_DOCS=1
```

### 2. Chromium 的 `clients2.google.com` 探测：与产品无关

该请求来自**外部浏览器**的强制门户检测（captive portal detection），不是本程序发起，
对推理与服务没有任何影响。若将来打包内置浏览器内核，启动参数建议带上：

```
--disable-background-networking --disable-component-update
--no-pings --disable-sync --disable-domain-reliability
--disable-features=OptimizationGuideDeepPageUnderstanding,OptimizationHints
```

---

## 三、服务侧的离线加固

`service.py` 在 import 任何模型库之前钉死以下环境变量（`setdefault`，不覆盖用户显式设置）：

```
TRANSFORMERS_OFFLINE=1        HF_HUB_OFFLINE=1
HF_DATASETS_OFFLINE=1         HF_HUB_DISABLE_TELEMETRY=1
HF_HUB_DISABLE_IMPLICIT_TOKEN=1
```

目的是防御性的：权重、词表、BERT 全部本地提供，本不需要联网；
一旦将来有人误改代码触发下载，会在**入口立刻报明确错误**，
而不是在国内网络下默默卡住几十秒超时（最难排查的失败模式）。

---

## 四、开发期：需要联网的部分与国内镜像

运行期不需要，但**首次搭建开发环境 / 重装依赖**时需要，可全部切国内镜像。

### npm（前端依赖）

```bash
npm config set registry https://registry.npmmirror.com     # 淘宝镜像（推荐）
# 或临时： npm install --registry=https://registry.npmmirror.com
```

### pip（Python 依赖）

```bash
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple   # 清华
# 备选： https://mirrors.aliyun.com/pypi/simple（阿里） / https://mirrors.cloud.tencent.com/pypi/simple（腾讯）
```

### HuggingFace 权重（首次部署必做：发布包不含权重）

```bash
# 推荐：用随包脚本下载（走国内镜像，支持断点续传）
python RADAR_inference/scripts/download_weights.py --preset main
```

需下载的权重见 README「获取模型权重」。文本嵌入（约 440 KB）随包分发，
官方 HuggingFace 权重库**不含**这两个文件，无需也无法从此渠道下载。

### Playwright Chromium（仅 UI 自动化验证用，产品不需要）

```bash
export PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright
```

---

## 五、回归清单

改动网络相关行为后，至少跑通以下三项：

```bash
cd RADAR_inference
python scripts/smoke_test.py --base http://127.0.0.1:8124   # 33 项契约 + 数值红线
python scripts/netprobe.py main radar146                    # 离线守卫：main
python scripts/netprobe.py plus merlin20                    # 离线守卫：plus
```

注意：本机 shell 可能配置了 `http_proxy`（如 `127.0.0.1:5xxxx`），
`curl` 探活本机服务会被代理劫持返回伪装成 502 的响应，须加 `--noproxy '*'`。
`smoke_test.py` 已内置 `Session(trust_env=False)` 规避该问题。
