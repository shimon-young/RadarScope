# RadarScope 前后端 API 契约（v1.0）

> **唯一权威定义**：`RADAR_inference/radar/schemas.py`（Pydantic v2）。
> TS 镜像：`frontend/src/api/types.ts`。
> 任何字段增删改必须同步三处：`schemas.py`、`types.ts`、本文件。

- `schema_version`: `1.0`（响应体均携带）
- 基址：`http://127.0.0.1:8000`（单机模式）/ `http://<局域网IP>:8000`（局域网模式）
- 媒体类型：JSON（UTF-8，禁止 NaN/Inf 字面量）；文件传输 `multipart/form-data`
- 认证：无（本地单机应用）

---

## 0. 核心设计约定（勿违背）

1. **阈值过滤在前端**：服务端不做阈值过滤，`findings` 全量下发（146/20 项）。
   `Finding.positive` 只是按提交时阈值算好的参考值；前端用本地阈值即时重算。
2. **概率必须是有限数**：非有限值一律置 `prob: null`，并在 `input.warnings` 记录，
   绝不允许 NaN 出现在 JSON 中（NaN 不是合法 JSON）。
3. **SSE 只推轻量帧**：完成事件只带摘要，完整 findings 由前端再拉 `/result`。
4. **任务化**：推理一律走异步任务（单并发队列），HTTP 请求绝不阻塞在推理上。
5. **掩膜坐标空间**：分割掩膜 NIfTI 默认以 `space=ras` 下发（与 Cornerstone3D
   nifti-volume-loader 同空间）；`space=native` 返回服务端落盘的原件。

---

## 1. 端点总览

| 方法 | 路径 | 说明 | 成功响应 |
|---|---|---|---|
| GET | `/api/system` | 系统/引擎/权重/磁盘状态 | `SystemInfo` |
| POST | `/api/jobs` | 上传 NIfTI 创建任务 | 202 + `JobMeta` |
| GET | `/api/jobs?cursor=&limit=` | 历史列表（游标分页） | `JobList` |
| GET | `/api/jobs/{id}` | 任务快照 | `JobMeta` |
| GET | `/api/jobs/{id}/events` | SSE 进度流 | `text/event-stream` |
| GET | `/api/jobs/{id}/result` | 完整结果 | `JobResult` |
| GET | `/api/jobs/{id}/input` | 回传原始上传的 NIfTI | `application/gzip` |
| GET | `/api/jobs/{id}/segmentation?space=ras` | 分割掩膜 NIfTI | `application/gzip` |

> **`.nii.gz` 后缀别名**：上述两个端点同时接受 `/input.nii.gz` 与
> `/segmentation.nii.gz`。前端必须使用带后缀的 URL——Cornerstone3D 的
> NIfTI loader 以 URL 后缀判断 gzip，后缀缺失会导致头解析失败、体积加载挂死。
> `artifacts.input_url` 与 `segmentation.url` 下发的已是带后缀版本。
| POST | `/api/jobs/{id}/cancel` | 取消任务 | `JobMeta` |
| DELETE | `/api/jobs/{id}` | 删除任务及产物 | 204 |

### 1.1 POST /api/jobs

`multipart/form-data`：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `file` | file | 必填 | `.nii.gz`（MVP 仅 NIfTI，推荐门脉期增强腹部 CT） |
| `model_type` | str | `main` | `main`（146 项全面筛查）\| `plus`（20 项 MERLIN 急诊协议） |
| `device` | str | `auto` | `auto` \| `gpu` \| `cpu` |
| `precision` | str | `auto` | `auto` \| `bf16` \| `fp16` \| `fp32` |
| `threshold` | float | `0.5` | 仅用于服务端预置 `positive` 标记；**该默认值未经官方标定**（官方只发布 AUC，未给出工作点），需在自有标注数据上确定 |
| `save_segmentation` | bool | `true` | 是否生成分割掩膜 |

#### 模型、权重与文本嵌入的对应关系

| model_type | 输出项 | 权重文件 | 文本嵌入 | 文本编码器 |
|---|---|---|---|---|
| `main` | 146 项 | `checkpoint_radar_pretrain.pth` | `infer_text_embedding_radar.pt`（官方发布） | 中文 `bert-base-chinese`（21128） |
| `plus` | 20 项 | `checkpoint_radar_plus_finetuned_on_merlin.pth` | `infer_text_embedding_merlin_en.pt`（现算） | 英文 `bert-base-uncased`（30522） |

- 测试项集合由模型决定，不接受客户端指定。
- 两个文本编码器语言不同、词表不同，**不可混用**：配错会让整层 text_encoder
  （199 个参数）在 `strict=False` 下被静默丢弃。
- plus 必须用 `merlin_en.pt`（按 MERLIN 官方提示词现算），**不能**用官方同名的
  `infer_text_embedding_merlin.pt`——后者属「中文 BERT + main 权重」空间，
  配给 plus 不会报错，只会静默产出错误概率。嵌入的 key 均为中文项名，
  故 `findings[].key` 始终是中文。

行为：
- 校验失败 → `400/413/415` + `ErrorBody`；磁盘不足 → `507`。
- `job_id` 为服务端生成的 12 位十六进制串；所有路径参数按 `^[0-9a-f]{12}$`
  白名单校验，格式不符 → `400 BAD_REQUEST`，格式合法但不存在 → `404 NOT_FOUND`。
- CORS：前端由本服务同源托管，生产无跨域需求；仅放行本地 Vite 开发端口
  （`localhost:5173/5174`），不对 `*` 开放。
- 成功 → `202`，body 为初始 `JobMeta`（`state=queued`）。
- 排队语义：单飞（同一时刻至多 1 个任务在推理），其余排队，`queue_position` 可见。

### 1.2 GET /api/jobs/{id}/events（SSE）

`data:` 帧为以下三者之一（与 `schemas.py` 对应）：

- `ProgressEvent`：`state`/`progress`/`stage`/`message`/`queue_position`/`eta_s`
- `ResultEvent`：`done` 时一次，仅摘要（`positive_count`/`max_prob`/`total_s`）
- `ErrorEvent`：`failed`/`cancelled` 时一次，含 `ErrorBody`

状态机：`queued → preprocessing → sliding_window → postprocessing → finalizing → done`
（任意非终态可转 `failed` / `cancelled`；终态后 SSE 关闭）。
断线重连：重新 GET 该端点从当前状态续推（不补历史帧；快照以 `JobMeta` 为准）。

### 1.3 错误响应

所有非 2xx 响应 body 为 `ErrorBody`：

```json
{
  "code": "BAD_REQUEST | NOT_FOUND | PAYLOAD_TOO_LARGE | UNSUPPORTED_MEDIA | INVALID_IMAGE | INSUFFICIENT_STORAGE | WEIGHTS_MISSING | CONFLICT | CANCELLED | INTERNAL",
  "message": "人类可读描述（中文）",
  "detail": {},
  "request_id": "可选",
  "retryable": false
}
```

HTTP 映射：400→`BAD_REQUEST`/`INVALID_IMAGE`，404→`NOT_FOUND`，409→`CONFLICT`，
413→`PAYLOAD_TOO_LARGE`，415→`UNSUPPORTED_MEDIA`，507→`INSUFFICIENT_STORAGE`，
500→`INTERNAL`。`INSUFFICIENT_STORAGE` 同时覆盖 CUDA OOM 与磁盘不足（`retryable` 可为 true）。

---

## 2. 关键结构速览（权威以 schemas.py 为准）

### JobResult（核心载荷）

```
schema_version, job_id, state="done", created_at, finished_at
input      : InputMeta   （文件名/尺寸/spacing/origin/direction/警告）
engine     : EngineInfo  （model_type/items_mode/item_count/device/precision/torch/…/text_features）
threshold  : ThresholdInfo（default=0.5, applied_on="client"）
timing     : TimingInfo  （preprocess/sliding_window/postprocess/segmentation/total 秒）
findings[] : Finding     （key/organ/organ_en/finding/finding_en/prob/positive）
organ_summary[] : OrganSummary（organ/max_prob/positive_count/total_count）
segmentation    : SegmentationInfo（available/url/format/dimensions/spacing_mm/labels[index,organ,color,voxel_count]）
artifacts  : Artifacts   （result_url/csv_url/log_url/input_url）
```

- `artifacts.input_url`：回传原始上传 NIfTI。用途**仅限**「重开历史任务」——
  上个月/上次会话的任务在浏览器里没有本地 File 对象，不提供此端点则无法重建 MPR 视图。

- `findings[].key`：原始「器官_病症」中文键（如 `肝_肝囊肿`），main 为 146 项、
  plus 为 20 项（键如 `肝_肝大`）。数量以 `engine.item_count` 为准；该字段对历史任务可能为
  `null`（写于该字段出现之前），此时前端以 `findings.length` 为准。
- `segmentation.labels[].index`：label 1..36，与 `radar/engine/items.py` 的 `ORGANS` 顺序一致
  （label = 数组下标 + 1，**顺序冻结，不得改动**）。
- `segmentation.labels[].color`：后端下发的 RGB 色板；前端仅存兜底默认值。

### JobState 生命周期

`queued / preprocessing / sliding_window / postprocessing / finalizing / done / failed / cancelled`
终态：`done`、`failed`、`cancelled`（不可再迁移）。

---

## 3. 前端消费要点

1. 上传后保存 `job_id`，订阅 `/events`；收到 `ResultEvent` 后拉 `/result` 渲染。
2. 阈值滑杆只改本地过滤，不触发任何请求。
3. 掩膜加载：`segmentation.url` 直接喂给 Cornerstone3D `nifti-volume-loader`，
   与 CT 同几何（同 size/spacing/origin/direction），labelmap 派生体直接逐体素拷贝。
4. 所有 `prob` 先做 `null` 检查再参与排序/过滤。
5. 错误处理：`retryable=true` 时 UI 提供「重试」；`INSUFFICIENT_STORAGE` 提示降精度/换 CPU。

---

## 4. 兼容性

- 前端应在启动时请求 `/api/system`，比对 `version` 与自身期望的 `schema_version` 大版本；
  不一致时给出明确提示（绿色版前后端同包分发，正常情况恒一致）。
- 字段只增不删；删除/改名必须升 `schema_version` 大版本。
