from pathlib import Path
import csv,json,hashlib
from collections import Counter
ROOT=Path('/mnt/data/iko_gate_work')
# Proposed question design, not independent expert-produced gold labels.
# Format: group, insurer, question, source PDF, one-based PDF page, rationale for author-only audit
DATA=[
('AXA_REPLACEMENT','AXA','Under AXA motor insurance, what is the maximum payment for a windscreen replacement carried out by a repairer who is not approved?','axa_car_policy.pdf',16,'outside-network replacement cap'),
('AXA_REPLACEMENT','AXA','If an AXA policyholder arranges a windscreen repair without an approved repairer, how much can AXA pay at most?','axa_car_policy.pdf',16,'outside-network repair cap'),
('AXA_REPLACEMENT','AXA','For AXA Section D, how do the payout ceilings differ between a windscreen repair and replacement by an independent glass business?','axa_car_policy.pdf',16,'compare two outside-network caps'),
('AXA_REPLACEMENT','AXA','What payment restrictions apply when AXA windscreen work is not done by its approved glass repairer?','axa_car_policy.pdf',16,'outside-network cap'),
('AXA_REPLACEMENT','AXA','For an AXA policyholder using a non-network provider to replace a damaged vehicle windscreen, what is the stated reimbursement limit?','axa_car_policy.pdf',16,'outside-network replacement cap'),
('ADMIRAL_ADAS','Admiral','Does Admiral pay to recalibrate the ADAS after a windscreen has been replaced, when this is required?','admiral_car_policy.pdf',18,'ADAS recalibration after screen replacement'),
('ADMIRAL_ADAS','Admiral','Under Admiral windscreen cover, who bears the cost of a required driver-assistance recalibration following replacement?','admiral_car_policy.pdf',18,'ADAS cost responsibility'),
('ADMIRAL_ADAS','Admiral','If replacing an Admiral-insured windscreen means the vehicle safety sensors must be calibrated again, does the policy address that cost?','admiral_car_policy.pdf',18,'ADAS paraphrase without trigger term'),
('ADMIRAL_ADAS','Admiral','Is required Advanced Driver Assistance System calibration included following an Admiral windscreen replacement?','admiral_car_policy.pdf',18,'ADAS long-form term'),
('ADMIRAL_ADAS','Admiral','Does Admiral cover ADAS recalibration after glass is replaced, or is this always left to the customer?','admiral_car_policy.pdf',18,'ADAS eligibility'),
('AVIVA_GLASS','Aviva','Before an Aviva policyholder has a windscreen repaired, what contact step does the glass-claim section require?','aviva_car_policy.pdf',23,'notify insurer before work'),
('AVIVA_GLASS','Aviva','If a glass replacement is performed by a repairer not approved by Aviva, where is the contribution limit specified?','aviva_car_policy.pdf',23,'non-approved repairer cap schedule'),
('AVIVA_GLASS','Aviva','Does Aviva provide a courtesy vehicle for a claim solely under its glass claim section when optional courtesy vehicle cover exists?','aviva_car_policy.pdf',23,'no courtesy vehicle for solely glass claim'),
('AVIVA_GLASS','Aviva','What does Aviva require for windscreen-dependent ADAS systems when a glass claim involves repair or replacement?','aviva_car_policy.pdf',23,'ADAS repair/recalibration'),
('AVIVA_GLASS','Aviva','When claiming for an Aviva windscreen repair, must the insurer direct the customer to its approved repairer before work starts?','aviva_car_policy.pdf',23,'pre-work contact and approved repairer'),
('DL_GLASS','Direct Line','Under Direct Line, what is the cap for a windscreen repair carried out by a different supplier?','directline_car_policy.pdf',17,'nonapproved repair limit'),
('DL_GLASS','Direct Line','How much can Direct Line pay for a windscreen replacement when the customer chooses their own glass supplier?','directline_car_policy.pdf',17,'nonapproved replacement limit'),
('DL_GLASS','Direct Line','How do Direct Line payment limits differ for independent windscreen repair and replacement services?','directline_car_policy.pdf',17,'contrast 40 versus 125'),
('DL_GLASS','Direct Line','What reimbursement ceiling applies to a windscreen replacement undertaken outside Direct Line’s approved supplier network?','directline_car_policy.pdf',17,'nonapproved replacement cap'),
('DL_GLASS','Direct Line','If a Direct Line policyholder opts for a separate windscreen repair company, is the full invoice covered or is there a stated upper limit?','directline_car_policy.pdf',17,'nonapproved repair cap'),
('DL_HIRE','Direct Line','For Direct Line, how long is a hire car supplied while the policyholder’s own repairer fixes a repairable vehicle?','directline_car_policy.pdf',15,'independent garage 21 day cap'),
('DL_HIRE','Direct Line','Under Direct Line Guaranteed Hire Car Plus, what is the stated time limit when a customer selects their own repairer?','directline_car_policy.pdf',15,'independent garage 21 day cap'),
('DL_HIRE','Direct Line','Does Direct Line limit a hired car to 21 consecutive days when the insured chooses a non-approved repairer?','directline_car_policy.pdf',15,'21-day wording'),
('DL_HIRE','Direct Line','When an independent repairer is repairing a Direct Line insured car, for how many days can a replacement hire vehicle be provided?','directline_car_policy.pdf',15,'independent repairer duration'),
('DL_HIRE','Direct Line','Does the Direct Line hire car duration change depending on whether repairs use an approved garage or the customer’s own garage?','directline_car_policy.pdf',15,'approved versus own garage duration'),
('AXA_CONTROL','AXA','For AXA European breakdown cover, how many consecutive days may a single trip abroad last?','axa_car_policy.pdf',31,'breakdown option, not glass addition'),
('AXA_CONTROL','AXA','When there is a conflict of interest in a legal dispute, can an AXA customer choose a lawyer under legal assistance cover?','axa_car_policy.pdf',27,'legal assistance not glass'),
('AXA_CONTROL','AXA','Will an AXA claim exclusively for windscreen glass damage reduce the No Claims Discount?','axa_car_policy.pdf',16,'hard negative: same windscreen section, different condition'),
('AXA_CONTROL','AXA','Does AXA breakdown assistance mention help after a flat battery?','axa_car_policy.pdf',31,'breakdown, not glass'),
('AXA_CONTROL','AXA','What can an AXA customer do to withdraw consent to direct marketing communications?','axa_car_policy.pdf',42,'marketing consent, not graph extension'),
('ADMIRAL_CONTROL','Admiral','How many days of cover does Admiral describe for driving the insured vehicle in Europe?','admiral_car_policy.pdf',23,'Europe travel, not ADAS'),
('ADMIRAL_CONTROL','Admiral','What conditions apply to replacement of a car less than twelve months old after a theft or major damage under Admiral?','admiral_car_policy.pdf',20,'new vehicle replacement'),
('ADMIRAL_CONTROL','Admiral','Could Admiral reduce a claim because the driver ignored manufacturer vehicle software updates?','admiral_car_policy.pdf',29,'vehicle care condition'),
('ADMIRAL_CONTROL','Admiral','Does Admiral windscreen cover also mention bodywork scratches caused by broken vehicle glass?','admiral_car_policy.pdf',18,'hard negative: windscreen but not ADAS addition'),
('ADMIRAL_CONTROL','Admiral','Is an additional amount available for accessories damaged with a child car seat under Admiral?','admiral_car_policy.pdf',20,'child equipment, not ADAS'),
('AVIVA_CONTROL','Aviva','Does an Aviva claim solely for glass damage change the customer’s no claim discount?','aviva_car_policy.pdf',23,'hard negative: glass related but outside new quote'),
('AVIVA_CONTROL','Aviva','If an Aviva customer requests original manufacturer glass for a windscreen repair, who pays any price difference?','aviva_car_policy.pdf',23,'hard negative: OEM/OES outside new quote'),
('AVIVA_CONTROL','Aviva','For Aviva repairs using a garage outside the approved network, must an itemised repair estimate be agreed before the work starts?','aviva_car_policy.pdf',10,'general vehicle repair not added glass condition'),
('AVIVA_CONTROL','Aviva','Is optional Aviva courtesy vehicle cover available when the claim has not yet been accepted?','aviva_car_policy.pdf',12,'courtesy vehicle general, not glass only'),
('AVIVA_CONTROL','Aviva','What is excluded from Aviva Tool Cover regarding goods or samples used for trade?','aviva_car_policy.pdf',20,'tools, unrelated to glass'),
('DL_CONTROL','Direct Line','If a Direct Line windscreen claim is the only claim, does it affect the No Claim Discount?','directline_car_policy.pdf',17,'hard negative: same windscreen page, different contract fact'),
('DL_CONTROL','Direct Line','How many protected No Claim Discount claims can a Direct Line policyholder make over three years without affecting NCD?','directline_car_policy.pdf',27,'protected NCD not hire/repair'),
('DL_CONTROL','Direct Line','Are parking fines covered by Direct Line Motor Legal Cover?','directline_car_policy.pdf',22,'legal cover exclusions'),
('DL_CONTROL','Direct Line','Can a Direct Line driver keep a hire car after the vehicle is written off, and what deadline applies?','directline_car_policy.pdf',15,'hard negative: different hire-car rule than own repairer addition'),
('DL_CONTROL','Direct Line','What happens to a Direct Line protected No Claim Discount when more than two claims occur within three years?','directline_car_policy.pdf',27,'NCD condition'),
('ESURE_CONTROL','esure','Does esure cover a mechanical or electrical breakdown as accidental vehicle damage?','esure_car_policy.pdf',19,'non extension insurer; mechanical exclusion'),
('ESURE_CONTROL','esure','What should an esure policyholder report when their details or circumstances change?','esure_car_policy.pdf',48,'non extension insurer; notification'),
('ESURE_CONTROL','esure','Is an esure car-key claim excluded for losses in the first 48 hours of new cover?','esure_car_policy.pdf',27,'non extension insurer; keys'),
('ESURE_CONTROL','esure','How does an esure customer start a complaint about a motor insurance claim?','esure_car_policy.pdf',53,'non extension insurer; complaint'),
('ESURE_CONTROL','esure','Does esure cover driving a rented or hired car if a hire company requires its own insurance?','esure_car_policy.pdf',15,'hard negative: hire car words but no esure extension'),
]
assert len(DATA)==50
EXPECTED_GROUPS={'AXA_REPLACEMENT':5,'ADMIRAL_ADAS':5,'AVIVA_GLASS':5,'DL_GLASS':5,'DL_HIRE':5,'AXA_CONTROL':5,'ADMIRAL_CONTROL':5,'AVIVA_CONTROL':5,'DL_CONTROL':5,'ESURE_CONTROL':5}
assert Counter(r[0] for r in DATA)==EXPECTED_GROUPS
assert len({r[2] for r in DATA})==50
questions=[];design=[]
for i,(grp,insurer,q,file,page,anchor) in enumerate(DATA,1):
 qid=f'GATE26_{i:03d}';questions.append(dict(question_id=qid,insurer=insurer,question=q,category='extension_topic_gate',split='test',gold_exhaustive=False))
 design.append(dict(question_id=qid,insurer=insurer,question=q,design_group=grp,source_document=file,source_pdf_page=page,design_focus=anchor,independent_gold='',review_status='CANDIDATE_AUTHOR_GENERATED_UNVALIDATED'))
out=ROOT/'GATE26_50_Candidate_Questions.csv'
with out.open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,fieldnames=['question_id','insurer','question','category','split','gold_exhaustive']);w.writeheader();w.writerows(questions)
with (ROOT/'GATE26_50_Candidate_Questions.jsonl').open('w',encoding='utf-8') as f:
 for q in questions:f.write(json.dumps(q,ensure_ascii=False)+'\n')
with (ROOT/'GATE26_Design_Notes_INTERNAL.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(design[0]));w.writeheader();w.writerows(design)
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
source_root=Path('/mnt/data/iko_final_work/project')
from hashlib import sha256
pdfhashes={p.name:sha(p) for p in sorted((source_root/'data/research_corpus').glob('*.pdf'))}
manifest=dict(benchmark='REVIEWER_1_COMMENT_2_POST_HOC_AI_DRAFTED_CANDIDATES',n_questions=len(questions),strata=EXPECTED_GROUPS,question_sha256=sha(out),question_jsonl_sha256=sha(ROOT/'GATE26_50_Candidate_Questions.jsonl'),source_pdf_sha256=pdfhashes,source_graph_sha256=sha(source_root/'outputs/v6/iko_auto_five_insurers_v6.ttl'),extended_graph_sha256=sha(source_root/'outputs/v8_2/iko_auto_extended_v8_2.ttl'),gate_code_sha256=sha(source_root/'src/v8_3_intent.py'),development_informed=True,independent_gold=False,limitations=['Question text AI-assisted and tailored to the five known graph additions; not an independent held-out test of external users','Human assessors must verify both contract source grounding and semantic G+ relevance','Retrieval metrics require separately graded method-blind pooled passages'])
(ROOT/'GATE26_Frozen_Candidate_Manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
print('CREATED',len(questions),'questions; insurer balance',Counter(q['insurer'] for q in questions))
print('SHA',manifest['question_sha256'])
