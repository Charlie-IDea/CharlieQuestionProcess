from datetime import timedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from core.models import Workspace, Student, Question, AnswerRevision, Paper, PaperItem, Submission, Attempt, LearningPlan, ImportBatch
from core.services import approve_question, publish_paper, set_grade, suggest_objective_grade

class Command(BaseCommand):
    help='仅在DEBUG模式建立明确标记的演示数据；不会重置已有账户。'
    def add_arguments(self,parser):
        parser.add_argument('--email',default='demo@zhixu.local')
        parser.add_argument('--password',default='ZhixuDemo!2026')
    @transaction.atomic
    def handle(self,*args,**options):
        if not settings.DEBUG:
            raise CommandError('演示数据只能在DEBUG模式建立。')
        User=get_user_model()
        if User.objects.filter(username=options['email']).exists():
            self.stdout.write('演示账户已存在，保留当前数据。')
            return
        user=User.objects.create_user(username=options['email'],email=options['email'],password=options['password'],first_name='林老师')
        ws=Workspace.objects.create(owner=user,name='林老师的教学空间',email_verified=True)
        students=[Student.objects.create(workspace=ws,name=name,grade=grade,textbook='人教版',goal=goal,notes='演示学生，非真实个人资料。')
            for name,grade,goal in [('陈同学','初三','巩固二次函数与相似三角形，提升解题过程的完整性。'),('许同学','高一','建立函数概念，掌握集合与基本不等式。'),('周同学','初二','梳理一次函数，养成规范计算与验算习惯。')]]
        examples=[
            ('single','若 $x^2-5x+6=0$，则方程的两根是（ ）',['A. 1和6','B. 2和3','C. -2和-3','D. -1和-6'],'B','因式分解得 $(x-2)(x-3)=0$。',['一元二次方程'],2),
            ('fill','函数 $y=(x-2)^2+3$ 的顶点坐标为 ______。',[],'(2,3)','由顶点式可直接读出顶点为 $(2,3)$。',['二次函数'],2),
            ('solution','已知二次函数 $y=x^2-4x+3$，求其与 $x$ 轴的交点坐标，并求对称轴。',[],'$(1,0)$、$(3,0)$；对称轴 $x=2$。','令 $y=0$，得 $(x-1)(x-3)=0$；对称轴为两根的平均值。',['二次函数','一元二次方程'],3),
            ('fill','计算：$\\frac{1}{2}+\\frac{1}{3}=$ ______。',[],'5/6','通分得到 $3/6+2/6=5/6$。',['分数运算'],1),
            ('single','一次函数 $y=2x-1$ 的图像经过点（ ）',['A. (0,1)','B. (1,1)','C. (1,2)','D. (-1,1)'],'B','将 $x=1$ 代入得到 $y=1$。',['一次函数'],2),
            ('solution','已知 $a+b=5$，$ab=6$，求 $a^2+b^2$ 的值。',[],'13','$a^2+b^2=(a+b)^2-2ab=25-12=13$。',['完全平方公式'],2),
            ('solution','将 $y=x^2-6x+5$ 化为顶点式，并写出最小值。',[],'$y=(x-3)^2-4$，最小值为 $-4$。','配方得到 $y=(x-3)^2-4$，平方项非负。',['二次函数'],3),
            ('fill','方程 $3x+5=20$ 的解是 ______。',[],'5','移项并除以3，得到 $x=5$。',['一元一次方程'],1),
            ('solution','已知一次函数经过 $(1,3)$、$(3,7)$ 两点，求函数表达式。',[],'$y=2x+1$。','设 $y=kx+b$，联立方程求得 $k=2$，$b=1$。',['一次函数'],3)]
        questions=[]
        for i,(kind,stem,opts,answer,explanation,tags,difficulty) in enumerate(examples,1):
            q=Question.objects.create(workspace=ws,number=str(i),kind=kind,stem=stem,options=opts,tags=tags,grade='初三',difficulty=difficulty,source='内置演示资料 · 教师编写',suggested_max_score=5)
            a=AnswerRevision.objects.create(workspace=ws,question=q,answer=answer,explanation=explanation,rubric='主要步骤3分，正确结果2分。' if kind=='solution' else '答案正确得5分。',origin='teacher')
            approve_question(q,a.id)
            q.refresh_from_db()
            questions.append(q)
        paper=Paper.objects.create(workspace=ws,title='二次函数与方程 · 阶段诊断')
        for i,q in enumerate(questions[:4],1):
            PaperItem.objects.create(workspace=ws,paper=paper,question=q,position=i,label=str(i),max_score=5)
        publish_paper(paper)
        sub=Submission.objects.create(workspace=ws,paper=paper,student=students[0],test_date=timezone.localdate()-timedelta(days=2))
        for i,item in enumerate(paper.items.all()):
            attempt=Attempt.objects.create(workspace=ws,submission=sub,item=item,student_answer=['B','(3,2)','交点(1,0)、(3,0)，对称轴x=3','5/6'][i],recognition_confirmed=True,confidence=1)
            set_grade(attempt,[5,0,3,5][i],['答案正确。','顶点坐标的横纵顺序需要核对。','交点正确，对称轴应为两根平均值。','通分计算正确。'][i])
        sub2=Submission.objects.create(workspace=ws,paper=paper,student=students[2],test_date=timezone.localdate())
        for item in paper.items.all():
            Attempt.objects.create(workspace=ws,submission=sub2,item=item,student_answer='B' if item.position==1 else '',confidence=.95)
        for offset,(student,title,goal) in enumerate([(students[0],'二次函数 · 错题复测','顶点坐标与对称轴'),(students[1],'准备函数概念专项练习','集合与函数定义'),(students[2],'复核本周数学作业','核对计算过程与解题步骤')]):
            LearningPlan.objects.create(workspace=ws,student=student,title=title,goal=goal,due_date=timezone.localdate()+timedelta(days=offset))
        batch=ImportBatch.objects.create(workspace=ws,title='外部周测卷 · 答案审核示例',route='external',purpose='bank',material='with_answers',test_date=timezone.localdate(),status='review',progress=100,message='此为演示审核记录，题目由演示命令生成，不是AI识别结果。')
        q=Question.objects.create(workspace=ws,batch=batch,number='1',stem='解方程：$x^2-3x+2=0$。',kind='solution',tags=['一元二次方程'],issues=['演示题目，请核对参考答案及分值。'],source='演示外部卷')
        AnswerRevision.objects.create(workspace=ws,question=q,answer='$x=1$ 或 $x=2$。',explanation='因式分解得到 $(x-1)(x-2)=0$。',origin='printed')
        self.stdout.write(self.style.SUCCESS(f'演示空间已建立。登录邮箱：{options["email"]}；密码使用 --password 指定值或 README 中的本地默认值。'))
