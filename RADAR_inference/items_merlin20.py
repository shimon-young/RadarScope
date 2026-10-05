# -*- coding: utf-8 -*-
"""Merlin 协议 20 项「器官_病症」清单（plus 模型的标准输出项）。

来源（唯一权威）：
- 项名顺序：`ckpt/infer_text_embedding_merlin.pt` 的 key 顺序（官方原文件与
  现算版 `infer_text_embedding_merlin_en.pt` 使用同一套 key，顺序一致）
- 英文项名：`RADAR_inference/inference_merlin_testset.py` 的 `map_radar_merlin`

关于「不是 21 项」：官方 `test_items` 列出 21 项，但推理主循环里显式
`organ_logits.pop('胆囊_术后胆囊缺失')` 剔除该项（surgically_absent_gallbladder
须另按协议处理），故实际评分为 **20 项**，与文本嵌入文件的 20 个 key 一一对应。

关于「用哪份嵌入」：plus 的文本编码器是英文 BERT、在英文 MERLIN 报告上训练，
必须用 MERLIN 官方提示词现算的 `infer_text_embedding_merlin_en.pt`。
官方随包发布的 `infer_text_embedding_merlin.pt` 属「中文 BERT + main 权重」空间，
配给 plus 会静默失效（不报错，但概率错误）。两者的 key 与本清单一致。

重要约束（已断言）：
- 20 项只覆盖 12 个器官，且**全部在 36 个分割器官表内**——
  `RADAR.forward_test_win` 以器官名匹配分割 token，器官不在表内则该项永不评分。
- 这 20 项中有 5 项不在 146 项表内（如 `大肠_粘膜下水肿`、`肾_肾积水`），
  因此不能复用 `items146.ENGLISH_MAPPING`，必须有本套独立映射。
"""

# ── 20 项「器官_病症」（顺序与文本嵌入文件一致，勿随意重排）──
MERLIN20_ITEMS = (
    '主动脉_主动脉瘤',
    '主动脉_粥样硬化',
    '大肠_粘膜下水肿',
    '大肠_阑尾炎',
    '小肠_梗阻',
    '心脏_主动脉瓣钙化',
    '心脏_心影（脏）增大',
    '肝_肝内胆管扩张',
    '肝_肝大',
    '肝_脂肪肝',
    '肺_胸腔积液',
    '肺_膨胀不全',
    '肾_低密度影',
    '肾_囊肿',
    '肾_肾积水',
    '胆囊_结石',
    '胰腺_萎缩',
    '脾_脾大',
    '腰椎_骨折',
    '食管_裂孔疝',
)

# ── 中文项名 → Merlin 协议英文项名 ──
MERLIN20_ENGLISH = {
    '主动脉_主动脉瘤': 'abdominal_aortic_aneurysm',
    '主动脉_粥样硬化': 'atherosclerosis',
    '大肠_粘膜下水肿': 'submucosal_edema',
    '大肠_阑尾炎': 'appendicitis',
    '小肠_梗阻': 'bowel_obstruction',
    '心脏_主动脉瓣钙化': 'aortic_valve_calcification',
    '心脏_心影（脏）增大': 'cardiomegaly',
    '肝_肝内胆管扩张': 'biliary_ductal_dilation',
    '肝_肝大': 'hepatomegaly',
    '肝_脂肪肝': 'hepatic_steatosis',
    '肺_胸腔积液': 'pleural_effusion',
    '肺_膨胀不全': 'atelectasis',
    '肾_低密度影': 'renal_hypodensities',
    '肾_囊肿': 'renal_cyst',
    '肾_肾积水': 'hydronephrosis',
    '胆囊_结石': 'gallstones',
    '胰腺_萎缩': 'pancreatic_atrophy',
    '脾_脾大': 'splenomegaly',
    '腰椎_骨折': 'fracture',
    '食管_裂孔疝': 'hiatal_hernia',
}

# 参与评分的器官（20 项涉及的 12 个器官，须为 36 器官表的子集）
MERLIN20_ORGANS = ('主动脉', '大肠', '小肠', '心脏', '肝', '肺', '肾',
                   '胆囊', '胰腺', '脾', '腰椎', '食管')

if __name__ == '__main__':
    assert len(MERLIN20_ITEMS) == 20, 'Merlin 标准输出必须恰好 20 项'
    assert len(MERLIN20_ENGLISH) == 20
    assert set(MERLIN20_ITEMS) == set(MERLIN20_ENGLISH), '中英文表键必须一致'
    assert len(set(MERLIN20_ITEMS)) == 20, '项名不可重复'
    assert set(MERLIN20_ORGANS) == {i.split('_')[0] for i in MERLIN20_ITEMS}
    print('merlin20 自检通过：20 项 /', len(MERLIN20_ORGANS), '个器官')

# 中文项 → merlin_prompts.disease_prompts 的键（官方报告式正/负短语表；
# 与 infer_plus_bf16.CN_TO_PROMPT 同源，收编至此作唯一数据源）
MERLIN20_PROMPT_KEYS = {
    '主动脉_主动脉瘤': 'aortic_aneurysm', '主动脉_粥样硬化': 'atherosclerosis',
    '大肠_粘膜下水肿': 'submucosal_edema', '大肠_阑尾炎': 'appendicitis',
    '小肠_梗阻': 'bowel_obstruction', '心脏_主动脉瓣钙化': 'aortic_valve_calcification',
    '心脏_心影（脏）增大': 'cardiomegaly', '肝_肝内胆管扩张': 'biliary_ductal_dilation',
    '肝_肝大': 'hepatomegaly', '肝_脂肪肝': 'hepatic_steatosis',
    '肺_胸腔积液': 'pleural_effusion', '肺_膨胀不全': 'atelectasis',
    '肾_低密度影': 'renal_hypodensities', '肾_囊肿': 'renal_cyst',
    '肾_肾积水': 'hydronephrosis', '胆囊_结石': 'gallstones',
    '胰腺_萎缩': 'pancreatic_atrophy', '脾_脾大': 'splenomegaly',
    '腰椎_骨折': 'fracture', '食管_裂孔疝': 'hiatal_hernia',
}
