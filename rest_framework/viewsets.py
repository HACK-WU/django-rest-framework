"""
ViewSets are essentially just a type of class based view, that doesn't provide
any method handlers, such as `get()`, `post()`, etc... but instead has actions,
such as `list()`, `retrieve()`, `create()`, etc...

Actions are only bound to methods at the point of instantiating the views.

    user_list = UserViewSet.as_view({'get': 'list'})
    user_detail = UserViewSet.as_view({'get': 'retrieve'})

Typically, rather than instantiate views from viewsets directly, you'll
register the viewset with a router and let the URL conf be determined
automatically.

    router = DefaultRouter()
    router.register(r'users', UserViewSet, 'user')
    urlpatterns = router.urls
"""
from functools import update_wrapper
from inspect import getmembers

from django import VERSION as DJANGO_VERSION
from django.urls import NoReverseMatch
from django.utils.decorators import classonlymethod
from django.views.decorators.csrf import csrf_exempt

from rest_framework import generics, mixins, views
from rest_framework.decorators import MethodMapper
from rest_framework.reverse import reverse


def _is_extra_action(attr):
    return hasattr(attr, 'mapping') and isinstance(attr.mapping, MethodMapper)


def _check_attr_name(func, name):
    assert func.__name__ == name, (
        'Expected function (`{func.__name__}`) to match its attribute name '
        '(`{name}`). If using a decorator, ensure the inner function is '
        'decorated with `functools.wraps`, or that `{func.__name__}.__name__` '
        'is otherwise set to `{name}`.').format(func=func, name=name)
    return func


class ViewSetMixin:
    """
    This is the magic.

    Overrides `.as_view()` so that it takes an `actions` keyword that performs
    the binding of HTTP methods to actions on the Resource.

    For example, to create a concrete view binding the 'GET' and 'POST' methods
    to the 'list' and 'create' actions...

    view = MyViewSet.as_view({'get': 'list', 'post': 'create'})
    """

    @classonlymethod
    def as_view(cls, actions=None, **initkwargs):
        """
        重写类视图的as_view方法，支持通过actions参数绑定HTTP方法到资源操作
        
        Args:
            cls: 当前视图类
            actions (dict): HTTP方法到视图方法的映射字典，格式如 {'get': 'list', 'post': 'create'}
            **initkwargs: 传递给视图类的初始化参数
        
        Returns:
            function: 经过CSRF豁免的视图处理函数
        
        Raises:
            TypeError: 当actions为空或存在无效参数时抛出
        
        实现说明:
            1. 重置类属性为None以避免继承值的影响
            2. 对传入参数进行严格校验
            3. 创建闭包视图函数并完成方法绑定
            4. 维护视图函数的元数据信息
        """
        # 初始化视图类元属性（这些属性会被路由配置覆盖）
        cls.name = None
        cls.description = None

        # 后缀参数用于显示视图集类型。
        # 如果提供了name参数，则此参数无效。
        # 例如：'List' 或 'Instance'
        cls.suffix = None

        # detail参数用于检查视图集类型
        cls.detail = None

        # 设置basename允许视图反向解析其操作URL。
        # 此值由路由器通过initkwargs提供
        cls.basename = None

        # actions不能为空
        if not actions:
            raise TypeError("The `actions` argument must be provided when "
                            "calling `.as_view()` on a ViewSet. For example "
                            "`.as_view({'get': 'list'})`")
    
        # 清理无效的初始化参数
        for key in initkwargs:
            # 防止HTTP方法名被用作参数
            if key in cls.http_method_names:
                raise TypeError("You tried to pass in the %s method name as a "
                                "keyword argument to %s(). Don't do that."
                                % (key, cls.__name__))
            # 校验参数是否为类的合法属性
            if not hasattr(cls, key):
                raise TypeError("%s() received an invalid keyword %r" % (
                    cls.__name__, key))
    
        # 处理互斥参数
        if 'name' in initkwargs and 'suffix' in initkwargs:
            raise TypeError("%s() received both `name` and `suffix`, which are "
                            "mutually exclusive arguments." % (cls.__name__))
    
        def view(request, *args, **kwargs):
            """Django视图处理函数闭包
            
            处理HTTP请求并返回响应，实现类视图的请求分发逻辑
            
            Args:
                request: HttpRequest对象，包含请求元数据
                *args: 位置参数，通常来自URL捕获的参数
                **kwargs: 关键字参数，包含URL命名参数和其他初始化参数
            
            Returns:
                HttpResponse: 通过dispatch方法返回的HTTP响应对象
            """
            
            # 实例化视图类，使用传入的初始化参数创建类实例
            self = cls(**initkwargs)
        
            # 自动为HEAD请求添加处理支持（复用GET方法处理逻辑）
            if 'get' in actions and 'head' not in actions:
                actions['head'] = actions['get']
        
            # 建立HTTP方法与视图操作的映射关系字典
            # 用于后续设置self.action属性（如GET请求对应'list'操作）
            self.action_map = actions
        
            # 动态绑定HTTP方法到具体的处理函数
            # 这是类视图与函数视图的核心差异点：通过反射实现方法路由
            for method, action in actions.items():
                handler = getattr(self, action)  # 获取实际的处理方法
                setattr(self, method, handler)   # 将方法绑定到实例
        
            # 保存请求上下文到实例属性
            # 这些属性将在后续处理流程中被视图方法访问
            self.request = request
            self.args = args
            self.kwargs = kwargs
        
            # 执行标准的请求分发流程
            # 最终会调用与请求方法对应的处理函数（如get/post等）
            return self.dispatch(request, *args, **kwargs)
    
        # 维护视图函数的元数据
        update_wrapper(view, cls, updated=())
        update_wrapper(view, cls.dispatch, assigned=())
    
        # 附加视图级属性（用于URL反向解析）
        view.cls = cls
        view.initkwargs = initkwargs
        view.actions = actions
    
        # 处理Django中间件兼容性
        if DJANGO_VERSION >= (5, 1):
            view.login_required = False
    
        return csrf_exempt(view)
        
    def initialize_request(self, request, *args, **kwargs):
        """
        初始化请求对象并设置视图的action属性

        Args:
            request (HttpRequest): 原始的HTTP请求对象
            *args: 传递给父类方法的可变位置参数
            **kwargs: 传递给父类方法的可变关键字参数

        Returns:
            HttpRequest: 经过初始化的请求对象，已添加REST framework的特定属性

        处理逻辑:
        - 继承父类请求初始化逻辑，增强请求对象功能
        - 根据HTTP方法设置对应的action标识，用于后续的权限校验和请求处理
        """
        # 调用父类方法完成基础请求对象初始化
        request = super().initialize_request(request, *args, **kwargs)
        
        # 标准化HTTP方法为小写
        method = request.method.lower()
        
        # 特殊处理OPTIONS方法请求
        if method == 'options':
            # 显式设置元数据标识，该操作由框架基类自动处理
            # 区别于其他需要显式定义action的HTTP方法
            self.action = 'metadata'
        else:
            # 通过预定义的HTTP方法到action的映射表获取操作标识
            # 例如：GET -> 'retrieve'，POST -> 'create' 等
            self.action = self.action_map.get(method)
            
        return request


    def reverse_action(self, url_name, *args, **kwargs):
        """
        Reverse the action for the given `url_name`.
        """
        url_name = '%s-%s' % (self.basename, url_name)
        namespace = None
        if self.request and self.request.resolver_match:
            namespace = self.request.resolver_match.namespace
        if namespace:
            url_name = namespace + ':' + url_name
        kwargs.setdefault('request', self.request)

        return reverse(url_name, *args, **kwargs)

    @classmethod
    def get_extra_actions(cls):
        """
        Get the methods that are marked as an extra ViewSet `@action`.
        """
        return [_check_attr_name(method, name)
                for name, method
                in getmembers(cls, _is_extra_action)]

    def get_extra_action_url_map(self):
        """
        Build a map of {names: urls} for the extra actions.

        This method will noop if `detail` was not provided as a view initkwarg.
        """
        action_urls = {}

        # exit early if `detail` has not been provided
        if self.detail is None:
            return action_urls

        # filter for the relevant extra actions
        actions = [
            action for action in self.get_extra_actions()
            if action.detail == self.detail
        ]

        for action in actions:
            try:
                url_name = '%s-%s' % (self.basename, action.url_name)
                namespace = self.request.resolver_match.namespace
                if namespace:
                    url_name = '%s:%s' % (namespace, url_name)

                url = reverse(url_name, self.args, self.kwargs, request=self.request)
                view = self.__class__(**action.kwargs)
                action_urls[view.get_view_name()] = url
            except NoReverseMatch:
                pass  # URL requires additional arguments, ignore

        return action_urls


class ViewSet(ViewSetMixin, views.APIView):
    """
    The base ViewSet class does not provide any actions by default.
    """
    pass


class GenericViewSet(ViewSetMixin, generics.GenericAPIView):
    """
    The GenericViewSet class does not provide any actions by default,
    but does include the base set of generic view behavior, such as
    the `get_object` and `get_queryset` methods.
    """
    pass


class ReadOnlyModelViewSet(mixins.RetrieveModelMixin,
                           mixins.ListModelMixin,
                           GenericViewSet):
    """
    A viewset that provides default `list()` and `retrieve()` actions.
    """
    pass


class ModelViewSet(mixins.CreateModelMixin,
                   mixins.RetrieveModelMixin,
                   mixins.UpdateModelMixin,
                   mixins.DestroyModelMixin,
                   mixins.ListModelMixin,
                   GenericViewSet):
    """
    A viewset that provides default `create()`, `retrieve()`, `update()`,
    `partial_update()`, `destroy()` and `list()` actions.
    """
    pass
