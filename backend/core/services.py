import re
from decimal import Decimal, InvalidOperation
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from .models import Question, AnswerRevision, PaperItem, Paper, Submission, Attempt, Mistake, GradeRevision, AuditEvent

def audit(workspace, action, obj, **details):
    AuditEvent.objects.create(workspace=workspace, action=action, object_id=str(obj.id), details=details)

def decimal_score(value, maximum=None):
    try:
        score = Decimal(str(value))
    except (ValueError, InvalidOperation, TypeError):
        raise ValidationError('分数格式错误。')
    if not score.is_finite() or score < 0 or (maximum is not None and score > maximum) or score.as_tuple().exponent < -2:
        raise ValidationError('分数必须为范围内、最多两位小数的数值。')
    return score

def approved_answer(question):
    return question.answers.filter(status='approved').order_by('-approved_at','-created_at').first()

def validate_paper_student(paper,student):
    if paper.source=='practice':
        owners=set(paper.items.filter(origin_response__isnull=False).values_list('origin_response__submission__student_id',flat=True))
        if owners and owners!={student.id}:
            raise ValidationError('该复练卷关联原学生的错题，请选择对应学生，避免混淆复练证据。')

def question_snapshot(question):
    answer = approved_answer(question)
    if question.status != 'approved' or not answer:
        raise ValidationError(f'第 {question.number or "?"} 题尚未确认题目与参考答案。')
    return {'question_id': str(question.id), 'revision': question.revision, 'stem': question.stem,
            'options': question.options, 'kind': question.kind, 'tags': question.tags, 'regions': question.regions, 'figure_regions': question.figure_regions,
            'answer_id': str(answer.id), 'answer': answer.answer, 'explanation': answer.explanation, 'rubric': answer.rubric}

@transaction.atomic
def approve_question(question, answer_id, clear_issues=False):
    question = Question.objects.select_for_update().get(pk=question.pk)
    answer = question.answers.filter(id=answer_id, workspace=question.workspace).first()
    if not answer or not answer.answer.strip():
        raise ValidationError('请选择本题有效的参考答案。')
    if question.issues and not clear_issues:
        raise ValidationError('请核对并确认题目缺失、识别或答案冲突问题。')
    question.answers.filter(status='approved').exclude(pk=answer.pk).update(status='rejected')
    answer.status = 'approved'
    answer.approved_at = timezone.now()
    answer.save()
    question.status = 'approved'
    question.issues = []
    question.revision += 1
    question.save()
    audit(question.workspace, 'question_approved', question, answer_id=str(answer.id))
    return question

@transaction.atomic
def publish_paper(paper):
    paper = Paper.objects.select_for_update().get(pk=paper.pk)
    if paper.status == 'published':
        return paper
    if not paper.items.exists():
        raise ValidationError('请先添加题目。')
    for item in paper.items.select_related('question'):
        question=Question.objects.select_for_update().get(pk=item.question_id)
        item.snapshot = question_snapshot(question)
        item.save(update_fields=['snapshot'])
    paper.status = 'published'
    paper.published_at = timezone.now()
    paper.save()
    audit(paper.workspace, 'paper_published', paper)
    return paper

@transaction.atomic
def set_grade(attempt, score, feedback='', actor='teacher', expected_revision=None):
    attempt = Attempt.objects.select_for_update().select_related('item','submission').get(pk=attempt.pk)
    if expected_revision is not None and int(expected_revision) != attempt.revision:
        raise ValidationError('评分已被更新，请刷新后再提交。')
    if not attempt.recognition_confirmed or not attempt.item.snapshot.get('answer_id'):
        raise ValidationError('请先确认作答识别和参考答案。')
    score = decimal_score(score, attempt.item.max_score)
    GradeRevision.objects.create(workspace=attempt.workspace, attempt=attempt, score=score, feedback=feedback, actor=actor)
    attempt.final_score = score
    attempt.feedback = feedback
    attempt.status = 'final'
    attempt.revision += 1
    attempt.save()
    if score < attempt.item.max_score:
        mistake, _ = Mistake.objects.get_or_create(workspace=attempt.workspace, attempt=attempt)
        mistake.active = True
        mistake.mastered = False
        mistake.save()
    else:
        Mistake.objects.filter(attempt=attempt).update(active=False, mastered=False)
    audit(attempt.workspace, 'grade_updated', attempt, score=str(score), actor=actor, revision=attempt.revision)
    return attempt

def compare_answer(kind, actual, expected):
    """Conservative supported subset. None means manual review, never wrong."""
    normalize = lambda s: re.sub(r'\s+', '', str(s)).replace('−','-').replace('，',',')
    actual, expected = normalize(actual), normalize(expected)
    if not actual or not expected:
        return None
    if kind in ('single','multiple'):
        if kind=='single' and (len(actual)!=1 or len(expected)!=1):
            return None
        if re.fullmatch('[A-Ha-h]+',actual) and re.fullmatch('[A-Ha-h]+',expected):
            return set(actual.upper()) == set(expected.upper())
        return None
    if kind == 'fill':
        # Only real numeric constants; never eval user/model expressions.
        pattern = r'-?\d+(?:\.\d+)?(?:/-?\d+(?:\.\d+)?)?'
        if re.fullmatch(pattern,actual) and re.fullmatch(pattern,expected):
            from sympy import Rational
            try:
                def rational(s):
                    parts = s.split('/')
                    return Rational(parts[0]) / Rational(parts[1]) if len(parts)==2 else Rational(s)
                return bool(rational(actual) == rational(expected)) if not actual.endswith('/0') and not expected.endswith('/0') else None
            except (ValueError, ZeroDivisionError, TypeError):
                return None
    return None

def suggest_objective_grade(attempt):
    result = compare_answer(attempt.item.snapshot.get('kind'), attempt.student_answer, attempt.item.snapshot.get('answer'))
    if result is None:
        return False
    attempt.suggested_score = attempt.item.max_score if result else Decimal('0')
    attempt.suggestion = '规则比较：答案一致。' if result else '规则比较：答案不同，请核对识别。'
    attempt.save()
    if settings.AUTO_GRADING_ENABLED and attempt.recognition_confirmed:
        set_grade(attempt, attempt.suggested_score, attempt.suggestion, actor='rule')
    return True

@transaction.atomic
def commit_batch(batch):
    from .models import ImportBatch
    batch = ImportBatch.objects.select_for_update().get(pk=batch.pk)
    if batch.status == 'committed':
        return batch
    if batch.status not in ('review','blocked'):
        raise ValidationError('请等待批次识别完成后再归档。')
    questions = list(batch.questions.order_by('created_at'))
    if not questions or any(q.status!='approved' for q in questions):
        raise ValidationError('请先逐题确认所有题目和参考答案。')
    if batch.purpose == 'assessment' and not batch.student_id:
        raise ValidationError('请先绑定学生。')
    paper = batch.paper
    if paper and paper.status != 'published':
        raise ValidationError('关联试卷必须已发布。')
    if paper and batch.student:
        validate_paper_student(paper,batch.student)
    mapping = {}
    if paper:
        if batch.route=='card' and len(questions)!=paper.items.count():
            raise ValidationError('答题卡缺页、重复页或题目数量不符，请检查完整性。')
        for q in questions:
            matches = list(paper.items.filter(label=q.number))
            if len(matches)!=1:
                raise ValidationError(f'题号 {q.number} 无法唯一关联试卷，请修正题号。')
            mapping[q.id] = matches[0]
            if q.stem.strip()!=matches[0].snapshot.get('stem','').strip():
                raise ValidationError(f'题号 {q.number} 的题干与已发布试卷不一致，请核对卷子版本或作为新卷录入。')
            if approved_answer(q).answer.strip()!=str(matches[0].snapshot.get('answer','')).strip():
                raise ValidationError(f'题号 {q.number} 的参考答案与已发布试卷不一致，请核对。')
    else:
        paper = Paper.objects.create(workspace=batch.workspace, title=batch.title, source='external', is_fragment=batch.route=='fragment')
        for i,q in enumerate(questions,1):
            maximum = decimal_score(q.suggested_max_score)
            if maximum <= 0:
                raise ValidationError('请确认各题分值大于0。')
            mapping[q.id] = PaperItem.objects.create(workspace=batch.workspace, paper=paper, question=q,
                label=q.number or str(i), position=i, max_score=maximum)
        paper = publish_paper(paper)
        batch.paper = paper
    if batch.purpose == 'assessment':
        submission, _ = Submission.objects.get_or_create(batch=batch, defaults={'workspace':batch.workspace,
            'paper':paper,'student':batch.student,'test_date':batch.test_date})
        for q in questions:
            item = mapping[q.id]
            attempt, created = Attempt.objects.get_or_create(submission=submission, item=item, defaults={
                'workspace':batch.workspace, 'student_answer':q.extracted_student_answer, 'regions':q.regions, 'confidence':q.confidence})
            if created:
                suggest_objective_grade(attempt)
    batch.status = 'committed'
    batch.progress = 100
    batch.message = '已归档；学生作答需确认识别后定分。' if batch.purpose=='assessment' else '已进入私有题库。'
    batch.save()
    audit(batch.workspace, 'batch_committed', batch)
    return batch
