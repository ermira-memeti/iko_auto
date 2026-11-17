from pathlib import Path
from collections import Counter,defaultdict
from datetime import datetime,timezone
import csv,json,hashlib,statistics,math,re,zipfile
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.style import WD_STYLE_TYPE

ROOT=Path('/mnt/data/iko_gate_work')
OUT=ROOT/'final_reviewed'
OUT.mkdir(exist_ok=True)
files={
 'EU routing':Path('/mnt/data/IKO_Gate_Routing_Blind_EU.xlsx'),
 'BK routing':Path('/mnt/data/IKO_Gate_Routing_Blind_BK.xlsx'),
 'EU passages':Path('/mnt/data/IKO_Gate_Passage_Blind_EU.xlsx'),
 'BK passages':Path('/mnt/data/IKO_Gate_Passage_Blind_BK.xlsx')}

def read_csv(p):
 with open(p,encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
qrows=read_csv(ROOT/'GATE26_50_Candidate_Questions.csv')
qmap={x['question_id']:x for x in qrows}
design={x['question_id']:x for x in read_csv(ROOT/'GATE26_Design_Notes_INTERNAL.csv')}
ppool=read_csv(ROOT/'GATE26_Union_Passage_Pool_NO_LABELS.csv')
ppmap={(x['question_id'],x['chunk_id']):x for x in ppool}
pred={x['question_id']:x for x in read_csv(ROOT/'GATE26_Gate_Predictions_NOT_FOR_REVIEWERS.csv')}
ranks=read_csv(ROOT/'GATE26_Original_Method_Rankings.csv')

def xread(file,tab,keys):
 ws=openpyxl.load_workbook(file,read_only=True,data_only=True)[tab];ws.reset_dimensions()
 rows={}
 for row in ws.iter_rows(min_row=2,values_only=True):
  if not row or row[0] is None: continue
  key=tuple(str(row[k]).strip() for k in keys)
  assert key not in rows,(file,key)
  rows[key]=row
 return rows
EU=xread(files['EU routing'],'Routing Labels',[0]);BK=xread(files['BK routing'],'Routing Labels',[0]);PEU=xread(files['EU passages'],'Passage Grades',[0,3]);PBK=xread(files['BK passages'],'Passage Grades',[0,3])
assert set(EU)==set(BK)=={(k,) for k in qmap}
assert set(PEU)==set(PBK)==set(ppmap)

# Content and data-snapshot consistency, plus exact missing-grade checks.
issues=[]
def norm(s): return ' '.join(str(s or '').split())
for id,q in qmap.items():
 for name,rows in [('EU',EU),('BK',BK)]:
  x=rows[(id,)]
  if norm(x[1])!=norm(q['insurer']) or norm(x[2])!=norm(q['question']):issues.append(f'{name} routing question mismatch {id}')
  if x[3] not in ('Yes','No','Unclear') or x[4] not in ('Yes','No','Unclear'):issues.append(f'{name} incomplete routing {id}')
for k,p in ppmap.items():
 for name,rows in [('EU',PEU),('BK',PBK)]:
  x=rows[k]
  for i,col in [(1,'insurer'),(2,'question'),(4,'source_document'),(5,'pdf_page'),(6,'passage_text')]:
   if norm(x[i])!=norm(p[col]):issues.append(f'{name} passage mismatch {col} {k}')
  if str(x[7]).strip() not in ('0','1','2'):issues.append(f'{name} grade missing {k}')
assert not issues, '\n'.join(issues[:30])
route_dis=[(id,f) for id in qmap for f,i in [('Grounding',3),('Gplus',4)] if EU[(id,)][i]!=BK[(id,)][i]]
pass_dis=[k for k in ppmap if PEU[k][7]!=PBK[k][7]]
assert not route_dis and not pass_dis

qdata=[]
cm=Counter()
for id,q in qmap.items():
 r=EU[(id,)];ground=r[3];ext=r[4];yes=pred[id]['gate_route']=='enhanced_v8_2'
 valid=ground=='Yes' and ext in ('Yes','No')
 cls=('TP' if ext=='Yes' and yes else 'FN' if ext=='Yes' else 'FP' if yes else 'TN') if valid else 'EXCLUDED'
 if valid:cm[cls]+=1
 qdata.append({'question_id':id,'insurer':q['insurer'],'design_group':design[id]['design_group'],'question':q['question'],
  'EU_grounding':r[3],'BK_grounding':BK[(id,)][3], 'EU_Gplus':r[4],'BK_Gplus':BK[(id,)][4],
  'final_grounding':ground,'final_Gplus':ext,'gate_prediction':'G+' if yes else 'G0','gate_topic':pred[id]['gate_topic'],
  'evaluation_status':'Included' if valid else 'Excluded: unclear grounding','classification':cls,
  'EU_notes':r[7] or '','BK_notes':BK[(id,)][7] or '',
  'source_pdf':design[id]['source_document'],'source_pdf_page':design[id]['source_pdf_page']})

assert len(qdata)==50 and sum(q['evaluation_status']=='Included' for q in qdata)==48
assert cm==Counter({'TP':24,'FP':4,'TN':19,'FN':1})
precision=cm['TP']/(cm['TP']+cm['FP']);recall=cm['TP']/(cm['TP']+cm['FN']);specificity=cm['TN']/(cm['TN']+cm['FP'])
pass_data=[]
grades={}
for k,p in ppmap.items():
 ga=int(PEU[k][7]);gb=int(PBK[k][7]);assert ga==gb
 grades[k]=ga
 pass_data.append({'question_id':k[0],'chunk_id':k[1],'insurer':p['insurer'],'source_pdf':p['source_document'],'source_pdf_page':int(p['pdf_page']),
  'EU_grade':ga,'BK_grade':gb,'final_grade':ga,'EU_notes':PEU[k][8] or '','BK_notes':PBK[k][8] or '',
  'question':p['question'],'retrieved_passage':p['passage_text']})
assert Counter(grades.values())==Counter({0:213,1:41,2:73})

# Independent recomputation from original saved rankings, not imported metrics file.
run_index=defaultdict(list)
for r in ranks:
 if r['chunk_id']: run_index[r['method'],r['question_id']].append((int(r['rank']),r['chunk_id']))
for k in run_index:run_index[k].sort()
per=[]
sub=defaultdict(list)
for method in ['M2','M5','M7','M8']:
 for q in qdata:
  if q['evaluation_status']!='Included':continue
  qid=q['question_id'];rs=[c for rank,c in run_index[method,qid]]
  assert len(rs)<=5 and len(rs)==len(set(rs))
  scores=[grades[(qid,c)] for c in rs]
  hit=sum(x==2 for x in scores)>0
  rr=next((1/(i+1) for i,v in enumerate(scores) if v==2),0.0)
  ideal_n=sum(1 for (id,ch),v in grades.items() if id==qid and v==2)
  ideal=sum(1/math.log2(i+2) for i in range(min(5,ideal_n)))
  dcg=sum((v==2)/math.log2(i+2) for i,v in enumerate(scores))
  row={'method':method,'question_id':qid,'expert_Gplus':q['final_Gplus'],'design_group':q['design_group'],
       'hit5':int(hit),'p5':sum(x==2 for x in scores)/5,'p1':int(bool(scores) and scores[0]==2),
       'mrr5':rr,'ndcg5':dcg/ideal if ideal else 0,'empty':int(len(rs)==0),'num_returned':len(rs)}
  per.append(row)
  sub[method,'all_eligible'].append(row)
  sub[method,'Gplus_related'].append(row) if q['final_Gplus']=='Yes' else sub[method,'other_topics'].append(row)
assert len(per)==192
mrows=[]
for (method,grp),rs in sorted(sub.items()):
 mrows.append({'method':method,'group':grp,'n_questions':len(rs),'Hit@5':sum(x['hit5'] for x in rs)/len(rs),
 'P@5':sum(x['p5'] for x in rs)/len(rs),'P@1':sum(x['p1'] for x in rs)/len(rs),
 'MRR@5':sum(x['mrr5'] for x in rs)/len(rs),'nDCG@5':sum(x['ndcg5'] for x in rs)/len(rs),'Empty':sum(x['empty'] for x in rs)})
# Independently compare against the previously generated scoring script.
saved=read_csv(OUT/'retrieval_results_by_expert_topic.csv')
for m in mrows:
 s=next(x for x in saved if x['method']==m['method'] and x['subset']=={'all_eligible':'all_valid','Gplus_related':'expert_Gplus_topic','other_topics':'expert_other_topic'}[m['group']])
 for field,prev in [('Hit@5','Hit5'),('P@5','P5'),('P@1','P1'),('MRR@5','MRR5'),('nDCG@5','nDCG5')]: assert abs(m[field]-float(s[prev]))<1e-12,(m,field)
 assert m['Empty']==int(s['empty'])

strata=[]
for group in sorted(set(x['design_group'] for x in qdata)):
 arr=[r for r in qdata if r['design_group']==group];valid=[x for x in arr if x['evaluation_status']=='Included']
 strata.append({'design_group':group,'n_drafted':len(arr),'n_eligible':len(valid),'n_gold_Gplus':sum(x['final_Gplus']=='Yes' for x in valid),
 'gate_Gplus_predictions':sum(x['gate_prediction']=='G+' for x in valid),'TP':sum(x['classification']=='TP' for x in valid),
 'FP':sum(x['classification']=='FP' for x in valid),'TN':sum(x['classification']=='TN' for x in valid),
 'FN':sum(x['classification']=='FN' for x in valid),'excluded_ids':', '.join(x['question_id'] for x in arr if x['evaluation_status']!='Included')})

# Result workbook, original grades unchanged.
WB=openpyxl.Workbook();WB.remove(WB.active)
navy='24334C';green='20775F';teal='DDF3EF';blue='244DAD';muted='667085';purple='6B4C8A';orange='D97706';light='F4F7FA'

def sheet(name,headers,rows,widths=None):
 ws=WB.create_sheet(name);ws.sheet_view.showGridLines=False;ws.append(headers)
 for row in rows:ws.append([row.get(h,'') for h in headers])
 ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
 ws.row_dimensions[1].height=32
 for c in ws[1]:c.fill=PatternFill('solid',fgColor=navy);c.font=Font(name='Aptos',size=10,bold=True,color='FFFFFF');c.alignment=Alignment(wrap_text=True,vertical='center')
 for i,h in enumerate(headers,1):
  w=(widths or {}).get(h,16 if len(h)<17 else 23)
  ws.column_dimensions[get_column_letter(i)].width=w
 for row in ws.iter_rows(min_row=2):
  for c in row:
   c.font=Font(name='Aptos',size=10,color=green if c.column in (1,2) else '303944')
   c.alignment=Alignment(vertical='top',wrap_text= c.column==1 or (widths or {}).get(headers[c.column-1],0)>32)
 for j in range(2,ws.max_row+1):
  if name=='Passage Audit':ws.row_dimensions[j].height=85
  elif name=='Routing Audit':ws.row_dimensions[j].height=49
  else:ws.row_dimensions[j].height=23
 return ws

read=WB.create_sheet('Read Me');read.sheet_view.showGridLines=False
notes=[
 ('IKO-AUTO | Reviewer 1, Comment 2','Final analysis of independently rated extension-topic gate diagnostic'),
 ('Assessment status','EU and BK provided complete separate forms; per study team, assessments were blind and independent.'),
 ('Questions drafted','50 post-hoc AI-assisted, topic-balanced questions; 25 intended G+ topics and 25 controls'),
 ('Primary denominator','48 questions; GATE26_047 and GATE26_050 excluded because both assessors marked grounding Unclear'),
 ('Routing labels','Both reviewers agree on 50/50 G+ semantic relevance labels and 50/50 grounding labels.'),
 ('Passage labels','Both reviewers agree on all 327 grades: 213 grade 0; 41 grade 1; 73 grade 2.'),
 ('Target definition','G+ relevant means question asks for one of five newly represented assertions; this is not proof G+ improves retrieval.'),
 ('Gate prediction','Unchanged V8.3 gate generated 28 G+ and 22 G0 predictions across all drafted questions.'),
 ('Gate accuracy','TP=24; FP=4; TN=19; FN=1 among 48 eligible questions. Precision=85.7%; Recall=96.0%.'),
 ('Retrieval metrics','Four original methods M2, M5, M7, M8; cutoff Top-5, grade 2 defines direct relevance; empty outputs score zero.'),
 ('Caution','M8 does not outperform always-G+ M7 overall in Hit@5; M2 performs best overall.'),
 ('Limitations','Post-hoc AI-assisted question design, five known policy booklets and one exposure per extension fact; not an external held-out benchmark.'),
 ('No scientific inference','No statistical significance is claimed from descriptive differences.'),
 ('Evidence trail','Reviewer input files are preserved unchanged; sha256 hashes and original model-run hashes in Provenance sheet.'),
]
read.append(['FIELD','DETAIL'])
for n in notes:read.append(n)
read.column_dimensions['A'].width=27;read.column_dimensions['B'].width=118;read.freeze_panes='B2';read.row_dimensions[1].height=29
for c in read[1]:c.fill=PatternFill('solid',fgColor=navy);c.font=Font(name='Aptos',bold=True,color='FFFFFF',size=11)
for r in range(2,read.max_row+1):
 read.cell(r,1).font=Font(name='Aptos',color=muted,bold=True,size=10)
 read.cell(r,2).font=Font(name='Aptos',size=10,color='283445')
 read.cell(r,2).alignment=Alignment(wrap_text=True,vertical='center')
 read.row_dimensions[r].height=36

matrows=[{'row':'Predicted G+','Expert G+ relevant':cm['TP'],'Expert G0 sufficient':cm['FP']},
 {'row':'Predicted G0','Expert G+ relevant':cm['FN'],'Expert G0 sufficient':cm['TN']}]
sheet('Gate Matrix',['row','Expert G+ relevant','Expert G0 sufficient'],matrows,{'row':25,'Expert G+ relevant':26,'Expert G0 sufficient':26})
sheet('Method Results',['method','group','n_questions','Hit@5','P@5','P@1','MRR@5','nDCG@5','Empty'],mrows,{'method':15,'group':27,'n_questions':15,'Hit@5':14,'P@5':14,'P@1':14,'MRR@5':14,'nDCG@5':14,'Empty':12})
for row in WB['Method Results'].iter_rows(min_row=2):
 for c in row[3:8]:c.number_format='0.000'
ws=sheet('Routing Audit',list(qdata[0].keys()),qdata,{'question_id':18,'insurer':16,'design_group':24,'question':86,'EU_grounding':15,'BK_grounding':15,'EU_Gplus':14,'BK_Gplus':14,'final_grounding':18,'final_Gplus':18,'gate_prediction':18,'gate_topic':18,'evaluation_status':30,'classification':18,'EU_notes':40,'BK_notes':40,'source_pdf':28,'source_pdf_page':14})
for row in ws.iter_rows(min_row=2):
 if row[12].value.startswith('Excluded'):
  for c in row:c.fill=PatternFill('solid',fgColor='FFF1E3')
 elif row[13].value in ('FN','FP'):
  row[13].font=Font(name='Aptos',bold=True,color='B42318')
sheet('Topic Strata',list(strata[0].keys()),strata,{'design_group':28,'n_drafted':14,'n_eligible':15,'n_gold_Gplus':17,'gate_Gplus_predictions':23,'excluded_ids':25})
sheet('Passage Audit',list(pass_data[0].keys()),pass_data,{'question_id':17,'chunk_id':44,'insurer':17,'source_pdf':30,'source_pdf_page':16,'EU_grade':11,'BK_grade':11,'final_grade':13,'EU_notes':44,'BK_notes':44,'question':85,'retrieved_passage':110})
sheet('Per Question',list(per[0].keys()),per,{'method':13,'question_id':19,'expert_Gplus':16,'design_group':27,'hit5':10,'p5':10,'p1':10,'mrr5':12,'ndcg5':13,'empty':10,'num_returned':16})
for row in WB['Per Question'].iter_rows(min_row=2):
 for c in row[5:9]:c.number_format='0.000'
prov=[]
for name,p in files.items():prov.append({'item':name,'location':p.name,'sha256':sha(p),'category':'Human workbook'})
for name in ['GATE26_50_Candidate_Questions.csv','GATE26_Gate_Predictions_NOT_FOR_REVIEWERS.csv','GATE26_Original_Method_Rankings.csv','GATE26_Union_Passage_Pool_NO_LABELS.csv','GATE26_Design_Notes_INTERNAL.csv','GATE26_Run_Provenance.json','GATE26_Frozen_Candidate_Manifest.json']:
 p=ROOT/name;prov.append({'item':name,'location':p.name,'sha256':sha(p),'category':'Frozen run'})
sheet('Provenance',['item','location','sha256','category'],prov,{'item':58,'location':58,'sha256':72,'category':20})
WB.calculation=openpyxl.workbook.properties.CalcProperties(calcMode='auto')
file_xlsx=Path('/mnt/data/IKO_Auto_Gate_Comment2_Final_Results.xlsx');WB.save(file_xlsx)

# Copy ready article insertion and reviewer response.
D=Document();sec=D.sections[0];sec.top_margin=Inches(.65);sec.bottom_margin=Inches(.65);sec.left_margin=Inches(.76);sec.right_margin=Inches(.76)
styles=D.styles;style=styles['Normal'];style.font.name='Aptos';style.font.size=Pt(10);style.font.color.rgb=RGBColor(37,50,69);style.paragraph_format.space_after=Pt(5)
for name,sz in [('Title',17),('Heading 1',13),('Heading 2',11)]:
 s=styles[name];s.font.name='Aptos';s.font.size=Pt(sz);s.font.bold=True;s.font.color.rgb=RGBColor(36,51,76);s.paragraph_format.space_before=Pt(9);s.paragraph_format.space_after=Pt(5)
cap=styles.add_style('Table caption',WD_STYLE_TYPE.PARAGRAPH);cap.font.name='Aptos';cap.font.size=Pt(9);cap.font.bold=True;cap.font.color.rgb=RGBColor(36,51,76);cap.paragraph_format.space_before=Pt(6);cap.paragraph_format.space_after=Pt(3)
D.add_heading('IKO-Auto | Reviewer 1 Comment 2',0)
D.add_paragraph('Copy-ready local manuscript additions and final scoring results',style='Subtitle')
D.add_heading('1. New methods subsection',1)
D.add_paragraph('Suggested location: add Section 5.7 after the current Section 5.6 and before Results. Preserve the original Methods text.')
D.add_heading('Extension-topic gate evaluation (post-hoc)',2)
D.add_paragraph('To assess the deterministic insurer–topic gate independently of the original H1 question distribution, we constructed an additional topic-balanced diagnostic of 50 questions using the same five indexed policy booklets. Twenty-five questions targeted the five newly represented G+ evidence areas (AXA non-approved windscreen claims, Admiral ADAS recalibration, Aviva glass/ADAS terms, Direct Line windscreen supplier limits, and Direct Line hire-car repairer duration), with five questions per area. The remaining 25 were off-topic or misleading-keyword controls, including five esure controls for which no G+ route was defined. Questions were drafted with AI assistance after the original development and H1 analyses and therefore form a post-hoc diagnostic, not an independently authored or prospective held-out benchmark.')
D.add_paragraph('Two insurance-domain assessors (EU and BK) independently reviewed all 50 questions on separate forms without gate predictions, method identities, retrieval outcomes, or pre-filled AI relevance suggestions. For each question they judged policy grounding and whether the question required a fact newly represented by G+. The assessors separately graded 327 deduplicated question–passage pairs, pooled from the unchanged top-five results of M2, M5, M7 and M8, using the original 0/1/2 rubric. Agreement was exact for both 50-question routing labels and all 327 passage grades, so no disagreement adjudication was required. Two questions (GATE26_047 and GATE26_050) were marked unclear for policy grounding by both assessors and were excluded from primary accuracy and retrieval analyses. The remaining 48 questions comprised 25 expert-labeled G+-relevant questions and 23 other-topic questions.')
D.add_paragraph('Gate precision, recall, specificity, and the confusion matrix were calculated by comparing expert semantic G+ relevance with the unchanged V8.3 gate predictions. Retrieval outcomes were computed over all 48 eligible questions for M2, M5, M7 and M8, and separately for the two expert-defined topic groups. We report Hit@5, Precision@5, P@1, MRR@5, and binary nDCG@5 using grade 2 as direct relevance and treating empty results as zero. All four retrieval configurations and the 717-passage index were held unchanged. Comparisons are descriptive.')
D.add_heading('2. New results subsection',1)
D.add_paragraph('Suggested title: 6.9. Extension-topic gate evaluation')
D.add_paragraph('EU and BK agreed on all 50 extension-topic judgments and all 327 passage judgments; the latter comprised 213 grade-0, 41 grade-1 and 73 grade-2 pairs. After excluding two questions that both assessors marked as unclear for source grounding, the gate correctly selected G+ for 24 of the 25 G+-relevant questions and correctly retained G0 for 19 of the 23 other-topic questions. This yielded 24 true positives, four false positives, 19 true negatives and one false negative. Gate precision was 0.857, recall 0.960, specificity 0.826 and accuracy 0.896. These values measure recognition of the five added evidence topics, not retrieval superiority or generalization to unseen policy documents.')

D.add_paragraph('Table X. Gate decisions against independently judged extension-topic relevance (48 grounded questions).',style='Table caption')
t=D.add_table(rows=1,cols=3);t.style='Light Shading Accent 1'
for c,s in zip(t.rows[0].cells,['Gate prediction','Expert: G+ relevant','Expert: G0 sufficient']):c.text=s
for arr in [('Selects G+',str(cm['TP'])+' (TP)',str(cm['FP'])+' (FP)'),('Selects G0',str(cm['FN'])+' (FN)',str(cm['TN'])+' (TN)')]:
 cells=t.add_row().cells
 for c,v in zip(cells,arr):c.text=v
D.add_paragraph('On the 48 grounded questions, M2 achieved the highest overall retrieval performance (Hit@5 = 0.938; MRR@5 = 0.778). M7 and M8 both achieved Hit@5 = 0.792; their MRR@5 scores were 0.577 and 0.578, respectively. For the 25 extension-topic questions, M7 attained MRR@5 = 0.860 and M8 attained 0.820, compared with M2 at 0.783. On the 23 other-topic questions, M8 improved MRR@5 relative to M7 (0.314 versus 0.269) but remained below M2 (0.772). Thus the gate recognizes the added-topic intent with relatively high precision and recall, yet its routing does not yield a clear aggregate advantage over always using G+, and it does not surpass the lexical baseline overall.')

D.add_paragraph('Table Y. Retrieval on the independently assessed extension-topic diagnostic (binary direct relevance).',style='Table caption')
t=D.add_table(rows=1,cols=7);t.style='Light Shading Accent 1'
headers=['Group','Method','n','Hit@5','P@1','MRR@5','nDCG@5']
for c,s in zip(t.rows[0].cells,headers):c.text=s
for group,label in [('all_eligible','All grounded'),('Gplus_related','G+ topics'),('other_topics','Other topics')]:
 for method in ['M2','M5','M7','M8']:
  m=next(x for x in mrows if x['method']==method and x['group']==group)
  vals=[label,method,str(m['n_questions']),f"{m['Hit@5']:.3f}",f"{m['P@1']:.3f}",f"{m['MRR@5']:.3f}",f"{m['nDCG@5']:.3f}"]
  cells=t.add_row().cells
  for c,v in zip(cells,vals):c.text=v
D.add_paragraph('Note: n is the number of grounded questions in each subset; group labels denote the independently assessed semantic requirement for one of the five new G+ facts. Empty outputs contribute zero. P@5 and the number of empty outputs are provided in the accompanying results workbook.')
D.add_heading('3. Short discussion addition',1)
D.add_paragraph('Suggested location: Section 8.2, after the existing gate interpretation.')
D.add_paragraph('The extension-topic diagnostic distinguishes semantic routing accuracy from the downstream retrieval effect. Although the unchanged gate recalled 24 of 25 relevant extension-topic questions, its routing sometimes selected G+ for questions about other contractual provisions, and one relevant question was routed to G0. Across the 48 eligible questions, M8 did not improve Hit@5 over unconditional G+ retrieval (M7), and M2 remained the strongest overall method. The targeted, AI-assisted question design and repeated policy clauses prevent these findings from being interpreted as evidence of generalization to independent user queries or unseen policy booklets.')
D.add_heading('4. Draft response to Reviewer 1, Comment 2',1)
D.add_paragraph('We thank the reviewer for identifying the inadequacy of H1 as a gate-evaluation set. We added a post-hoc, topic-balanced diagnostic with 50 questions covering the five newly represented G+ evidence areas and matched off-topic/keyword controls. Two insurance-domain assessors independently judged question grounding and whether each question required newly represented G+ evidence, without seeing gate predictions or retrieval results; they also judged 327 pooled question–passage pairs. Two questions were excluded due to unclear source grounding. Among the remaining 48 questions, the unchanged gate achieved 24 TP, 4 FP, 19 TN and 1 FN (precision = 0.857; recall = 0.960). We additionally evaluated unchanged M2, M5, M7 and M8 retrieval configurations by expert-defined topic. Although the gate identifies extension topics accurately within this diagnostic, M8 does not improve overall Hit@5 over always-G+ M7, and insurer-filtered BM25 remains the strongest overall baseline. We now report both the gate-recognition evidence and its limited retrieval impact, while explicitly stating that the AI-assisted, post-hoc diagnostic does not constitute a prospective held-out evaluation.')
D.add_heading('5. Final reporting checks',1)
for text in ['In the question archive, change the study status from “no independent gold” to a new version with the expert ratings, retaining the original frozen manifest unchanged.',
'Identify the two excluded questions and the 48-question denominator in every reported result. Do not label this an H1 or unseen-policy test.',
'Retain both original EU and BK workbooks unchanged alongside the metric CSV outputs, exact gate predictions and saved rankings.',
'If reporting inter-rater agreement, specify that exact agreement was 50/50 on routing labels and 327/327 on passage grades; these figures concern the new diagnostic only.',
'Use final section/table numbers after integrating the local additions.']:
 D.add_paragraph(text,style='List Bullet')
for table in D.tables:
 table.alignment=WD_TABLE_ALIGNMENT.CENTER
 for row in table.rows:
  for cell in row.cells:
   cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
   for p in cell.paragraphs:
    p.paragraph_format.space_after=Pt(2)
    for run in p.runs:run.font.size=Pt(8.2)
 for cell in table.rows[0].cells:
  for p in cell.paragraphs:
   for run in p.runs:run.bold=True
D.core_properties.title='IKO-Auto Reviewer 1 Comment 2 | Expert-reviewed extension-topic gate diagnostic'
file_docx=Path('/mnt/data/IKO_Auto_Gate_Comment2_Copy_Ready_Additions.docx');D.save(file_docx)

# Bundle without assessor-identified original workbooks, which are already possessed by user.
files_to_zip=[file_xlsx,file_docx,OUT/'gate_accuracy_and_agreement.json',OUT/'retrieval_results_by_expert_topic.csv',OUT/'per_question_retrieval_metrics.csv',OUT/'final_routing_gold.csv',OUT/'final_passage_labels.csv']
with zipfile.ZipFile('/mnt/data/IKO_Auto_Gate_Comment2_Final_Analysis.zip','w',zipfile.ZIP_DEFLATED) as z:
 for p in files_to_zip:z.write(p,p.name)

print('PASSAGES',len(grades),Counter(grades.values()))
print('ROUTES',len(qdata),cm,'precision',precision,'recall',recall,'specificity',specificity)
print('METHODS')
for m in mrows:print(m)
print('OUTPUT',file_xlsx,file_docx)
