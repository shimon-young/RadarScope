# 安全与隐私政策

## 绝不提交任何医疗数据

**这是本项目最硬的红线。** 任何患者影像、诊断报告、DICOM 元数据、病理切片，
无论是否脱敏，**都不得提交到本仓库**，也不得放进 Issue、Pull Request 或 Release 附件。

包括看似无害的：

- 官方 demo 病例（`data/demo_cases/`）—— 那是**真实患者影像**，已在 `.gitignore` 中排除
- 从医院或公开数据集导出的任何子集
- 截图中出现的患者姓名、住院号、检查号、日期

## 已内置的防护

| 防护 | 位置 |
|---|---|
| 患者影像目录排除 | `.gitignore` → `data/demo_cases/` |
| 打包时二次拦截 | `pack_release.ps1` 白名单 + 压缩后复检 zip 条目 |
| 一致性校验 | 打包时校验「zip 内文件都被 git 追踪」，同时反查敏感项 |
| 管理员凭据排除 | `.gitignore` → `results/`（内含 `admin_auth.json`） |

`pack_release.ps1` 在压缩完成后会重新打开 zip 检查，发现权重、患者数据或虚拟环境
就直接**中止并删除产物**。发布前请务必运行它，不要直接压缩源目录。

## 如果你已经误提交了

1. **立刻停止**继续 push
2. 告诉我（开私密 Issue 或直接联系维护者），我会协助清理
3. 注意：**仅仅删除文件不够** —— git 历史里仍然存在。若已推送到公开仓库，
   需要重写历史（`git filter-repo` 或 BFG），并视情况联系 GitHub Support
   申请清除缓存副本

## 发现的漏洞

安全相关问题请**不要**开公开 Issue。请通过 GitHub 的
[私密漏洞报告](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
功能私下报告。

## 免责声明

本项目仅供科研、教学与算法评估，**不得用于临床诊断**。模型表现仍需前瞻性临床研究验证。
