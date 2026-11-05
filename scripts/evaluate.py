"""Compare human-labelled JSONL against recognition/grading exports.

This evaluator does not manufacture a benchmark and does not call paid APIs.
Each line is {id, questions:[{number, regions:[{page,bbox}], answer,
score, auto_finalized, manual_seconds}]}. See docs/VALIDATION.md.
"""
import argparse
import json
from pathlib import Path

def load(path):
    rows={}
    for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        if not line.strip():
            continue
        row=json.loads(line)
        if row['id'] in rows:
            raise ValueError(f'Duplicate sample id: {row["id"]}')
        numbers=[str(q['number']) for q in row.get('questions',[])]
        if len(numbers)!=len(set(numbers)):
            raise ValueError(f'Duplicate question number in {row["id"]}')
        rows[row['id']]=row
    return rows

def iou(a,b):
    x=max(0,min(a[2],b[2])-max(a[0],b[0]))
    y=max(0,min(a[3],b[3])-max(a[1],b[1]))
    intersection=x*y
    union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
    return intersection/union if union>0 else 0

def normalize(answer):
    return ''.join(str(answer).split()).replace('−','-')

def evaluate(gold,predicted,threshold=.85):
    total=detected=complete=answers=correct_answers=scored=exact_scores=auto=auto_correct=0
    absolute_error=seconds=0
    for sample_id,sample in gold.items():
        candidates={str(q['number']):q for q in predicted.get(sample_id,{}).get('questions',[])}
        for expected in sample.get('questions',[]):
            total+=1
            actual=candidates.get(str(expected['number']))
            if not actual:
                continue
            detected+=1
            required=expected.get('regions',[])
            received=actual.get('regions',[])
            if required and all(any(str(r['page'])==str(g['page']) and iou(r['bbox'],g['bbox'])>=threshold for r in received) for g in required):
                complete+=1
            if 'answer' in expected:
                answers+=1
                correct_answers+=normalize(expected['answer'])==normalize(actual.get('answer',''))
            if expected.get('score') is not None and actual.get('score') is not None:
                scored+=1
                delta=abs(float(expected['score'])-float(actual['score']))
                absolute_error+=delta
                exact_scores+=delta<.005
                if actual.get('auto_finalized'):
                    auto+=1
                    auto_correct+=delta<.005
            seconds+=float(actual.get('manual_seconds',0))
    ratio=lambda a,b:round(a/b,4) if b else None
    return {'samples':len(gold),'expected_questions':total,'detected_questions':detected,
        'detection_recall':ratio(detected,total),'complete_crop_rate':ratio(complete,total),
        'answer_exact_accuracy_on_matched':ratio(correct_answers,answers),
        'grade_exact_accuracy_on_scored':ratio(exact_scores,scored),
        'grade_mean_absolute_error':ratio(absolute_error,scored),
        'automatic_coverage':ratio(auto,total),'automatic_grade_accuracy':ratio(auto_correct,auto),
        'manual_seconds_per_expected_question':ratio(seconds,total)}

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('gold')
    parser.add_argument('predicted')
    parser.add_argument('--iou',type=float,default=.85)
    args=parser.parse_args()
    print(json.dumps(evaluate(load(args.gold),load(args.predicted),args.iou),ensure_ascii=False,indent=2))
