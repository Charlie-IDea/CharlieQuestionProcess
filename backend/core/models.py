import uuid
from django.conf import settings
from django.db import models
from django.db.models import Q

class Workspace(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='workspace')
    name = models.CharField(max_length=100)
    email_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

class Owned(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        abstract = True
        ordering = ['-created_at']

class Student(Owned):
    name = models.CharField(max_length=80)
    grade = models.CharField(max_length=40, blank=True)
    textbook = models.CharField(max_length=80, blank=True)
    goal = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    archived = models.BooleanField(default=False)

class LearningPlan(Owned):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='plans')
    title = models.CharField(max_length=200)
    goal = models.TextField(blank=True)
    due_date = models.DateField(null=True, blank=True)
    completed = models.BooleanField(default=False)

class Paper(Owned):
    title = models.CharField(max_length=200)
    source = models.CharField(max_length=20, default='generated', choices=[('generated','系统组卷'),('external','外部试卷'),('practice','针对练习')])
    status = models.CharField(max_length=20, default='draft', choices=[('draft','草稿'),('published','已发布')])
    published_at = models.DateTimeField(null=True, blank=True)
    is_fragment = models.BooleanField(default=False)
    instructions = models.TextField(blank=True)

class ImportBatch(Owned):
    title = models.CharField(max_length=200)
    route = models.CharField(max_length=20, choices=[('external','外部试卷'),('card','规范答题卡'),('fragment','零散错题')])
    purpose = models.CharField(max_length=20, choices=[('bank','题库资料'),('assessment','学生作业测试')])
    material = models.CharField(max_length=20, choices=[('blank','空白卷'),('with_answers','附答案'),('answered','学生已作答')])
    student = models.ForeignKey(Student, null=True, blank=True, on_delete=models.PROTECT)
    paper = models.ForeignKey(Paper, null=True, blank=True, on_delete=models.PROTECT)
    test_date = models.DateField()
    status = models.CharField(max_length=30, default='uploaded')
    progress = models.PositiveSmallIntegerField(default=0)
    message = models.TextField(blank=True)
    generation = models.PositiveIntegerField(default=0)
    ai_calls = models.PositiveIntegerField(default=0)
    usage_tokens = models.PositiveIntegerField(default=0)
    task_id = models.CharField(max_length=100, blank=True)

def private_path(instance, name):
    suffix = name.rsplit('.', 1)[-1].lower()
    return f'{instance.workspace_id}/{uuid.uuid4().hex}.{suffix}'

class SourceFile(Owned):
    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name='files')
    file = models.FileField(upload_to=private_path)
    original_name = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64)
    role = models.CharField(max_length=20, choices=[('paper','题目页'),('answer','答案页'),('student','作答页')])
    class Meta(Owned.Meta):
        constraints = [models.UniqueConstraint(fields=['batch','sha256','role'], name='unique_batch_file')]

class SourcePage(Owned):
    source_file = models.ForeignKey(SourceFile, on_delete=models.CASCADE, related_name='pages')
    number = models.PositiveIntegerField()
    image = models.ImageField(upload_to=private_path)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    class Meta(Owned.Meta):
        constraints = [models.UniqueConstraint(fields=['source_file','number'], name='unique_source_page')]

class Question(Owned):
    batch = models.ForeignKey(ImportBatch, null=True, blank=True, on_delete=models.SET_NULL, related_name='questions')
    number = models.CharField(max_length=40, blank=True)
    stem = models.TextField()
    options = models.JSONField(default=list, blank=True)
    kind = models.CharField(max_length=20, default='solution', choices=[('single','单选题'),('multiple','多选题'),('fill','填空题'),('solution','解答题'),('proof','证明题')])
    grade = models.CharField(max_length=40, blank=True)
    chapter = models.CharField(max_length=100, blank=True)
    tags = models.JSONField(default=list, blank=True)
    difficulty = models.PositiveSmallIntegerField(default=3)
    source = models.CharField(max_length=255, blank=True)
    regions = models.JSONField(default=list, blank=True)
    figure_regions = models.JSONField(default=list, blank=True)
    confidence = models.FloatField(default=0)
    issues = models.JSONField(default=list, blank=True)
    extracted_student_answer = models.TextField(blank=True)
    student_answer_present = models.BooleanField(default=False)
    suggested_max_score = models.DecimalField(max_digits=6, decimal_places=2, default=5)
    status = models.CharField(max_length=20, default='draft', choices=[('draft','待审核'),('approved','已入库')])
    revision = models.PositiveIntegerField(default=1)
    class Meta(Owned.Meta):
        constraints = [models.CheckConstraint(condition=Q(difficulty__gte=1, difficulty__lte=5), name='question_difficulty_range')]

class AnswerRevision(Owned):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='answers')
    answer = models.TextField()
    explanation = models.TextField(blank=True)
    rubric = models.TextField(blank=True)
    origin = models.CharField(max_length=20, choices=[('printed','随卷答案'),('ai','AI生成'),('teacher','教师填写'),('bank','题库关联')])
    status = models.CharField(max_length=20, default='pending', choices=[('pending','待审核'),('approved','已确认'),('rejected','已拒绝')])
    model = models.CharField(max_length=100, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)

class PaperItem(Owned):
    paper = models.ForeignKey(Paper, on_delete=models.CASCADE, related_name='items')
    question = models.ForeignKey(Question, on_delete=models.PROTECT)
    position = models.PositiveIntegerField()
    label = models.CharField(max_length=40)
    max_score = models.DecimalField(max_digits=6, decimal_places=2, default=5)
    snapshot = models.JSONField(default=dict)
    origin_response = models.ForeignKey('Attempt', on_delete=models.SET_NULL, null=True, blank=True, related_name='practice_items')
    class Meta(Owned.Meta):
        ordering = ['position']
        constraints = [models.UniqueConstraint(fields=['paper','position'], name='unique_paper_position'),
                       models.CheckConstraint(condition=Q(max_score__gt=0), name='positive_max_score')]

class Submission(Owned):
    paper = models.ForeignKey(Paper, on_delete=models.PROTECT, related_name='submissions')
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name='submissions')
    batch = models.OneToOneField(ImportBatch, null=True, blank=True, on_delete=models.PROTECT)
    test_date = models.DateField()
    notes = models.TextField(blank=True)
    @property
    def is_fragment(self):
        return self.paper.is_fragment or bool(self.batch_id and self.batch.route=='fragment')

class Attempt(Owned):
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name='attempts')
    item = models.ForeignKey(PaperItem, on_delete=models.PROTECT)
    student_answer = models.TextField(blank=True)
    regions = models.JSONField(default=list, blank=True)
    confidence = models.FloatField(default=0)
    recognition_confirmed = models.BooleanField(default=False)
    suggested_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    suggestion = models.TextField(blank=True)
    final_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    feedback = models.TextField(blank=True)
    status = models.CharField(max_length=20, default='pending')
    revision = models.PositiveIntegerField(default=1)
    class Meta(Owned.Meta):
        constraints = [models.UniqueConstraint(fields=['submission','item'], name='unique_submission_item')]

class GradeRevision(Owned):
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name='history')
    score = models.DecimalField(max_digits=6, decimal_places=2)
    feedback = models.TextField(blank=True)
    actor = models.CharField(max_length=20, default='teacher')

class Mistake(Owned):
    attempt = models.OneToOneField(Attempt, on_delete=models.CASCADE, related_name='mistake')
    active = models.BooleanField(default=True)
    mastered = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

class AuditEvent(Owned):
    action = models.CharField(max_length=60)
    object_id = models.CharField(max_length=100)
    details = models.JSONField(default=dict)
