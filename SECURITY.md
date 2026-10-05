# 安全与隐私政策

## 医疗数据

任何患者影像、诊断报告、DICOM 元数据、病理切片，无论是否脱敏，
**都不得提交到本仓库**，也不得放进 Issue、Pull Request 或 Release 附件。

包括看似无害的：

- 官方 demo 病例（`data/demo_cases/`）—— 那是**真实患者影像**，已在 `.gitignore` 中排除
- 从医院或公开数据集导出的任何子集
- 截图中出现的患者姓名、住院号、检查号、日期

## 已内置的防护

| 防护 | 位置 |
|---|---|
| 患者影像目录排除 | `.gitignore` → `data/demo_cases/` |
| 管理员凭据排除 | `.gitignore` → `results/`（内含 `admin_auth.json`） |
| 打包时二次拦截 | `pack_release.ps1` 白名单 + 压缩后复检 zip 条目 |
| 持续集成校验 | `Package Integrity` 工作流检查敏感内容未被追踪 |

`pack_release.ps1` 在压缩完成后会重新打开 zip 检查，发现权重、患者数据或虚拟环境
即中止并删除产物。`Package Integrity` 工作流在每次 push 时独立复查仓库中是否
出现医疗影像、管理员凭据或模型权重。

## 如果你已经误提交了

1. 停止继续 push
2. 私下联系维护者
3. 注意：**删除文件不够** —— git 历史里仍然存在。若已推送到公开仓库，
   需重写历史（`git filter-repo` 或 BFG），并视情况联系 GitHub Support
   申请清除缓存副本

## 发现的漏洞

安全相关问题请**不要**开公开 Issue。请通过 GitHub 的
[私密漏洞报告](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
功能私下报告。

## 免责声明

本项目仅供科研、教学与算法评估，**不得用于临床诊断**。模型表现仍需前瞻性临床研究验证。
