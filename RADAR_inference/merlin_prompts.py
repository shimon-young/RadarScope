from typing import Any, Callable, List, Sequence, Tuple, Union

from dataclasses import dataclass

@dataclass
class DiseasePrompts:
    disease_name: str
    region: str
    positive_prompts: List[str]
    negative_prompts: List[str]

disease_prompts = {}

prompts = DiseasePrompts(disease_name='submucosal_edema', region='large bowel', positive_prompts=['mild diffuse submucosal edema', 'mild diffuse submucoasal edema', 'scattered areas of submucosal edema', 'mild submucosal edema', 'with submucosal edema', 'demonstrates submucosal edema', 'marked submucosal edema', 'there is submucosal edema', 'diffuse submucosal edema'], negative_prompts=['bowel : normal', 'no submucosal edema'])

disease_prompts['submucosal_edema'] = prompts

prompts = DiseasePrompts(disease_name='renal_hypodensities', region='kidney', positive_prompts=['kidneys and ureters : subcentimeter hypodensities', 'kidneys and ureters : 2 subcentimeter hypodensities', 'kidneys and ureters : two hypodensities', 'kidneys and ureters : small hypodensities', 'kidneys and ureters : hypodensities', 'bilateral renal hypodensities', 'subcentimeter renal hypodensities', 'multiple renal hypodensities', 'right renal hypodensities', 'left renal hypodensities'], negative_prompts=[' kidneys and ureters : normal'])

disease_prompts['renal_hypodensities'] = prompts

prompts = DiseasePrompts(disease_name='aortic_valve_calcification', region='heart', positive_prompts=['aortic valvular calcification', 'coronary artery and aortic valvular calcifications', 'aortic valve calcification'], negative_prompts=['vasculature : normal'])

disease_prompts['aortic_valve_calcification'] = prompts

prompts = DiseasePrompts(disease_name='pancreatic atrophy', region='pancreas', positive_prompts=['parenchymal atrophy', 'renal atrophy', 'pancreatic atrophy', 'atrophy of the pancreas', 'pancreas : severe atrophy', 'pancreas : diffuse atrophy', 'pancreas : fatty atrophy', 'pancreas : mild fatty atrophy', 'pancreas : diffuse fatty atrophy'], negative_prompts=['pancreas : normal'])

disease_prompts['pancreatic_atrophy'] = prompts

prompts = DiseasePrompts(disease_name='renal_cyst', region='kidney', positive_prompts=['renal cyst', 'bilateral renal cysts', 'simple renal cyst', 'multiple renal cysts', 'left renal cyst', 'right renal cyst', 'represent renal cyst', 'representing renal cyst', 'reflect renal cyst'], negative_prompts=['kidneys : normal', 'kidneys and ureters : normal'])

disease_prompts['renal_cyst'] = prompts

prompts = DiseasePrompts(disease_name='atelectasis', region='lung', positive_prompts=['lower lobe atelectasis', 'bibasilar atelectasis', 'basilar passive atelectasis', 'mild bibasilar dependent atelectasis', 'mild dependent atelectasis', 'compatible with atelectasis', 'consistent with atelectasis'], negative_prompts=['lower thorax : normal .'])

disease_prompts['atelectasis'] = prompts

prompts = DiseasePrompts(disease_name='aortic aneurysm', region='aorta', positive_prompts=['infrarenal abdominal aortic aneurysm', 'the abdominal aortic aneurysm', 'abdominal aortic aneurysm , measuring', 'abdominal aortic aneurysm with', 'aortic aneurysm measures', 'aortic aneurysm measuring', 'aortic aneurysm with'], negative_prompts=['no aortic aneurysm', 'no abdominal aortic aneurysm', 'without abdominal aortic aneurysm'])

disease_prompts['aortic_aneurysm'] = prompts

prompts = DiseasePrompts(disease_name='hiatal_hernia', region='esophagus', positive_prompts=['small hiatal hernia', 'moderate sized hiatal hernia', 'moderate hiatal hernia', 'large hiatal hernia', 'small hiatus hernia'], negative_prompts=['no hernia', 'abdominal wall : normal .'])

disease_prompts['hiatal_hernia'] = prompts

prompts = DiseasePrompts(disease_name='biliary ductal dilation', region='liver', positive_prompts=['moderate biliary ductal dilation', 'mild biliary ductal dilation', 'severe biliary ductal dilation', 'mild intrahepatic biliary ductal dilation', 'severe intrahepatic biliary ductal dilation', 'moderate intrahepatic biliary ductal dilation', 'mild extrahepatic biliary ductal dilation', 'severe extrahepatic biliary ductal dilation', 'moderate extrahepatic biliary ductal dilation'], negative_prompts=['no biliary ductal dilation', 'no intrahepatic biliary ductal dilation', 'no extrahepatic biliary ductal dilation', 'no intra - or extrahepatic biliary ductal dilation', 'no intrahepatic or extrahepatic biliary ductal dilation'])

disease_prompts['biliary_ductal_dilation'] = prompts

prompts = DiseasePrompts(disease_name='cardiomegaly', region='heart', positive_prompts=['severe cardiomegaly', 'marked cardiomegaly', 'moderate cardiomegaly', 'mild cardiomegaly', '. cardiomegaly', 'the heart is enlarged'], negative_prompts=['no cardiomegaly', 'the heart is normal in size'])

disease_prompts['cardiomegaly'] = prompts

prompts = DiseasePrompts(disease_name='splenomegaly', region='spleen', positive_prompts=['severe splenomegaly', 'mild splenomegaly', 'marked splenomegaly', 'spleen : splenomegaly', 'ongoing splenomegaly'], negative_prompts=['no splenomegaly', 'spleen : normal .', 'negative for splenomegaly'])

disease_prompts['splenomegaly'] = prompts

prompts = DiseasePrompts(disease_name='hepatomegaly', region='liver', positive_prompts=['massive hepatomegaly', 'marked hepatomegaly', 'stable hepatomegaly', 'mild hepatomegaly', 'liver and biliary tree : hepatomegaly'], negative_prompts=['liver and biliary tree : normal .', 'no hepatomegaly'])

disease_prompts['hepatomegaly'] = prompts

prompts = DiseasePrompts(disease_name='atherosclerosis', region='aorta', positive_prompts=['vasculature : atherosclerosis', 'mild atherosclerosis', 'moderate atherosclerosis', 'severe atherosclerosis', 'focal atherosclerosis', 'marked atherosclerosis', 'calcific atherosclerosis'], negative_prompts=['no evidence of atherosclerosis', 'no significant atherosclerosis'])

disease_prompts['atherosclerosis'] = prompts

pleural_effusion_prompts = DiseasePrompts(disease_name='pleural effusion', region='lung', positive_prompts=['left pleural effusion', 'right pleural effusion', 'bilateral pleural effusion', 'moderate pleural effusion', 'small pleural effusion'], negative_prompts=['no pleural effusion', 'without pleural effusion', 'no evidence of pleural effusion', 'no left pleural effusion', 'no right pleural effusion', 'no consolidation or pleural effusion', 'no pericardial or pleural effusion'])

disease_prompts['pleural_effusion'] = pleural_effusion_prompts

hepatic_steatosis_prompts = DiseasePrompts(disease_name='hepatic steatosis', region='liver', positive_prompts=['mild hepatic steatosis', 'severe hepatic steatosis', 'moderate hepatic steatosis', 'diffuse hepatic steatosis', 'with hepatic steatosis', 'liver and biliary tree : hepatic steatosis', 'hepatic steatosis is noted'], negative_prompts=['no hepatic steatosis', 'without hepatic steatosis', 'no evidence of hepatic steatosis'])

disease_prompts['hepatic_steatosis'] = hepatic_steatosis_prompts

appendicitis_prompts = DiseasePrompts(disease_name='appendicitis', region='large bowel', positive_prompts=['consistent with acute appendicitis', 'consistent with appendicitis', 'compatible with appendicitis', 'compatible with acute uncomplicated appendicitis', 'compatible with uncomplicated appendicitis', 'compatible with acute appendicitis', 'represents early acute appendicitis', 'acute uncomplicated appendicitis', 'abdominal suggest acute appendicitis', 'concerning for appendicitis', 'perforated appendicitis'], negative_prompts=['no evidence of acute appendicitis', 'no evidence of appendicitis', 'no appendicitis', 'no acute appendicitis', 'negative for appendicitis', 'without evidence of appendicitis', 'no sign of acute appendicitis', 'no secondary signs of acute appendicitis', 'no secondary signs of appendicitis'])

disease_prompts['appendicitis'] = appendicitis_prompts

gallstones_prompts = DiseasePrompts(disease_name='gallstones', region='gallbladder', positive_prompts=['gallstones present', 'gallstones without ct findings of cholecystitis', 'gallstones are seen', 'gallstones are present', 'gallstones demonstrated', 'gallstones evident', 'large gallstones', 'small gallstones', 'multiple gallstones', 'multiple hyperdense gallstones', 'multiple calcified gallstones', 'multiple radiopaque gallstones', 'multiple layering gallstones', 'gallstones are again noted', 'gallstones are noted'], negative_prompts=['no gallstones', 'no radiopaque gallstones', 'no gallstones identified', 'without evidence of radiopaque gallstones', 'no evidence of radiopaque gallstones', 'without ct evidence of gallstones', 'no ct evidence of gallstones', 'no radiodense gallstones', 'without gallstones', 'without radiopaque gallstones', 'no calcified gallstones', 'no radiolucent gallstones', 'no sludge or gallstones'])

disease_prompts['gallstones'] = gallstones_prompts

hydronephrosis_prompts = DiseasePrompts(disease_name='hydronephrosis', region='kidney', positive_prompts=['sided hydronephrosis', 'bilateral hydronephrosis', 'increase in mild hydronephrosis', 'development of mild hydronephrosis', 'is mild left hydronephrosis', 'is mild right hydronephrosis', 'is moderate left hydronephrosis', 'is moderate right hydronephrosis', 'moderate degree of hydronephrosis', ': left hydronephrosis', ': mild hydronephrosis', ': mild left hydronephrosis', ': mild right hydronephrosis', 'there is hydronephrosis', 'persistent moderate right hydronephrosis'], negative_prompts=['no hydronephrosis', 'no focal hydronephrosis', 'no renal hydronephrosis', 'no evidence of hydronephrosis', 'without hydronephrosis', 'or hydronephrosis', 'hydronephrosis or', 'no evidence of hydronephrosis'])

disease_prompts['hydronephrosis'] = hydronephrosis_prompts

bowel_obstruction_prompts = DiseasePrompts(disease_name='bowel obstruction', region='small bowel', positive_prompts=['partial small bowel obstruction', 'compatible with small bowel obstruction', 'concerning for a small bowel obstruction', 'consistent with small bowel obstruction', 'mechanical small bowel obstruction', 'high grade distal small bowel obstruction'], negative_prompts=['no bowel obstruction', 'no small bowel obstruction', 'no critical bowel obstruction', 'no small or large bowel obstruction', 'no evidence of bowel obstruction', 'no evidence for bowel obstruction', 'no evidence of small bowel obstruction', 'no associated bowel obstruction', 'negative for bowel obstruction', 'no ct evidence of bowel obstruction', 'no findings of bowel obstruction'])

disease_prompts['bowel_obstruction'] = bowel_obstruction_prompts

fracture_prompts = DiseasePrompts(disease_name='fracture', region='lumbar vertebrae', positive_prompts=['compression fracture', 'fracture identified', 'fractures identified', 'rib fracture', 'sacral fracture', 'femoral fracture', 'right iliac wing fracture', 'musculoskeletal : nondisplaced fracture', 'musculoskeletal : fracture'], negative_prompts=['no fracture', 'no displaced fracture', 'no acute fracture', 'no evidence of fracture', 'without evidence of fracture'])

disease_prompts['fracture'] = fracture_prompts