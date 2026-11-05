import hashlib
from io import BytesIO
from datetime import date
from difflib import SequenceMatcher
from PIL import Image, UnidentifiedImageError
from django.conf import settings
from django.db import transaction
from django.db.models import Count, Sum
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, mixins
from rest_framework.decorators import action, api_view
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from .models import *
from .serializers import *
from .services import *
from . import ai

class OwnedViewSet(viewsets.GenericViewSet):
    def get_queryset(self):
        return self.queryset.filter(workspace=self.request.user.workspace)
    def perform_create(self,serializer):
        serializer.save(workspace=self.request.user.workspace)

class EditableViewSet(mixins.ListModelMixin,mixins.CreateModelMixin,mixins.RetrieveModelMixin,mixins.UpdateModelMixin,OwnedViewSet):
    pass

class ReadViewSet(mixins.ListModelMixin,mixins.RetrieveModelMixin,OwnedViewSet):
    pass

class StudentViewSet(EditableViewSet):
    queryset=Student.objects.all()
    serializer_class=StudentSerializer
    @action(detail=True,methods=['get'])
    def report(self,request,pk=None):
        student=self.get_object()
        submissions=student.submissions.select_related('paper').prefetch_related('attempts__item')
        timeline=[]
        knowledge={}
        for submission in submissions:
            attempts=list(submission.attempts.all())
            complete=bool(attempts) and len(attempts)==submission.paper.items.count() and all(a.final_score is not None for a in attempts)
            total=sum((a.final_score or 0 for a in attempts),Decimal(0))
            maximum=sum((a.item.max_score for a in attempts),Decimal(0))
            timeline.append({'id':str(submission.id),'title':submission.paper.title,'date':submission.test_date,
                'score':str(total) if complete and not submission.is_fragment else None,
                'maximum':str(maximum) if complete and not submission.is_fragment else None,
                'reviewed':sum(a.final_score is not None for a in attempts),'count':len(attempts),'fragment':submission.is_fragment})
            for a in attempts:
                if a.final_score is None:
                    continue
                for tag in a.item.snapshot.get('tags',[]):
                    stats=knowledge.setdefault(tag,{'attempts':0,'wrong':0})
                    stats['attempts']+=1
                    stats['wrong']+=a.final_score<a.item.max_score
        return Response({'student':StudentSerializer(student).data,'timeline':timeline,'knowledge':knowledge,
            'mistakes':MistakeSerializer(Mistake.objects.filter(workspace=student.workspace,attempt__submission__student=student),many=True).data,
            'plans':PlanSerializer(student.plans.all(),many=True).data})

class PlanViewSet(EditableViewSet):
    queryset=LearningPlan.objects.all()
    serializer_class=PlanSerializer
    def get_queryset(self):
        qs=super().get_queryset()
        return qs.filter(student_id=self.request.query_params['student']) if self.request.query_params.get('student') else qs

class QuestionViewSet(EditableViewSet):
    queryset=Question.objects.prefetch_related('answers')
    serializer_class=QuestionSerializer
    def get_queryset(self):
        qs=super().get_queryset()
        for field in ('status','kind','grade','batch'):
            if self.request.query_params.get(field):
                qs=qs.filter(**{field:self.request.query_params[field]})
        if self.request.query_params.get('search'):
            qs=qs.filter(stem__icontains=self.request.query_params['search'])
        if self.request.query_params.get('tag'):
            tag=self.request.query_params['tag']
            ids=[q.id for q in qs if tag in q.tags]
            qs=qs.filter(id__in=ids)
        return qs
    def perform_update(self,serializer):
        q=serializer.instance
        if q.batch and q.batch.status=='committed':
            raise ValidationError('已归档的导入记录不能修改；请在题库中复制题目后修订。')
        serializer.save(status='draft',revision=q.revision+1)
    @action(detail=True,methods=['post'])
    def clone(self,request,pk=None):
        original=self.get_object()
        with transaction.atomic():
            q=Question.objects.create(workspace=original.workspace,number=original.number,stem=original.stem,kind=original.kind,
                options=original.options,tags=original.tags,difficulty=original.difficulty,grade=original.grade,chapter=original.chapter,
                regions=original.regions,figure_regions=original.figure_regions,source=original.source+' · 修订副本',
                suggested_max_score=original.suggested_max_score)
            answer=approved_answer(original)
            if answer:
                AnswerRevision.objects.create(workspace=q.workspace,question=q,answer=answer.answer,explanation=answer.explanation,rubric=answer.rubric,origin='teacher')
            audit(q.workspace,'question_cloned',q,original=str(original.id))
        return Response(self.get_serializer(q).data,status=201)
    @action(detail=True,methods=['post'])
    def answer(self,request,pk=None):
        q=self.get_object()
        ser=AnswerSerializer(data={**request.data,'question':q.id},context=self.get_serializer_context())
        ser.is_valid(raise_exception=True)
        answer=ser.save(workspace=q.workspace,origin='teacher')
        return Response(AnswerSerializer(answer).data,status=201)
    @action(detail=True,methods=['post'])
    def approve(self,request,pk=None):
        q=approve_question(self.get_object(),request.data.get('answer_id'),request.data.get('confirm_issues') is True)
        return Response(self.get_serializer(q).data)
    @action(detail=False,methods=['post'],url_path='bulk-approve')
    def bulk_approve(self,request):
        items=request.data.get('items',[])
        if not isinstance(items,list) or not 1<=len(items)<=100 or any(not isinstance(item,dict) for item in items):
            raise ValidationError('请提供1至100道待确认题目。')
        with transaction.atomic():
            result=[]
            for item in items:
                q=get_object_or_404(Question,id=item.get('id'),workspace=request.user.workspace)
                result.append(approve_question(q,item.get('answer_id'),item.get('confirm_issues') is True))
        return Response(self.get_serializer(result,many=True).data)
    @action(detail=True,methods=['post'])
    def solve(self,request,pk=None):
        q=self.get_object()
        from .tasks import region_images
        try:
            data=ai.solve_question(q,region_images(q))
        except (ai.ProviderUnavailable,ai.ProviderFailure) as exc:
            return Response({'detail':str(exc)},status=503)
        issues=data.get('issues',[])
        if not isinstance(issues,list) or any(not isinstance(x,str) for x in issues) or not isinstance(data.get('answer',''),str):
            raise ValidationError('AI解答格式无效。')
        if issues or not data.get('answer','').strip():
            q.issues=list(dict.fromkeys(q.issues+issues+['AI未能可靠解答，请核对题目条件。']))
            q.status='draft'
            q.save()
        else:
            AnswerRevision.objects.create(workspace=q.workspace,question=q,answer=data['answer'],explanation=data.get('explanation',''),
                rubric=data.get('rubric',''),origin='ai',model=settings.AI_MODEL)
            if q.answers.filter(origin='printed').exclude(answer=data['answer']).exists():
                q.issues=list(dict.fromkeys(q.issues+['AI解答与随卷答案可能不一致，请核对。']))
                q.status='draft'
                q.save()
        return Response(self.get_serializer(q).data)
    @action(detail=True,methods=['get'])
    def duplicates(self,request,pk=None):
        q=self.get_object()
        candidates=[]
        for other in Question.objects.filter(workspace=q.workspace,status='approved').exclude(pk=q.pk).order_by('-created_at')[:2000]:
            similarity=SequenceMatcher(None,q.stem,other.stem).ratio()
            if similarity>=0.65:
                candidates.append({'question':QuestionSerializer(other).data,'similarity':round(similarity,3)})
        return Response(sorted(candidates,key=lambda x:-x['similarity'])[:10])
    @action(detail=True,methods=['post'])
    def link(self,request,pk=None):
        q=self.get_object()
        other=get_object_or_404(Question,pk=request.data.get('question_id'),workspace=q.workspace,status='approved')
        if q.pk==other.pk:
            raise ValidationError('不能关联题目自身。')
        answer=approved_answer(other)
        if not answer:
            raise ValidationError('关联题目没有已确认答案。')
        AnswerRevision.objects.create(workspace=q.workspace,question=q,answer=answer.answer,explanation=answer.explanation,rubric=answer.rubric,origin='bank')
        audit(q.workspace,'question_linked',q,linked_question=str(other.id))
        return Response(self.get_serializer(q).data)
    @action(detail=True,methods=['post'])
    def split(self,request,pk=None):
        q=self.get_object()
        if q.status=='approved' or (q.batch and q.batch.status=='committed'):
            raise ValidationError('已确认题目不能拆分。')
        if PaperItem.objects.filter(question=q).exists():
            raise ValidationError('曾用于试卷的题目请先另存修订副本，再拆分。')
        parts=request.data.get('parts',[])
        if not isinstance(parts,list) or not 2<=len(parts)<=10:
            raise ValidationError('需提供2至10个题块。')
        result=[]
        with transaction.atomic():
            for part in parts:
                ser=self.get_serializer(data=part)
                ser.is_valid(raise_exception=True)
                new=ser.save(workspace=q.workspace,batch=q.batch,source=q.source,issues=['拆分后请核对题干及参考答案。'])
                result.append(new)
            audit(q.workspace,'question_split',q,new_ids=[str(v.id) for v in result])
            q.delete()
        return Response(self.get_serializer(result,many=True).data)
    @action(detail=False,methods=['post'])
    def merge(self,request):
        ids=request.data.get('ids',[])
        if not isinstance(ids,list) or not 2<=len(set(ids))<=10:
            raise ValidationError('请选择2至10个题块。')
        with transaction.atomic():
            qs=list(self.get_queryset().select_for_update().filter(id__in=ids))
            if len(qs)!=len(set(ids)) or any(q.status!='draft' for q in qs) or len(set(q.batch_id for q in qs))!=1:
                raise ValidationError('只能合并同一批次中未确认的题块。')
            if qs[0].batch and qs[0].batch.status=='committed':
                raise ValidationError('已归档批次不能合并。')
            if PaperItem.objects.filter(question__in=qs).exists():
                raise ValidationError('曾用于试卷的题目请先另存修订副本，再合并。')
            qs.sort(key=lambda q:ids.index(str(q.id)))
            first=qs[0]
            first.stem='\n'.join(q.stem for q in qs)
            first.regions=[r for q in qs for r in q.regions]
            if len(first.regions)>20:
                raise ValidationError('合并后区域过多。')
            first.extracted_student_answer='\n'.join(q.extracted_student_answer for q in qs)
            first.issues=['合并后请重新核对题干与参考答案。']
            first.save()
            for q in qs[1:]:
                q.answers.update(question=first)
                q.delete()
            audit(first.workspace,'question_merged',first)
        return Response(self.get_serializer(first).data)

class PaperViewSet(EditableViewSet):
    queryset=Paper.objects.prefetch_related('items')
    serializer_class=PaperSerializer
    def perform_update(self,serializer):
        with transaction.atomic():
            paper=Paper.objects.select_for_update().get(pk=serializer.instance.pk)
            if paper.status=='published':
                raise ValidationError('已发布试卷不可修改，请新建版本。')
            serializer.instance=paper
            serializer.save()
    @action(detail=True,methods=['post'])
    def items(self,request,pk=None):
        paper=self.get_object()
        with transaction.atomic():
            paper=Paper.objects.select_for_update().get(pk=paper.pk)
            if paper.status!='draft':
                raise ValidationError('已发布试卷不可修改。')
            q=get_object_or_404(Question,id=request.data.get('question'),workspace=paper.workspace,status='approved')
            maximum=decimal_score(request.data.get('max_score',5))
            if maximum<=0:
                raise ValidationError('满分需大于0。')
            position=max(paper.items.values_list('position',flat=True),default=0)+1
            item=PaperItem.objects.create(workspace=paper.workspace,paper=paper,question=q,position=position,label=str(position),max_score=maximum)
        return Response(PaperItemSerializer(item).data,status=201)
    @action(detail=True,methods=['post'],url_path='remove-item')
    def remove_item(self,request,pk=None):
        with transaction.atomic():
            paper=Paper.objects.select_for_update().get(pk=self.get_object().pk)
            if paper.status!='draft':
                raise ValidationError('已发布试卷不可修改。')
            get_object_or_404(PaperItem,paper=paper,id=request.data.get('item')).delete()
        return Response({'message':'已移除题目。'})
    @action(detail=True,methods=['post'])
    def publish(self,request,pk=None):
        return Response(self.get_serializer(publish_paper(self.get_object())).data)
    @action(detail=False,methods=['post'])
    def generate(self,request):
        workspace=request.user.workspace
        qs=Question.objects.filter(workspace=workspace,status='approved')
        if request.data.get('kind'):
            qs=qs.filter(kind=request.data['kind'])
        if request.data.get('difficulty'):
            qs=qs.filter(difficulty=request.data['difficulty'])
        tags=request.data.get('tags',[])
        if not isinstance(tags,list):
            raise ValidationError('知识点格式错误。')
        pool=[q for q in qs if not tags or set(tags)&set(q.tags)]
        count=request.data.get('count',10)
        if not isinstance(count,int) or not 1<=count<=100:
            raise ValidationError('题量需为1至100。')
        if len(pool)<count:
            raise ValidationError(f'符合条件的已审核题目仅 {len(pool)} 道，请减少题量或调整筛选。')
        import random
        with transaction.atomic():
            paper=Paper.objects.create(workspace=workspace,title=str(request.data.get('title','知识点专项测试'))[:200])
            for i,q in enumerate(random.sample(pool,count),1):
                PaperItem.objects.create(workspace=workspace,paper=paper,question=q,label=str(i),position=i,max_score=q.suggested_max_score)
        return Response(self.get_serializer(paper).data,status=201)
    @action(detail=True,methods=['get'])
    def card(self,request,pk=None):
        paper=self.get_object()
        if paper.status!='published':
            raise ValidationError('请先发布试卷。')
        student=get_object_or_404(Student,pk=request.query_params.get('student'),workspace=paper.workspace)
        validate_paper_student(paper,student)
        from .omr import create_card
        return FileResponse(BytesIO(create_card(paper,student)),content_type='application/pdf',as_attachment=True,filename='answer-card.pdf')

class BatchViewSet(ReadViewSet):
    queryset=ImportBatch.objects.prefetch_related('files__pages','questions__answers')
    serializer_class=BatchSerializer
    @action(detail=False,methods=['post'])
    def upload(self,request):
        ser=self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        files=request.FILES.getlist('files')
        roles=request.data.getlist('roles') if hasattr(request.data,'getlist') else []
        if not files or len(files)>30 or sum(f.size for f in files)>50*1024*1024:
            raise ValidationError('请上传1至30个文件，合计不超过50MB。')
        validated=[]
        for index,file in enumerate(files):
            role=roles[index] if index<len(roles) else 'paper'
            if role not in ('paper','answer','student'):
                raise ValidationError('文件角色无效。')
            data=file.read()
            file.seek(0)
            suffix=file.name.rsplit('.',1)[-1].lower()
            if suffix=='pdf':
                if not data.startswith(b'%PDF-'):
                    raise ValidationError('PDF文件格式无效。')
                import pypdfium2 as pdfium
                try:
                    doc=pdfium.PdfDocument(data)
                    if len(doc)>settings.MAX_BATCH_PAGES:
                        raise ValidationError('PDF页数超过单批上限。')
                    doc.close()
                except ValidationError:
                    raise
                except Exception:
                    raise ValidationError('PDF损坏或受密码保护。')
            elif suffix in ('jpg','jpeg','png'):
                try:
                    image=Image.open(BytesIO(data))
                    if image.format not in ('JPEG','PNG') or image.width*image.height>40_000_000:
                        raise ValueError()
                    image.verify()
                except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError):
                    raise ValidationError('图片无效或分辨率过大。')
            else:
                raise ValidationError('仅支持PDF、JPG和PNG。')
            validated.append((file,role,hashlib.sha256(data).hexdigest()))
        with transaction.atomic():
            batch=ser.save(workspace=request.user.workspace)
            seen=set()
            for file,role,digest in validated:
                if (digest,role) in seen:
                    continue
                seen.add((digest,role))
                SourceFile.objects.create(workspace=batch.workspace,batch=batch,file=file,original_name=file.name[:255],role=role,sha256=digest)
            audit(batch.workspace,'batch_uploaded',batch)
        return Response(self.get_serializer(batch).data,status=201)
    @action(detail=True,methods=['post'])
    def process(self,request,pk=None):
        with transaction.atomic():
            batch=ImportBatch.objects.select_for_update().get(pk=self.get_object().pk)
            if batch.status in ('processing','queued','committed'):
                raise ValidationError('批次正在处理或已经归档。')
            if batch.questions.exists():
                raise ValidationError('已有审核题目，请直接审核，避免重试覆盖编辑。')
            batch.status='queued'
            batch.generation+=1
            batch.message='等待后台处理。'
            batch.save()
        from .tasks import process_batch
        try:
            task=process_batch.delay(str(batch.id),batch.generation)
            ImportBatch.objects.filter(pk=batch.pk).update(task_id=task.id)
        except Exception:
            ImportBatch.objects.filter(pk=batch.pk).update(status='failed',message='任务未能完成或入队失败，请检查后台服务。')
        batch.refresh_from_db()
        return Response(self.get_serializer(batch).data)
    @action(detail=True,methods=['post'])
    def commit(self,request,pk=None):
        return Response(self.get_serializer(commit_batch(self.get_object())).data)

class FileViewSet(ReadViewSet):
    queryset=SourceFile.objects.all()
    serializer_class=FileSerializer
    @action(detail=True,methods=['get'])
    def download(self,request,pk=None):
        file=self.get_object()
        response=FileResponse(file.file.open('rb'),as_attachment=True,filename=file.original_name)
        response['Cache-Control']='private, no-store'
        return response

class PageViewSet(ReadViewSet):
    queryset=SourcePage.objects.all()
    serializer_class=PageSerializer
    @action(detail=True,methods=['get'])
    def image(self,request,pk=None):
        page=self.get_object()
        if request.query_params.get('bbox'):
            try:
                box=[float(v) for v in request.query_params['bbox'].split(',')]
                validate_regions([{'page':str(page.id),'bbox':box}],page.workspace)
                with page.image.open('rb') as f:
                    img=Image.open(f).convert('RGB')
                    img=img.crop((int(box[0]*img.width),int(box[1]*img.height),int(box[2]*img.width),int(box[3]*img.height)))
                buffer=BytesIO()
                img.save(buffer,format='PNG')
                buffer.seek(0)
                response=FileResponse(buffer,content_type='image/png')
            except (ValueError,TypeError):
                raise ValidationError('裁切区域格式错误。')
        else:
            response=FileResponse(page.image.open('rb'),content_type='image/jpeg')
        response['Cache-Control']='private, no-store'
        return response

class SubmissionViewSet(ReadViewSet):
    queryset=Submission.objects.select_related('student','paper').prefetch_related('attempts__item','attempts__history')
    serializer_class=SubmissionSerializer
    def get_queryset(self):
        qs=super().get_queryset()
        return qs.filter(student_id=self.request.query_params['student']) if self.request.query_params.get('student') else qs
    def create(self,request):
        workspace=request.user.workspace
        paper=get_object_or_404(Paper,pk=request.data.get('paper'),workspace=workspace,status='published')
        student=get_object_or_404(Student,pk=request.data.get('student'),workspace=workspace)
        validate_paper_student(paper,student)
        try:
            test_date=date.fromisoformat(request.data.get('test_date',''))
        except (ValueError,TypeError):
            raise ValidationError('请选择测试日期。')
        with transaction.atomic():
            submission=Submission.objects.create(workspace=workspace,paper=paper,student=student,test_date=test_date)
            for item in paper.items.all():
                Attempt.objects.create(workspace=workspace,submission=submission,item=item)
        return Response(self.get_serializer(submission).data,status=201)

class AttemptViewSet(ReadViewSet):
    queryset=Attempt.objects.select_related('item','submission').prefetch_related('history')
    serializer_class=AttemptSerializer
    @action(detail=True,methods=['post'])
    def recognize(self,request,pk=None):
        with transaction.atomic():
            attempt=Attempt.objects.select_for_update().get(pk=self.get_object().pk)
            if attempt.final_score is not None:
                raise ValidationError('已定分作答不可覆盖识别，请使用改分操作。')
            text=request.data.get('student_answer',attempt.student_answer)
            if not isinstance(text,str) or len(text)>30000:
                raise ValidationError('作答文字无效。')
            if request.data.get('confirmed') is not True:
                raise ValidationError('请明确确认作答识别。')
            attempt.student_answer=text
            attempt.recognition_confirmed=True
            attempt.revision+=1
            attempt.save()
            suggest_objective_grade(attempt)
            attempt.refresh_from_db()
        return Response(self.get_serializer(attempt).data)
    @action(detail=True,methods=['post'])
    def suggest(self,request,pk=None):
        attempt=self.get_object()
        if not attempt.recognition_confirmed:
            raise ValidationError('请先确认学生作答识别。')
        if not suggest_objective_grade(attempt):
            from .tasks import region_images
            proxy=type('QuestionRegions',(),{'regions':attempt.regions,'workspace':attempt.workspace})()
            try:
                result=ai.grade_solution(attempt,region_images(proxy))
            except (ai.ProviderUnavailable,ai.ProviderFailure) as exc:
                return Response({'detail':str(exc)},status=503)
            if result.get('issues') or result.get('score') is None:
                attempt.suggestion='AI无法可靠评分，请教师评阅。'+str(result.get('feedback',''))
                attempt.suggested_score=None
            else:
                attempt.suggested_score=decimal_score(result['score'],attempt.item.max_score)
                attempt.suggestion=str(result.get('feedback',''))
            attempt.save()
        return Response(self.get_serializer(attempt).data)
    @action(detail=True,methods=['post'])
    def grade(self,request,pk=None):
        attempt=set_grade(self.get_object(),request.data.get('score'),str(request.data.get('feedback','')),expected_revision=request.data.get('revision'))
        return Response(self.get_serializer(attempt).data)

class MistakeViewSet(mixins.ListModelMixin,mixins.RetrieveModelMixin,mixins.UpdateModelMixin,OwnedViewSet):
    queryset=Mistake.objects.select_related('attempt__submission__student','attempt__item').prefetch_related('attempt__history')
    serializer_class=MistakeSerializer
    def get_queryset(self):
        qs=super().get_queryset()
        if self.request.query_params.get('student'):
            qs=qs.filter(attempt__submission__student_id=self.request.query_params['student'])
        return qs
    @action(detail=False,methods=['post'])
    def practice(self,request):
        ids=request.data.get('ids',[])
        if not isinstance(ids,list) or not ids:
            raise ValidationError('请选择需要复练的错题。')
        mistakes=list(self.get_queryset().filter(id__in=ids,active=True).order_by('mastered','-created_at'))
        if len(mistakes)!=len(set(ids)) or len(mistakes)>100:
            raise ValidationError('错题无效或超过100道。')
        if len({m.attempt.submission.student_id for m in mistakes})!=1:
            raise ValidationError('请为同一个学生选择错题。')
        with transaction.atomic():
            paper=Paper.objects.create(workspace=request.user.workspace,title=str(request.data.get('title','错题巩固练习'))[:200],source='practice')
            mode=request.data.get('mode','original')
            if mode not in ('original','similar'):
                raise ValidationError('复练方式无效。')
            used=set()
            for index,mistake in enumerate(mistakes,1):
                original=mistake.attempt.item
                q=original.question
                snapshot=original.snapshot
                if mode=='similar':
                    tags=set(original.snapshot.get('tags',[]))
                    candidates=[c for c in Question.objects.filter(workspace=paper.workspace,status='approved',kind=q.kind)
                        .exclude(pk=q.pk).order_by('difficulty') if c.id not in used and tags&set(c.tags)]
                    if not candidates:
                        raise ValidationError('缺少已审核同类题，请补充题库或选择原题复练。')
                    q=min(candidates,key=lambda c:abs(c.difficulty-original.question.difficulty))
                    snapshot=question_snapshot(q)
                used.add(q.id)
                PaperItem.objects.create(workspace=paper.workspace,paper=paper,question=q,position=index,label=str(index),
                    max_score=original.max_score,snapshot=snapshot,origin_response=mistake.attempt)
            paper.status='published'
            paper.published_at=timezone.now()
            paper.save()
            audit(paper.workspace,'practice_created',paper,mistakes=[str(m.id) for m in mistakes])
        return Response(PaperSerializer(paper).data,status=201)

class AuditViewSet(ReadViewSet):
    queryset=AuditEvent.objects.all()
    serializer_class=AuditSerializer

@api_view(['GET'])
def dashboard(request):
    ws=request.user.workspace
    return Response({'students':Student.objects.filter(workspace=ws,archived=False).count(),
        'questions':Question.objects.filter(workspace=ws,status='approved').count(),
        'pending_batches':ImportBatch.objects.filter(workspace=ws).exclude(status='committed').count(),
        'pending_grades':Attempt.objects.filter(workspace=ws,final_score__isnull=True).count(),
        'active_mistakes':Mistake.objects.filter(workspace=ws,active=True,mastered=False).count(),
        'recent_batches':BatchSerializer(ImportBatch.objects.filter(workspace=ws)[:5],many=True).data,
        'plans':PlanSerializer(LearningPlan.objects.filter(workspace=ws,completed=False).order_by('due_date')[:6],many=True).data,
        'ai':{'configured':ai.configured(),'model':settings.AI_MODEL,'auto_grading':settings.AUTO_GRADING_ENABLED,
              'calls':ImportBatch.objects.filter(workspace=ws).aggregate(total=Sum('ai_calls'))['total'] or 0,
              'tokens':ImportBatch.objects.filter(workspace=ws).aggregate(total=Sum('usage_tokens'))['total'] or 0}})
