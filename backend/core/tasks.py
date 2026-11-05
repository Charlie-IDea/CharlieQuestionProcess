from io import BytesIO
from celery import shared_task
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from PIL import Image, ImageOps
import pypdfium2 as pdfium
from .models import ImportBatch, SourcePage, Question, AnswerRevision
from .ai import extract_page, solve_question, ProviderUnavailable, ProviderFailure
from django.utils import timezone
from datetime import timedelta

@shared_task
def recover_stale_batches():
    qs=ImportBatch.objects.filter(status__in=['queued','processing'],updated_at__lt=timezone.now()-timedelta(minutes=20))
    with_questions=list(qs.filter(questions__isnull=False).values_list('id',flat=True).distinct())
    reviewed=qs.filter(id__in=with_questions).update(status='review',progress=100,message='后台处理曾中断；已提取题目保留，请审核并补全参考答案。')
    failed=qs.exclude(id__in=with_questions).update(status='failed',message='后台处理超时或工作进程中断，原件已保留。请检查服务后重试。')
    return reviewed+failed

def pages_of(source):
    with source.file.open('rb') as file:
        data = file.read()
    if source.original_name.lower().endswith('.pdf'):
        document = pdfium.PdfDocument(data)
        try:
            if len(document)>settings.MAX_BATCH_PAGES:
                raise ValueError('PDF页数超过单批上限。')
            for index in range(len(document)):
                page = document[index]
                bitmap = page.render(scale=1.7)
                yield index+1, bitmap.to_pil().copy().convert('RGB')
                bitmap.close()
                page.close()
        finally:
            document.close()
    else:
        image = ImageOps.exif_transpose(Image.open(BytesIO(data))).convert('RGB')
        yield 1,image

def region_images(question):
    result = []
    for region in question.regions[:8]:
        page = SourcePage.objects.filter(id=region.get('page'),workspace=question.workspace).first()
        if page:
            with page.image.open('rb') as file:
                image = Image.open(file).convert('RGB')
                x1,y1,x2,y2=region['bbox']
                result.append(image.crop((int(x1*image.width),int(y1*image.height),int(x2*image.width),int(y2*image.height))))
    return result

def persist_page(batch, source, number, image):
    page = SourcePage.objects.filter(source_file=source,number=number).first()
    if page:
        return page
    buffer = BytesIO()
    image.save(buffer,format='JPEG',quality=92)
    page = SourcePage(workspace=batch.workspace,source_file=source,number=number,width=image.width,height=image.height)
    page.image.save('page.jpg',ContentFile(buffer.getvalue()),save=True)
    return page

def safe_extracted(data):
    questions = data.get('questions',[])
    if not isinstance(questions,list) or len(questions)>80:
        raise ProviderFailure('识别结果题目列表无效。')
    for q in questions:
        if not isinstance(q,dict) or not isinstance(q.get('number'),str):
            raise ProviderFailure('识别题号格式无效。')
        box = q.get('bbox',[0,0,1,1])
        if not isinstance(box,list) or len(box)!=4 or any(not isinstance(v,(int,float)) or not 0<=v<=1 for v in box) or box[0]>=box[2] or box[1]>=box[3]:
            raise ProviderFailure('识别区域无效，请重试或手动调整。')
        if q.get('kind','solution') not in ('single','multiple','fill','solution','proof'):
            q['kind']='solution'
        for key in ('options','tags','issues'):
            if not isinstance(q.get(key,[]),list) or any(not isinstance(v,str) for v in q.get(key,[])):
                raise ProviderFailure('识别内容格式无效。')
        for key in ('stem','student_answer','printed_answer','explanation'):
            if not isinstance(q.get(key,''),str) or len(q.get(key,''))>30000:
                raise ProviderFailure('识别文字格式无效。')
        figures=q.get('figures',[])
        if not isinstance(figures,list) or len(figures)>20:
            raise ProviderFailure('识别配图格式无效。')
        for figure in figures:
            if not isinstance(figure,list) or len(figure)!=4 or any(not isinstance(v,(int,float)) or not 0<=v<=1 for v in figure) or figure[0]>=figure[2] or figure[1]>=figure[3]:
                raise ProviderFailure('识别配图区域无效。')
        try:
            confidence = float(q.get('confidence',0))
            maximum = float(q.get('max_score',5))
        except (ValueError,TypeError):
            raise ProviderFailure('识别置信度或分值无效。')
        if not 0<=confidence<=1 or not 0<maximum<=1000:
            raise ProviderFailure('识别分值或置信度超出范围。')
        yield q

@shared_task(bind=True, max_retries=2, acks_late=True)
def process_batch(self, batch_id, generation):
    # Generation claim prevents repeated deliveries from duplicating questions.
    with transaction.atomic():
        batch = ImportBatch.objects.select_for_update().get(pk=batch_id)
        if batch.generation != generation or batch.status != 'queued':
            return
        batch.status='processing'
        batch.progress=5
        batch.message='正在准备页面。'
        batch.save()
    try:
        files=list(batch.files.order_by('created_at'))
        total=0
        extracted=[]
        seen_card_pages=set()
        for file_index,source in enumerate(files):
            for number,image in pages_of(source):
                total+=1
                if total>settings.MAX_BATCH_PAGES:
                    raise ValueError('批次页数超过上限，请拆成多个批次。')
                page=persist_page(batch,source,number,image)
                if batch.route=='card':
                    from .omr import read_card
                    data=read_card(image,batch,page)
                    if data['card_page'] in seen_card_pages:
                        raise ProviderFailure('检测到重复的答题卡页码，请移除重复页后重新上传批次。')
                    seen_card_pages.add(data['card_page'])
                else:
                    data=extract_page(image,source.role,batch.material,batch)
                extracted.extend((dict(q),page,source.role) for q in safe_extracted(data))
                ImportBatch.objects.filter(pk=batch_id).update(progress=min(85,10+int((file_index+1)/max(len(files),1)*70)),message=f'已识别 {total} 页，等待整理。')
        # All extraction must succeed before creating review data. A failed attempt leaves no partial bank entries.
        with transaction.atomic():
            groups={}
            for data,page,role in extracted:
                number=data['number']
                group=groups.setdefault(number,{'parts':[],'answers':[]})
                if role=='answer':
                    if data.get('printed_answer'):
                        group['answers'].append(data)
                else:
                    group['parts'].append((data,page))
            for number,group in groups.items():
                if not group['parts']:
                    # Never silently discard orphan reference answers.
                    group['parts']=[({'stem':'[答案页缺少对应题目，请补充题干]','issues':['答案页未匹配到题干'],'bbox':[0,0,1,1]},extracted[0][1])]
                first=group['parts'][0][0]
                issues=list(first.get('issues',[]))
                if len(group['parts'])>1:
                    issues.append('同题号跨页或重复，请确认合并结果与题号。')
                if not first.get('score_is_printed',False):
                    issues.append('分值为建议值，请确认。')
                q=Question.objects.create(workspace=batch.workspace,batch=batch,number=number,
                    stem='\n'.join(part.get('stem','') for part,_ in group['parts']),kind=first.get('kind','solution'),
                    options=first.get('options',[]),tags=first.get('tags',[]),source=batch.title,
                    confidence=first.get('confidence',0),issues=list(dict.fromkeys(issues)),
                    regions=[{'page':str(p.id),'bbox':part.get('bbox',[0,0,1,1])} for part,p in group['parts']],
                    figure_regions=[{'page':str(p.id),'bbox':box} for part,p in group['parts'] for box in part.get('figures',[])],
                    extracted_student_answer='\n'.join(part.get('student_answer','') for part,_ in group['parts']),
                    student_answer_present=any(part.get('student_answer_present',False) for part,_ in group['parts']),
                    suggested_max_score=first.get('max_score',5))
                refs=group['answers']+[part for part,_ in group['parts'] if part.get('printed_answer')]
                for ref in refs:
                    AnswerRevision.objects.create(workspace=batch.workspace,question=q,answer=ref['printed_answer'],
                        explanation=ref.get('explanation',''),origin='printed')
                if len(set(ref['printed_answer'] for ref in refs))>1:
                    q.issues.append('随卷参考答案存在冲突，请核对。')
                    q.save()
            batch.status='processing'
            batch.progress=90
            batch.message=f'识别完成，共 {len(groups)} 题。请审核题目、参考答案和分值；无答案题可点击AI解题。'
            if not groups:
                batch.status='blocked'
                batch.message='未识别到题目，请检查文件或补充清晰照片。'
            batch.save(update_fields=['status','progress','message','updated_at'])
        # Generate missing answers as pending revisions. Failure never converts into an official answer.
        if batch.route!='card':
            for question in batch.questions.filter(answers__isnull=True):
                if any('缺少' in issue or '缺图' in issue or '遮挡' in issue for issue in question.issues):
                    continue
                try:
                    solved=solve_question(question,region_images(question))
                    if isinstance(solved.get('answer'),str) and solved['answer'].strip() and not solved.get('issues'):
                        AnswerRevision.objects.create(workspace=batch.workspace,question=question,answer=solved['answer'],
                            explanation=str(solved.get('explanation','')),rubric=str(solved.get('rubric','')),origin='ai',model=settings.AI_MODEL)
                    else:
                        question.issues=list(dict.fromkeys(question.issues+['AI无法可靠解答，请核对题干条件并补充参考答案。']))
                        question.save()
                except (ProviderUnavailable,ProviderFailure):
                    ImportBatch.objects.filter(pk=batch_id).update(message='题目已提取，部分参考答案生成失败；可逐题重试AI解题或填写答案。')
                    break
        if batch.status!='blocked':
            ImportBatch.objects.filter(pk=batch_id).update(status='review',progress=100)
    except ProviderUnavailable as exc:
        ImportBatch.objects.filter(pk=batch_id).update(status='blocked',message=str(exc))
    except ProviderFailure as exc:
        ImportBatch.objects.filter(pk=batch_id).update(status='queued' if self.request.retries<self.max_retries else 'failed',message=str(exc))
        raise self.retry(exc=exc,countdown=30*(self.request.retries+1))
    except Exception:
        has_questions=batch.questions.exists()
        ImportBatch.objects.filter(pk=batch_id).update(status='review' if has_questions else 'failed',
            message='处理未完全完成，已保留原件及已提取题目。请检查文件并补全待审核内容。')
        import logging
        logging.getLogger(__name__).exception('Batch processing failed: %s',batch_id)
