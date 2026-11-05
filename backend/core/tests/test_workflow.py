from datetime import date
from decimal import Decimal
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core import mail, signing
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from PIL import Image
from core.models import *
from core.services import approve_question, publish_paper, set_grade, compare_answer, commit_batch
from core.tasks import process_batch, safe_extracted
from core.ai import ProviderUnavailable
from rest_framework.exceptions import ValidationError

class WorkflowFixture:
    def setUp(self):
        self.media=TemporaryDirectory()
        self.settings=override_settings(MEDIA_ROOT=self.media.name,CELERY_TASK_ALWAYS_EAGER=True,AI_BASE_URL='',AI_API_KEY='',AI_MODEL='')
        self.settings.enable()
        self.addCleanup(self.settings.disable)
        self.addCleanup(self.media.cleanup)
        self.user=get_user_model().objects.create_user('teacher@example.com',email='teacher@example.com',password='Teach!Pass2026')
        self.ws=Workspace.objects.create(owner=self.user,name='测试空间',email_verified=True)
        self.other=get_user_model().objects.create_user('other@example.com',password='Other!Pass2026')
        self.other_ws=Workspace.objects.create(owner=self.other,name='他人空间',email_verified=True)
        self.student=Student.objects.create(workspace=self.ws,name='学生甲')
        self.other_student=Student.objects.create(workspace=self.other_ws,name='学生乙')
        self.client=APIClient()
        self.client.force_login(self.user)

    def question(self,ws=None,kind='single',answer='B',batch=None,number='1'):
        ws=ws or self.ws
        q=Question.objects.create(workspace=ws,stem='测试题目'+number,kind=kind,number=number,batch=batch,tags=['方程'])
        a=AnswerRevision.objects.create(workspace=ws,question=q,answer=answer,origin='teacher')
        approve_question(q,a.id)
        q.refresh_from_db()
        return q

    def paper(self,q=None):
        q=q or self.question()
        p=Paper.objects.create(workspace=self.ws,title='测试卷')
        PaperItem.objects.create(workspace=self.ws,paper=p,question=q,label='1',position=1,max_score=5)
        return publish_paper(p)

    def batch(self,**kwargs):
        defaults=dict(workspace=self.ws,title='外部卷',route='external',purpose='assessment',material='answered',student=self.student,test_date=date.today(),status='review')
        defaults.update(kwargs)
        return ImportBatch.objects.create(**defaults)

    def image(self):
        out=BytesIO()
        Image.new('RGB',(600,800),'white').save(out,format='PNG')
        return SimpleUploadedFile('paper.png',out.getvalue(),content_type='image/png')

    def attempt(self,recognized=True):
        p=self.paper()
        sub=Submission.objects.create(workspace=self.ws,paper=p,student=self.student,test_date=date.today())
        return Attempt.objects.create(workspace=self.ws,submission=sub,item=p.items.first(),student_answer='A',recognition_confirmed=recognized)

class WorkflowTests(WorkflowFixture,TestCase):
    def test_tenant_lists_details_and_foreign_keys(self):
        res=self.client.get('/api/students/')
        self.assertEqual(len(res.data),1)
        self.assertEqual(self.client.get(f'/api/students/{self.other_student.id}/').status_code,404)
        self.assertEqual(self.client.patch(f'/api/students/{self.other_student.id}/',{'name':'越权'}).status_code,404)
        res=self.client.post('/api/plans/',{'student':str(self.other_student.id),'title':'越权'})
        self.assertEqual(res.status_code,400)
        other_q=self.question(ws=self.other_ws)
        own=self.question()
        self.assertEqual(self.client.post(f'/api/questions/{own.id}/approve/',{'answer_id':str(other_q.answers.first().id)},format='json').status_code,400)
        self.assertEqual(self.client.get(f'/api/questions/{other_q.id}/').status_code,404)

    def test_unapproved_answer_cannot_publish_or_grade(self):
        q=Question.objects.create(workspace=self.ws,stem='待审核题')
        AnswerRevision.objects.create(workspace=self.ws,question=q,answer='A',origin='ai')
        p=Paper.objects.create(workspace=self.ws,title='草稿')
        PaperItem.objects.create(workspace=self.ws,paper=p,question=q,label='1',position=1,max_score=5)
        self.assertEqual(self.client.post(f'/api/papers/{p.id}/publish/').status_code,400)
        a=self.attempt(recognized=False)
        self.assertEqual(self.client.post(f'/api/attempts/{a.id}/grade/',{'score':0},format='json').status_code,400)
        self.assertFalse(Mistake.objects.exists())

    def test_published_snapshot_does_not_change(self):
        q=self.question()
        p=self.paper(q)
        original=p.items.first().snapshot
        q.stem='修改后的题干'
        q.save()
        answer=AnswerRevision.objects.create(workspace=self.ws,question=q,answer='C',origin='teacher')
        approve_question(q,answer.id)
        self.assertEqual(p.items.first().snapshot,original)
        self.assertEqual(original['answer'],'B')
        self.assertEqual(self.client.post(f'/api/papers/{p.id}/items/',{'question':str(q.id)},format='json').status_code,400)

    def test_grade_change_updates_mistake_and_history(self):
        a=self.attempt()
        set_grade(a,0,'初评')
        self.assertTrue(Mistake.objects.get(attempt=a).active)
        set_grade(a,5,'纠正识别导致的误判')
        self.assertFalse(Mistake.objects.get(attempt=a).active)
        self.assertEqual(a.history.count(),2)
        set_grade(a,3,'过程分复核')
        self.assertTrue(Mistake.objects.get(attempt=a).active)
        a.refresh_from_db()
        res=self.client.post(f'/api/attempts/{a.id}/grade/',{'score':1,'revision':1},format='json')
        self.assertEqual(res.status_code,400)
        self.assertEqual(a.history.count(),3)

    def test_score_bounds_nan_and_precision(self):
        a=self.attempt()
        for score in [-1,6,'NaN','Infinity','1.234']:
            self.assertEqual(self.client.post(f'/api/attempts/{a.id}/grade/',{'score':score},format='json').status_code,400)
        self.assertFalse(Mistake.objects.exists())

    def test_commit_idempotence_and_fragment_no_total(self):
        b=self.batch(route='fragment')
        q=self.question(batch=b)
        q.extracted_student_answer='A'
        q.save()
        commit_batch(b)
        b.refresh_from_db()
        commit_batch(b)
        self.assertEqual(Submission.objects.filter(batch=b).count(),1)
        self.assertEqual(Attempt.objects.count(),1)
        self.assertFalse(Attempt.objects.first().recognition_confirmed)
        self.assertFalse(Mistake.objects.exists())
        attempt=Attempt.objects.first()
        attempt.recognition_confirmed=True
        attempt.save()
        set_grade(attempt,0)
        res=self.client.get(f'/api/students/{self.student.id}/report/')
        self.assertIsNone(res.data['timeline'][0]['score'])
        self.assertTrue(res.data['timeline'][0]['fragment'])

    def test_same_external_paper_reuse_and_mismatched_version_rejected(self):
        p=self.paper()
        b=self.batch(paper=p)
        q=self.question(batch=b)
        q.extracted_student_answer='A'
        q.save()
        commit_batch(b)
        self.assertEqual(Paper.objects.count(),1)
        b2=self.batch(paper=p)
        q2=self.question(batch=b2)
        q2.stem='不同版本题目'
        q2.save()
        with self.assertRaises(ValidationError):
            commit_batch(b2)
        self.assertEqual(Submission.objects.count(),1)

    def test_fragment_bound_to_full_paper_never_reports_total(self):
        p=self.paper()
        b=self.batch(paper=p,route='fragment')
        self.question(batch=b)
        commit_batch(b)
        attempt=Attempt.objects.first()
        attempt.recognition_confirmed=True
        attempt.save()
        set_grade(attempt,0)
        report=self.client.get(f'/api/students/{self.student.id}/report/')
        self.assertTrue(report.data['timeline'][0]['fragment'])
        self.assertIsNone(report.data['timeline'][0]['score'])

    def test_upload_validation_private_files_and_duplicate_pages(self):
        res=self.client.post('/api/batches/upload/',{'title':'外部卷','route':'external','purpose':'bank','material':'blank','test_date':'2026-11-05','files':[self.image(),self.image()],'roles':['paper','paper']},format='multipart')
        self.assertEqual(res.status_code,201,res.data)
        b=ImportBatch.objects.get(pk=res.data['id'])
        self.assertEqual(b.files.count(),1)
        file=b.files.first()
        self.assertEqual(self.client.get(f'/api/files/{file.id}/download/').status_code,200)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(f'/api/files/{file.id}/download/').status_code,404)
        self.client.force_login(self.user)
        res=self.client.post('/api/batches/upload/',{'title':'假图片','route':'external','purpose':'bank','material':'blank','test_date':'2026-11-05','files':SimpleUploadedFile('x.png',b'not an image')},format='multipart')
        self.assertEqual(res.status_code,400)

    def test_missing_provider_blocks_without_fabricated_data(self):
        b=self.batch(status='queued',generation=1,purpose='bank')
        SourceFile.objects.create(workspace=self.ws,batch=b,file=self.image(),original_name='paper.png',sha256='a'*64,role='paper')
        process_batch.run(str(b.id),1)
        b.refresh_from_db()
        self.assertEqual(b.status,'blocked')
        self.assertEqual(b.questions.count(),0)
        self.assertEqual(SourcePage.objects.count(),1)

    @patch('core.tasks.solve_question')
    @patch('core.tasks.extract_page')
    def test_student_answer_not_promoted_and_delivery_idempotent(self,extract,solve):
        extract.return_value={'questions':[{'number':'1','stem':'解方程x+1=3','kind':'fill','student_answer':'9','student_answer_present':True,'printed_answer':'','confidence':.9,'bbox':[0,0,1,1],'score_is_printed':True}]}
        solve.return_value={'answer':'2','explanation':'移项','issues':[]}
        b=self.batch(status='queued',generation=1)
        SourceFile.objects.create(workspace=self.ws,batch=b,file=self.image(),original_name='paper.png',sha256='a'*64,role='student')
        process_batch.run(str(b.id),1)
        process_batch.run(str(b.id),1)
        b.refresh_from_db()
        self.assertEqual(b.status,'review')
        self.assertEqual(b.questions.count(),1)
        q=b.questions.first()
        self.assertEqual(q.extracted_student_answer,'9')
        self.assertEqual(q.answers.count(),1)
        self.assertEqual(q.answers.first().answer,'2')
        self.assertEqual(q.answers.first().status,'pending')
        self.assertFalse(Attempt.objects.exists())

    @patch('core.tasks.solve_question')
    @patch('core.tasks.extract_page')
    def test_reference_page_maps_by_number(self,extract,solve):
        extract.side_effect=[{'questions':[{'number':'1','stem':'题目A','bbox':[0,0,1,1]}]},
                             {'questions':[{'number':'1','printed_answer':'42','bbox':[0,0,1,1]}]}]
        b=self.batch(status='queued',generation=1)
        for role in ['paper','answer']:
            SourceFile.objects.create(workspace=self.ws,batch=b,file=self.image(),original_name='paper.png',sha256=role*8,role=role)
        process_batch.run(str(b.id),1)
        q=b.questions.first()
        self.assertEqual(q.stem,'题目A')
        self.assertEqual(q.answers.first().origin,'printed')
        self.assertEqual(q.answers.first().answer,'42')
        solve.assert_not_called()

    def test_crop_pages_and_foreign_sources_are_scoped(self):
        b=self.batch()
        file=SourceFile.objects.create(workspace=self.other_ws,batch=self.batch(workspace=self.other_ws,student=self.other_student),file=self.image(),original_name='paper.png',sha256='b'*64,role='paper')
        page=SourcePage.objects.create(workspace=self.other_ws,source_file=file,number=1,image=self.image(),width=600,height=800)
        self.assertEqual(self.client.get(f'/api/pages/{page.id}/image/').status_code,404)
        res=self.client.post('/api/questions/',{'stem':'伪造引用','regions':[{'page':str(page.id),'bbox':[0,0,1,1]}]},format='json')
        self.assertEqual(res.status_code,400)
        res=self.client.post('/api/questions/',{'stem':'伪造配图','figure_regions':[{'page':str(page.id),'bbox':[0,0,1,1]}]},format='json')
        self.assertEqual(res.status_code,400)

    def test_practice_preserves_origin_and_new_attempt(self):
        a=self.attempt()
        set_grade(a,0)
        mistake=Mistake.objects.get(attempt=a)
        res=self.client.post('/api/mistakes/practice/',{'ids':[str(mistake.id)],'mode':'original','title':'复练'},format='json')
        self.assertEqual(res.status_code,201,res.data)
        p=Paper.objects.get(pk=res.data['id'])
        self.assertEqual(p.items.first().origin_response,a)
        self.assertEqual(p.items.first().snapshot,a.item.snapshot)
        res=self.client.post('/api/submissions/',{'paper':str(p.id),'student':str(self.student.id),'test_date':'2026-11-05'},format='json')
        self.assertEqual(res.status_code,201,res.data)
        self.assertEqual(Attempt.objects.count(),2)
        self.assertTrue(Mistake.objects.get(attempt=a).active)
        res=self.client.post('/api/submissions/',{'paper':str(p.id),'student':str(Student.objects.create(workspace=self.ws,name='另一个学生').id),'test_date':'2026-11-05'},format='json')
        self.assertEqual(res.status_code,400)

    def test_conservative_comparison(self):
        self.assertTrue(compare_answer('fill','0.5','1/2'))
        self.assertFalse(compare_answer('fill','1/3','1/2'))
        self.assertIsNone(compare_answer('fill','x/x','1'))
        self.assertIsNone(compare_answer('fill','1/0','2'))
        self.assertIsNone(compare_answer('solution','same','same'))
        self.assertTrue(compare_answer('multiple','BA','AB'))
        self.assertIsNone(compare_answer('single','AB','AB'))
        self.assertIsNone(compare_answer('single','','B'))

    def test_malformed_ai_region_rejected(self):
        with self.assertRaises(Exception):
            list(safe_extracted({'questions':[{'number':'1','bbox':[1,0,0,1]}]}))
        with self.assertRaises(Exception):
            list(safe_extracted({'questions':[{'number':'1','figures':[['bad']]}]}))

    def test_dashboard_empty_or_populated(self):
        res=self.client.get('/api/dashboard/')
        self.assertEqual(res.status_code,200,res.data)
        self.assertEqual(res.data['students'],1)
        self.assertFalse(res.data['ai']['configured'])

    def test_timeout_recovery_preserves_review_data(self):
        from core.tasks import recover_stale_batches
        from django.utils import timezone
        from datetime import timedelta
        b=self.batch(status='processing')
        q=Question.objects.create(workspace=self.ws,batch=b,stem='已识别题目')
        ImportBatch.objects.filter(pk=b.id).update(updated_at=timezone.now()-timedelta(minutes=25))
        self.assertEqual(recover_stale_batches(),1)
        b.refresh_from_db()
        self.assertEqual(b.status,'review')
        self.assertTrue(b.questions.filter(id=q.id).exists())

    def test_cloned_question_has_pending_answer_and_no_batch(self):
        q=self.question()
        res=self.client.post(f'/api/questions/{q.id}/clone/')
        self.assertEqual(res.status_code,201,res.data)
        self.assertEqual(res.data['status'],'draft')
        self.assertIsNone(res.data['batch'])
        self.assertEqual(res.data['answers'][0]['status'],'pending')

    def test_bulk_approval_rolls_back_cross_tenant_request(self):
        own=Question.objects.create(workspace=self.ws,stem='我方草稿')
        answer=AnswerRevision.objects.create(workspace=self.ws,question=own,answer='A',origin='ai')
        other=self.question(ws=self.other_ws)
        res=self.client.post('/api/questions/bulk-approve/',{'items':[
            {'id':str(own.id),'answer_id':str(answer.id)},
            {'id':str(other.id),'answer_id':str(other.answers.first().id)}]},format='json')
        self.assertEqual(res.status_code,404)
        own.refresh_from_db()
        self.assertEqual(own.status,'draft')
        answer.refresh_from_db()
        self.assertEqual(answer.status,'pending')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_registration_verification_and_password_reset(self):
        self.client.logout()
        res=self.client.post('/api/auth/register/',{'email':'new@example.com','name':'新教师','password':'Strong!New2026'},format='json')
        self.assertEqual(res.status_code,201,res.data)
        user=get_user_model().objects.get(username='new@example.com')
        self.assertFalse(user.is_active)
        token=mail.outbox[-1].body.split('?verify=')[1]
        self.assertEqual(self.client.post('/api/auth/verify/',{'token':token},format='json').status_code,200)
        self.assertEqual(self.client.post('/api/auth/login/',{'email':'new@example.com','password':'Strong!New2026'},format='json').status_code,200)
        self.client.post('/api/auth/forgot/',{'email':'new@example.com'},format='json')
        reset=mail.outbox[-1].body.split('?reset=')[1]
        self.assertEqual(self.client.post('/api/auth/reset/',{'token':reset,'password':'Changed!Pass2026'},format='json').status_code,200)
        self.assertEqual(self.client.post('/api/auth/reset/',{'token':reset,'password':'Changed!Pass2026'},format='json').status_code,400)

    def test_login_csrf_required(self):
        client=APIClient(enforce_csrf_checks=True)
        self.assertEqual(client.post('/api/auth/login/',{'email':'teacher@example.com','password':'Teach!Pass2026'},format='json').status_code,403)
        res=client.get('/api/session/')
        self.assertEqual(client.post('/api/auth/login/',{'email':'teacher@example.com','password':'Teach!Pass2026'},format='json',HTTP_X_CSRFTOKEN=res.data['csrf']).status_code,200)
