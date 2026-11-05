from rest_framework import serializers
from .models import Student, LearningPlan, Question, AnswerRevision, Paper, PaperItem, ImportBatch, SourceFile, SourcePage, Submission, Attempt, GradeRevision, Mistake, AuditEvent

class OwnedSerializer(serializers.ModelSerializer):
    """Every writable relation is restricted to the authenticated workspace."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        for field in self.fields.values():
            if isinstance(field, serializers.PrimaryKeyRelatedField) and field.queryset is not None:
                field.queryset = field.queryset.filter(workspace=request.user.workspace) if request and request.user.is_authenticated else field.queryset.none()

class StudentSerializer(OwnedSerializer):
    class Meta:
        model = Student
        exclude = ['workspace']
        read_only_fields = ['id','created_at','updated_at']

class PlanSerializer(OwnedSerializer):
    class Meta:
        model = LearningPlan
        exclude = ['workspace']

class AnswerSerializer(OwnedSerializer):
    class Meta:
        model = AnswerRevision
        exclude = ['workspace']
        read_only_fields = ['status','approved_at','model','origin']

def validate_regions(regions, workspace):
    if not isinstance(regions, list) or len(regions) > 20:
        raise serializers.ValidationError('题目区域格式错误或区域过多。')
    for region in regions:
        if not isinstance(region, dict) or not SourcePage.objects.filter(id=region.get('page'), workspace=workspace).exists():
            raise serializers.ValidationError('原始页面不属于当前工作空间。')
        box = region.get('bbox', [])
        if len(box) != 4 or any(not isinstance(v, (int,float)) or not 0 <= v <= 1 for v in box) or box[2] <= box[0] or box[3] <= box[1]:
            raise serializers.ValidationError('区域应为归一化坐标 [左,上,右,下]。')
    return regions

class QuestionSerializer(OwnedSerializer):
    answers = AnswerSerializer(many=True, read_only=True)
    def validate_regions(self, value):
        return validate_regions(value, self.context['request'].user.workspace)
    def validate_figure_regions(self, value):
        return validate_regions(value, self.context['request'].user.workspace)
    def validate_tags(self, value):
        if not isinstance(value, list) or any(not isinstance(v,str) or len(v)>100 for v in value) or len(value)>30:
            raise serializers.ValidationError('知识点需为字符串列表，最多30项。')
        return value
    def validate_options(self, value):
        if not isinstance(value,list) or any(not isinstance(v,str) for v in value) or len(value)>20:
            raise serializers.ValidationError('选项需为字符串列表。')
        return value
    def validate_difficulty(self, value):
        if value not in range(1,6):
            raise serializers.ValidationError('难度范围为1至5。')
        return value
    class Meta:
        model = Question
        exclude = ['workspace']
        read_only_fields = ['batch','status','revision','confidence']

class PaperItemSerializer(OwnedSerializer):
    class Meta:
        model = PaperItem
        exclude = ['workspace']
        read_only_fields = ['snapshot']

class PaperSerializer(OwnedSerializer):
    items = PaperItemSerializer(many=True, read_only=True)
    class Meta:
        model = Paper
        exclude = ['workspace']
        read_only_fields = ['status','published_at']

class PageSerializer(OwnedSerializer):
    image_url = serializers.SerializerMethodField()
    def get_image_url(self, obj):
        return f'/api/pages/{obj.id}/image/'
    class Meta:
        model = SourcePage
        fields = ['id','number','width','height','image_url']

class FileSerializer(OwnedSerializer):
    pages = PageSerializer(many=True, read_only=True)
    download_url = serializers.SerializerMethodField()
    def get_download_url(self, obj):
        return f'/api/files/{obj.id}/download/'
    class Meta:
        model = SourceFile
        fields = ['id','original_name','role','pages','download_url']

class BatchSerializer(OwnedSerializer):
    files = FileSerializer(many=True, read_only=True)
    questions = QuestionSerializer(many=True, read_only=True)
    student_name = serializers.CharField(source='student.name', read_only=True, default='')
    class Meta:
        model = ImportBatch
        exclude = ['workspace']
        read_only_fields = ['status','progress','message','generation','ai_calls','usage_tokens','task_id']
    def validate(self, attrs):
        if attrs.get('purpose') == 'assessment' and not attrs.get('student'):
            raise serializers.ValidationError('学生作业或测试必须指定学生。')
        if attrs.get('route') == 'card' and not attrs.get('paper'):
            raise serializers.ValidationError('规范答题卡必须指定已发布试卷。')
        return attrs

class GradeSerializer(OwnedSerializer):
    class Meta:
        model = GradeRevision
        exclude = ['workspace']

class AttemptSerializer(OwnedSerializer):
    item = PaperItemSerializer(read_only=True)
    history = GradeSerializer(many=True, read_only=True)
    class Meta:
        model = Attempt
        exclude = ['workspace']

class SubmissionSerializer(OwnedSerializer):
    attempts = AttemptSerializer(many=True, read_only=True)
    student_name = serializers.CharField(source='student.name', read_only=True)
    paper_title = serializers.CharField(source='paper.title', read_only=True)
    is_fragment = serializers.BooleanField(read_only=True)
    class Meta:
        model = Submission
        exclude = ['workspace']

class MistakeSerializer(OwnedSerializer):
    attempt = AttemptSerializer(read_only=True)
    student = serializers.UUIDField(source='attempt.submission.student_id', read_only=True)
    student_name = serializers.CharField(source='attempt.submission.student.name', read_only=True)
    test_date = serializers.DateField(source='attempt.submission.test_date', read_only=True)
    followups = serializers.SerializerMethodField()
    def get_followups(self,obj):
        return [{'id':str(a.id),'submission':str(a.submission_id),'date':a.submission.test_date,
            'score':str(a.final_score) if a.final_score is not None else None,'maximum':str(a.item.max_score)}
            for a in Attempt.objects.filter(workspace=obj.workspace,item__origin_response=obj.attempt)
                .select_related('submission','item').order_by('created_at')]
    class Meta:
        model = Mistake
        exclude = ['workspace']
        read_only_fields = ['active']

class AuditSerializer(OwnedSerializer):
    class Meta:
        model = AuditEvent
        exclude = ['workspace']
