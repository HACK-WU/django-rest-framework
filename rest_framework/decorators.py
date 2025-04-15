"""
The most important decorator in this module is `@api_view`, which is used
for writing function-based views with REST framework.

There are also various decorators for setting the API policies on function
based views, as well as the `@action` decorator, which is used to annotate
methods on viewsets that should be included by routers.
"""
import types

from django.forms.utils import pretty_name

from rest_framework.views import APIView


def api_view(http_method_names=None):
    """
    API视图装饰器工厂函数，用于将函数式视图转换为DRF的APIView子类

    Args:
        http_method_names: (list/tuple, optional) 允许的HTTP方法列表，默认为['GET']

    Returns:
        decorator: 实际执行装饰逻辑的函数装饰器

    功能说明：
    1. 自动创建继承自APIView的WrappedAPIView类
    2. 设置允许的HTTP方法（自动包含OPTIONS方法）
    3. 保持原函数的文档字符串和属性
    4. 支持从被装饰函数继承视图类属性（renderer_classes等）
    """
    # 处理默认HTTP方法，确保http_method_names是列表类型
    http_method_names = ['GET'] if (http_method_names is None) else http_method_names

    def decorator(func):
        # 动态创建APIView子类，保留原函数文档字符串
        WrappedAPIView = type(
            'WrappedAPIView',
            (APIView,),
            {'__doc__': func.__doc__}
        )

        # Note, the above allows us to set the docstring.
        # It is the equivalent of:
        #
        #     class WrappedAPIView(APIView):
        #         pass
        #     WrappedAPIView.__doc__ = func.doc    <--- Not possible to do this

        # api_view applied without (method_names)
        assert not isinstance(http_method_names, types.FunctionType), \
            '@api_view missing list of allowed HTTP methods'
        assert isinstance(http_method_names, (list, tuple)), \
            '@api_view expected a list of strings, received %s' % type(http_method_names).__name__

        # 配置允许的HTTP方法（自动添加OPTIONS方法）
        allowed_methods = set(http_method_names) | {'options'}
        WrappedAPIView.http_method_names = [method.lower() for method in allowed_methods]

        # 定义请求处理方法，将函数调用转发给被装饰函数
        def handler(self, *args, **kwargs):
            return func(*args, **kwargs)

        # 为每个HTTP方法注册处理函数
        for method in http_method_names:
            setattr(WrappedAPIView, method.lower(), handler)

        # 保留原函数的元信息
        WrappedAPIView.__name__ = func.__name__
        WrappedAPIView.__module__ = func.__module__

        # 继承视图类属性（优先使用被装饰函数的属性，否则使用APIView默认值）
        WrappedAPIView.renderer_classes = getattr(func, 'renderer_classes',
                                                  APIView.renderer_classes)
        WrappedAPIView.parser_classes = getattr(func, 'parser_classes',
                                                APIView.parser_classes)
        WrappedAPIView.authentication_classes = getattr(func, 'authentication_classes',
                                                        APIView.authentication_classes)
        WrappedAPIView.throttle_classes = getattr(func, 'throttle_classes',
                                                  APIView.throttle_classes)
        WrappedAPIView.permission_classes = getattr(func, 'permission_classes',
                                                    APIView.permission_classes)
        WrappedAPIView.schema = getattr(func, 'schema',
                                        APIView.schema)

        # 返回类视图的as_view()方法，使其兼容Django的URL配置
        return WrappedAPIView.as_view()

    return decorator



def renderer_classes(renderer_classes):
    def decorator(func):
        func.renderer_classes = renderer_classes
        return func
    return decorator


def parser_classes(parser_classes):
    def decorator(func):
        func.parser_classes = parser_classes
        return func
    return decorator


def authentication_classes(authentication_classes):
    def decorator(func):
        func.authentication_classes = authentication_classes
        return func
    return decorator


def throttle_classes(throttle_classes):
    def decorator(func):
        func.throttle_classes = throttle_classes
        return func
    return decorator


def permission_classes(permission_classes):
    def decorator(func):
        func.permission_classes = permission_classes
        return func
    return decorator


def schema(view_inspector):
    def decorator(func):
        func.schema = view_inspector
        return func
    return decorator


def action(methods=None, detail=None, url_path=None, url_name=None, **kwargs):
    """
    将ViewSet方法标记为可路由操作的装饰器

    Args:
        methods (list[str], optional): 该操作响应的HTTP方法列表，默认为['GET']
        detail (bool): 必需参数。决定该操作适用于实例详情请求(detail=True)
            还是集合列表请求(detail=False)
        url_path (str, optional): 自定义操作的URL路径段，默认使用被装饰方法的名称
        url_name (str, optional): 内部(reverse)URL名称，默认将方法名中的下划线替换为短横线
        **kwargs: 其他视图属性设置，可用于覆盖视图集级别的*_classes配置，
            类似于@renderer_classes等装饰器在函数式API视图中的作用

    Returns:
        function: 装饰器函数，用于包装视图方法并添加路由配置

    功能说明:
        - 被装饰的方法会获得mapping属性( MethodMapper 实例)
        - 自动处理HTTP方法映射和路由配置
    """
    methods = ['get'] if methods is None else methods
    methods = [method.lower() for method in methods]

    # 必需参数校验
    assert detail is not None, (
        "@action() missing required argument: 'detail'"
    )

    # 互斥参数检查
    if 'name' in kwargs and 'suffix' in kwargs:
        raise TypeError("`name` and `suffix` are mutually exclusive arguments.")

    def decorator(func):
        # 创建HTTP方法映射器并附加到目标函数
        func.mapping = MethodMapper(func, methods)

        # 设置路由元数据
        func.detail = detail
        func.url_path = url_path if url_path else func.__name__
        func.url_name = url_name if url_name else func.__name__.replace('_', '-')

        # 处理视图类配置参数
        func.kwargs = kwargs

        # 自动生成描述性元数据
        if 'name' not in kwargs and 'suffix' not in kwargs:
            func.kwargs['name'] = pretty_name(func.__name__)
        func.kwargs['description'] = func.__doc__ or None

        return func
    return decorator


class MethodMapper(dict):
    """
    Enables mapping HTTP methods to different ViewSet methods for a single,
    logical action.

    Example usage:

        class MyViewSet(ViewSet):

            @action(detail=False)
            def example(self, request, **kwargs):
                ...

            @example.mapping.post
            def create_example(self, request, **kwargs):
                ...
    """

    def __init__(self, action, methods):
        self.action = action
        for method in methods:
            self[method] = self.action.__name__

    def _map(self, method, func):
        assert method not in self, (
            "Method '%s' has already been mapped to '.%s'." % (method, self[method]))
        assert func.__name__ != self.action.__name__, (
            "Method mapping does not behave like the property decorator. You "
            "cannot use the same method name for each mapping declaration.")

        self[method] = func.__name__

        return func

    def get(self, func):
        return self._map('get', func)

    def post(self, func):
        return self._map('post', func)

    def put(self, func):
        return self._map('put', func)

    def patch(self, func):
        return self._map('patch', func)

    def delete(self, func):
        return self._map('delete', func)

    def head(self, func):
        return self._map('head', func)

    def options(self, func):
        return self._map('options', func)

    def trace(self, func):
        return self._map('trace', func)
