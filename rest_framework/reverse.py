"""
Provide urlresolver functions that return fully qualified URLs or view names
"""
from django.urls import NoReverseMatch
from django.urls import reverse as django_reverse
from django.utils.functional import lazy

from rest_framework.settings import api_settings
from rest_framework.utils.urls import replace_query_param


def preserve_builtin_query_params(url, request=None):
    """
    Given an incoming request, and an outgoing URL representation,
    append the value of any built-in query parameters.
    """
    if request is None:
        return url

    overrides = [
        api_settings.URL_FORMAT_OVERRIDE,
    ]

    for param in overrides:
        if param and (param in request.GET):
            value = request.GET[param]
            url = replace_query_param(url, param, value)

    return url


def reverse(viewname, args=None, kwargs=None, request=None, format=None, **extra):
    """
    根据视图名称生成版本感知的逆向URL
    
    参数说明：
        viewname (str): 视图名称或urls.py中配置的路径名称
        args (list,可选): 传递给URL解析的位置参数列表
        kwargs (dict,可选): 传递给URL解析的关键字参数字典
        request (Request,可选): 用于获取版本方案的请求对象
        format (str,可选): 格式后缀，影响URL生成结果
        **extra: 传递给URL解析器的额外关键字参数
        
    返回值：
        str: 处理后的完整URL字符串，保留内置查询参数
        
    实现逻辑：
        1. 优先使用请求关联的版本控制方案生成URL
        2. 版本方案不可用或反转失败时，回退到默认实现
        3. 最终处理保留内置查询参数
    """
    # 从请求对象获取版本控制方案（如果存在）
    scheme = getattr(request, 'versioning_scheme', None)
    
    # 存在版本控制方案时的处理流程
    if scheme is not None:
        try:
            # 通过版本控制方案生成URL
            url = scheme.reverse(viewname, args, kwargs, request, format, **extra)
        except NoReverseMatch:
            # 版本方案反转失败时，降级到基础实现
            url = _reverse(viewname, args, kwargs, request, format, **extra)
    else:
        # 无版本控制时的标准实现
        url = _reverse(viewname, args, kwargs, request, format, **extra)

    # 保留原始请求的内置查询参数（如format参数）
    return preserve_builtin_query_params(url, request)



def _reverse(viewname, args=None, kwargs=None, request=None, format=None, **extra):
    """
    Same as `django.urls.reverse`, but optionally takes a request
    and returns a fully qualified URL, using the request to get the base URL.
    """
    if format is not None:
        kwargs = kwargs or {}
        kwargs['format'] = format
    url = django_reverse(viewname, args=args, kwargs=kwargs, **extra)
    if request:
        return request.build_absolute_uri(url)
    return url


reverse_lazy = lazy(reverse, str)
