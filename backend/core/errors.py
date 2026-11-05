from rest_framework.views import exception_handler as drf_handler
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError
from django.http import JsonResponse

def csrf_failure(request,reason=''):
    return JsonResponse({'detail':'会话校验失败，请刷新页面后重试。'},status=403)

def exception_handler(exc, context):
    if isinstance(exc,DjangoValidationError):
        exc=ValidationError(exc.messages)
    response = drf_handler(exc, context)
    if response is not None:
        response.data = {'detail': response.data}
    return response
