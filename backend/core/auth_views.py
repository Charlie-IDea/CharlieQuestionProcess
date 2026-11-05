from django.conf import settings
from django.contrib.auth import authenticate, login, logout, get_user_model, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.core.mail import send_mail
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.exceptions import ValidationError
from .models import Workspace
import smtplib

User = get_user_model()

def user_info(user):
    workspace = user.workspace
    return {'id':user.id,'name':user.first_name or user.username,'email':user.email,
            'workspace':{'id':str(workspace.id),'name':workspace.name,'email_verified':workspace.email_verified}}

def check_password(password, user=None):
    try:
        validate_password(password,user)
    except DjangoValidationError as exc:
        raise ValidationError(list(exc.messages))

def verification_mail(user):
    token=signing.dumps({'user':user.pk,'email':user.email},salt='verify-email')
    try:
        send_mail('知序 · 验证邮箱','请打开链接完成验证：\n'+settings.APP_URL+'/?verify='+token,settings.DEFAULT_FROM_EMAIL,[user.email])
    except (smtplib.SMTPException,OSError):
        raise ValidationError('账户已保存，但验证邮件未能发送。请稍后重发，或联系管理员检查邮件服务。') from None

@method_decorator(ensure_csrf_cookie,name='dispatch')
class SessionView(APIView):
    permission_classes=[AllowAny]
    def get(self,request):
        return Response({'user':user_info(request.user) if request.user.is_authenticated else None,'csrf':get_token(request)})

@method_decorator(csrf_protect,name='dispatch')
class AuthView(APIView):
    permission_classes=[AllowAny]
    throttle_classes=[ScopedRateThrottle]
    throttle_scope='auth'
    def post(self,request,action):
        data=request.data
        if action=='register':
            email=str(data.get('email','')).strip().lower()
            name=str(data.get('name','')).strip()[:80]
            try:
                validate_email(email)
            except DjangoValidationError:
                raise ValidationError('请输入有效邮箱。')
            if len(email)>150:
                raise ValidationError('邮箱地址过长。')
            password=data.get('password','')
            check_password(password)
            if not name or User.objects.filter(username=email).exists():
                raise ValidationError('请填写姓名，并使用尚未注册的邮箱。')
            with transaction.atomic():
                user=User.objects.create_user(username=email,email=email,password=password,first_name=name,is_active=False)
                Workspace.objects.create(owner=user,name=name+'的教学空间')
            verification_mail(user)
            return Response({'message':'验证邮件已发送，请验证邮箱后登录。'},status=201)
        if action=='resend':
            user=User.objects.filter(username=str(data.get('email','')).strip().lower(),is_active=False).first()
            if user:
                verification_mail(user)
            return Response({'message':'若账户尚未验证，将重新发送验证邮件。'})
        if action=='verify':
            try:
                payload=signing.loads(data.get('token',''),salt='verify-email',max_age=86400)
                user=User.objects.get(pk=payload['user'],email=payload['email'])
            except (signing.BadSignature,User.DoesNotExist,KeyError,TypeError):
                raise ValidationError('验证链接无效或已过期。')
            if user.workspace.email_verified:
                return Response({'message':'该邮箱已验证，请直接登录。'})
            user.is_active=True
            user.save(update_fields=['is_active'])
            Workspace.objects.filter(owner=user).update(email_verified=True)
            return Response({'message':'邮箱已验证，请登录。'})
        if action=='login':
            user=authenticate(request,username=str(data.get('email','')).strip().lower(),password=data.get('password',''))
            if not user:
                raise ValidationError('邮箱或密码错误，或邮箱尚未验证。')
            login(request,user)
            return Response({'user':user_info(user),'csrf':get_token(request)})
        if action=='logout':
            logout(request)
            return Response({'message':'已退出登录。'})
        if action=='forgot':
            email=str(data.get('email','')).strip().lower()
            user=User.objects.filter(email=email,is_active=True).first()
            if user:
                token=default_token_generator.make_token(user)
                send_mail('知序 · 重置密码','请打开链接重置密码：\n'+settings.APP_URL+f'/?reset={user.pk}:{token}',settings.DEFAULT_FROM_EMAIL,[email])
            return Response({'message':'若邮箱已注册且激活，将收到重置邮件。'})
        if action=='reset':
            try:
                uid,token=str(data.get('token','')).split(':',1)
                user=User.objects.get(pk=uid)
            except (ValueError,User.DoesNotExist):
                raise ValidationError('重置链接无效。')
            if not default_token_generator.check_token(user,token):
                raise ValidationError('重置链接无效或已使用。')
            check_password(data.get('password',''),user)
            user.set_password(data['password'])
            user.save()
            return Response({'message':'密码已重置，请重新登录。'})
        if action=='password':
            if not request.user.is_authenticated or not request.user.check_password(data.get('old_password','')):
                raise ValidationError('当前密码错误。')
            check_password(data.get('password',''),request.user)
            request.user.set_password(data['password'])
            request.user.save()
            update_session_auth_hash(request,request.user)
            return Response({'message':'密码已修改，其他设备会话已失效。'})
        raise ValidationError('不支持的账户操作。')
