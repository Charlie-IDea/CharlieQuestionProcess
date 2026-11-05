from django.contrib import admin
from .models import Workspace, Student, Question, Paper, ImportBatch, Submission, AuditEvent

for model in (Workspace,Student,Question,Paper,ImportBatch,Submission,AuditEvent):
    admin.site.register(model)
