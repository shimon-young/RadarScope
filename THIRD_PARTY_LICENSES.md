# Third-Party Licenses

This project bundles or derives from the following open-source software. Their
original copyright notices and license terms are reproduced below.

**最重要的边界不在下面这些许可，而在本项目自身的许可证**：本仓库以
`CC BY-NC-SA 4.0`（见根目录 `LICENSE`）发布，即 **非商业性使用（NonCommercial）+
相同方式共享（ShareAlike）**。任何商业性使用（收费部署、对外服务、嵌入商业产品等）
都需要先取得版权方授权；对代码做出修改后再分发，衍生作品须同样以 CC BY-NC-SA 4.0
发布。模型权重（ckpt/）同样适用该许可。

以下第三方组件的许可均为宽松型许可（BSD-3-Clause / Apache-2.0 / MIT），
在遵守「保留版权与许可声明」义务的前提下允许使用、修改与再分发。

---

## LAVIS

- Source: https://github.com/salesforce/LAVIS
- License: BSD 3-Clause License（已核对上游仓库 README 的 License 章节）
- 说明：`RADAR_inference/dynamic_network_architectures/med.py` 来自本项目，
  保留在该目录仅因 RADAR 的 import 路径从此处引用。

```
BSD 3-Clause License

Copyright (c) 2022, Salesforce.com, Inc.
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

---

## nnU-Net / dynamic-network-architectures

- Source: https://github.com/MIC-DKFZ/nnUNet , https://github.com/MIC-DKFZ/dynamic-network-architectures
- License: Apache License 2.0
- 完整许可文本：本目录下的 `RADAR_inference/dynamic_network_architectures/LICENSE`
  与 `NOTICE`（NOTICE 已按 Apache-2.0 §4(d) 记录 vendored 事实与本地修改点）

> **许可边界（重要）**：`dynamic_network_architectures/` 目录整体**不适用**本项目的
> CC BY-NC-SA 4.0，而沿用其上游许可（Apache-2.0；其中 `med.py` 为 LAVIS 的
> BSD-3-Clause）。CC BY-NC-SA 4.0 只覆盖 RadarScope 自身的代码与文档。
> 三者均为宽松许可，可同时出现在同一分发包中；若修改并再分发 Apache-2.0 部分，
> 必须保留其 `LICENSE`/`NOTICE` 并按 §4(b) 标注改动——本项目已照此执行。

## MONAI

- Source: https://github.com/Project-MONAI/MONAI
- License: Apache License 2.0

The full text of the Apache License 2.0 (shared by nnU-Net and MONAI) is
available at http://www.apache.org/licenses/LICENSE-2.0 and reproduced below.

```
                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/

   TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION

   1. Definitions.

      "License" shall mean the terms and conditions for use, reproduction,
      and distribution as defined by Sections 1 through 9 of this document.

      "Licensor" shall mean the copyright owner or entity authorized by
      the copyright owner that is granting the License.

      "Legal Entity" shall mean the union of the acting entity and all
      other entities that control, are controlled by, or are under common
      control with that entity. For the purposes of this definition,
      "control" means (i) the power, direct or indirect, to cause the
      direction or management of such entity, whether by contract or
      otherwise, or (ii) ownership of fifty percent (50%) or more of the
      outstanding shares, or (iii) beneficial ownership of such entity.

      "You" (or "Your") shall mean an individual or Legal Entity
      exercising permissions granted by this License.

      "Source" form shall mean the preferred form for making modifications,
      including but not limited to software source code, documentation
      source, and configuration files.

      "Object" form shall mean any form resulting from mechanical
      transformation or translation of a Source form, including but
      not limited to compiled object code, generated documentation,
      and conversions to other media types.

      "Work" shall mean the work of authorship, whether in Source or
      Object form, made available under the License, as indicated by a
      copyright notice that is included in or attached to the work
      (an example is provided in the Appendix below).

      "Derivative Works" shall mean any work, whether in Source or Object
      form, that is based on (or derived from) the Work and for which the
      editorial revisions, annotations, elaborations, or other modifications
      represent, as a whole, an original work of authorship. For the purposes
      of this License, Derivative Works shall not include works that remain
      separable from, or merely link (or bind by name) to the interfaces of,
      the Work and Derivative Works thereof.

      "Contribution" shall mean any work of authorship, including
      the original version of the Work and any modifications or additions
      to that Work or Derivative Works thereof, that is intentionally
      submitted to Licensor for inclusion in the Work by the copyright owner
      or by an individual or Legal Entity authorized to submit on behalf of
      the copyright owner. For the purposes of this definition, "submitted"
      means any form of electronic, verbal, or written communication sent
      to the Licensor or its representatives, including but not limited to
      communication on electronic mailing lists, source code control systems,
      and issue tracking systems that are managed by, or on behalf of, the
      Licensor for the purpose of discussing and improving the Work, but
      excluding communication that is conspicuously marked or otherwise
      designated in writing by the copyright owner as "Not a Contribution."

      "Contributor" shall mean Licensor and any individual or Legal Entity
      on behalf of whom a Contribution has been received by Licensor and
      subsequently incorporated within the Work.

   2. Grant of Copyright License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      copyright license to reproduce, prepare Derivative Works of,
      publicly display, publicly perform, sublicense, and distribute the
      Work and such Derivative Works in Source or Object form.

   3. Grant of Patent License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      (except as stated in this section) patent license to make, have made,
      use, offer to sell, sell, import, and otherwise transfer the Work,
      where such license applies only to those patent claims licensable
      by such Contributor that are necessarily infringed by their
      Contribution(s) alone or by combination of their Contribution(s)
      with the Work to which such Contribution(s) was submitted. If You
      institute patent litigation against any entity (including a
      cross-claim or counterclaim in a lawsuit) alleging that the Work
      or a Contribution incorporated within the Work constitutes direct
      or contributory patent infringement, then any patent licenses
      granted to You under this License for that Work shall terminate
      as of the date such litigation is filed.

   4. Redistribution. You may reproduce and distribute copies of the
      Work or Derivative Works thereof in any medium, with or without
      modifications, and in Source or Object form, provided that You
      meet the following conditions:

      (a) You must give any other recipients of the Work or Derivative
          Works a copy of this License; and

      (b) You must cause any modified files to carry prominent notices
          stating that You changed the files; and

      (c) You must retain, in the Source form of any Derivative Works
          that You distribute, all copyright, patent, trademark, and
          attribution notices from the Source form of the Work,
          excluding those notices that do not pertain to any part of
          the Derivative Works; and

      (d) If the Work includes a "NOTICE" text file as part of its
          distribution, then any Derivative Works that You distribute must
          include a readable copy of the attribution notices contained
          within such NOTICE file, excluding those notices that do not
          pertain to any part of the Derivative Works, in at least one
          of the following places: within a NOTICE text file distributed
          as part of the Derivative Works; within the Source form or
          documentation, if provided along with the Derivative Works; or,
          within a display generated by the Derivative Works, if and
          wherever such third-party notices normally appear. The contents
          of the NOTICE file are for informational purposes only and do
          not modify the License. You may add Your own attribution notices
          within Derivative Works that You distribute, alongside or as an
          addendum to the NOTICE text from the Work, provided that such
          additional attribution notices cannot be construed as modifying
          the License.

      You may add Your own copyright statement to Your modifications and
      may provide additional or different license terms and conditions
      for use, reproduction, or distribution of Your modifications, or
      for any such Derivative Works as a whole, provided Your use,
      reproduction, and distribution of the Work otherwise complies with
      the conditions stated in this License.

   5. Submission of Contributions. Unless You explicitly state otherwise,
      any Contribution intentionally submitted for inclusion in the Work
      by You to the Licensor shall be under the terms and conditions of
      this License, without any additional terms or conditions.
      Notwithstanding the above, nothing herein shall supersede or modify
      the terms of any separate license agreement you may have executed
      with Licensor regarding such Contributions.

   6. Trademarks. This License does not grant permission to use the trade
      names, trademarks, service marks, or product names of the Licensor,
      except as required for reasonable and customary use in describing the
      origin of the Work and reproducing the content of the NOTICE file.

   7. Disclaimer of Warranty. Unless required by applicable law or
      agreed to in writing, Licensor provides the Work (and each
      Contributor provides its Contributions) on an "AS IS" BASIS,
      WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
      implied, including, without limitation, any warranties or conditions
      of TITLE, NON-INFRINGEMENT, MERCHANTABILITY, or FITNESS FOR A
      PARTICULAR PURPOSE. You are solely responsible for determining the
      appropriateness of using or redistributing the Work and assume any
      risks associated with Your exercise of permissions under this License.

   8. Limitation of Liability. In no event and under no legal theory,
      whether in tort (including negligence), contract, or otherwise,
      unless required by applicable law (such as deliberate and grossly
      negligent acts) or agreed to in writing, shall any Contributor be
      liable to You for damages, including any direct, indirect, special,
      incidental, or consequential damages of any character arising as a
      result of this License or out of the use or inability to use the
      Work (including but not limited to damages for loss of goodwill,
      work stoppage, computer failure or malfunction, or any and all
      other commercial damages or losses), even if such Contributor
      has been advised of the possibility of such damages.

   9. Accepting Warranty or Additional Liability. While redistributing
      the Work or Derivative Works thereof, You may choose to offer,
      and charge a fee for, acceptance of support, warranty, indemnity,
      or other liability obligations and/or rights consistent with this
      License. However, in accepting such obligations, You may act only
      on Your own behalf and on Your sole responsibility, not on behalf
      of any other Contributor, and only if You agree to indemnify,
      defend, and hold each Contributor harmless for any liability
      incurred by, or claims asserted against, such Contributor by reason
      of your accepting any such warranty or additional liability.

   END OF TERMS AND CONDITIONS
```

---

## 3D-ResNets-PyTorch

- Source: https://github.com/kenshohara/3D-ResNets-PyTorch
- License: MIT License

```
MIT License

Copyright (c) 2017 Kensho Hara

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 前端打包产物（`frontend/dist/`，随包分发的已构建 JS/CSS）

`frontend/dist/assets/*.js` 是构建产物，其中**内嵌**了以下第三方组件的代码。
这些声明原文保留在 bundle 内（未做 strip），本节仅作索引：

| 组件 | 许可 | 在 bundle 中的声明 | 上游 |
|---|---|---|---|
| Cornerstone3D / Cornerstone Tools | MIT | `@license` + `Cornerstone3D` / `Cornerstone3DTools` 标识 | https://github.com/cornerstonejs/cornerstone3D |
| VTK.js 相关（vtk.js 源自 VTK） | BSD-3-Clause | `Copyright (c) Ken Martin, Will Schroeder, Bill Lorensen` | https://kitware.github.io/vtk-js/ |
| Google LLC 贡献片段 | Apache-2.0 | `Copyright 2019 Google LLC` | — |
| pako 等小工具 | `(MIT AND Zlib)` | `@license (MIT AND Zlib)` | 见 npm 上游 |

上述均为宽松许可，允许再分发。**MIT 与 BSD-3-Clause 的核心义务是保留版权与许可声明**——
本包通过在 bundle 内保留原始 `@license` / `Copyright` 行来履行；若后续重新构建前端，
请确认构建工具未 strip 这些注释（部分压缩配置会移除 `legalComments`）。

> Cornerstone3D 的完整 MIT 许可文本可在其 npm 包
> （`@cornerstonejs/core`）与上游仓库 `LICENSE` 获取。若你希望分发物内附完整
> MIT 文本，可把 `node_modules/@cornerstonejs/core/LICENSE` 复制到
> `frontend/dist/` 下。

---

## 运行时依赖中的 LGPL-3.0 组件（弱 copyleft，需单独留意）

上述四个模块是**源码层面**的引用/改写；除此之外，运行期依赖链中还有 4 个以
**LGPL-3.0-or-later** 发布的组件，经 nnU-Net 后处理链路
（`acvl_utils.morphology`）被间接加载：

| 组件 | 版本 | 许可 | 上游 |
|---|---|---|---|
| connected-components-3d | 3.26.1 | LGPL-3.0-or-later | https://github.com/seung-lab/connected-components-3d |
| fastremap | 1.19.0 | LGPL-3.0 | https://github.com/seung-lab/fastremap |
| fill-voids | 2.1.2 | LGPL-3.0-or-later | https://github.com/seung-lab/fill-voids |
| edt | 3.0.0 | LGPL-3.0-or-later | https://github.com/seung-lab/edt |

LGPL 是**弱 copyleft**：不会把许可传染到本项目自身的代码，但在分发时要求：

1. 随分发物提供这些组件的许可文本（或在文档中给出获取方式）；
2. 提供这些组件**源码的可得性**（提供源码，或提供书面索取方式）；
3. 不得将 LGPL 组件静态链接进闭源产物，须保证接收者能够替换/重新链接该库。

本分发包不再内置 Python 环境，这些组件由部署脚本在用户端从 PyPI 安装
（wheel 为可替换的动态链接库），上述 2、3 条义务在用户侧天然满足；
分发包仍应保留本节清单以履行第 1 条。

> 其余核心运行时依赖均为宽松许可：torch (BSD-3-Clause)、transformers /
> timm / nnunetv2 / MONAI / torchio / SimpleITK / medim / acvl_utils
> (Apache-2.0)、numpy / scipy / pandas / blosc2 / imagecodecs (BSD-3-Clause)、
> nibabel / pydicom / deepbet (MIT)。其中 opencv-python-headless 的 wheel
> 内含自己的第三方组件清单（`LICENSE-3RD-PARTY.txt`），如深度分发需一并保留。
