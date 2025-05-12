"""
Routers provide a convenient and consistent way of automatically
determining the URL conf for your API.

They are used by simply instantiating a Router class, and then registering
all the required ViewSets with that router.

For example, you might have a `urls.py` that looks something like this:

    router = routers.DefaultRouter()
    router.register('users', UserViewSet, 'user')
    router.register('accounts', AccountViewSet, 'account')

    urlpatterns = router.urls
"""
import itertools
from collections import namedtuple

from django.core.exceptions import ImproperlyConfigured
from django.urls import NoReverseMatch, path, re_path

from rest_framework import views
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.schemas import SchemaGenerator
from rest_framework.schemas.views import SchemaView
from rest_framework.settings import api_settings
from rest_framework.urlpatterns import format_suffix_patterns

Route = namedtuple('Route', ['url', 'mapping', 'name', 'detail', 'initkwargs'])
DynamicRoute = namedtuple('DynamicRoute', ['url', 'name', 'detail', 'initkwargs'])


def escape_curly_brackets(url_path):
    """
    Double brackets in regex of url_path for escape string formatting
    """
    return url_path.replace('{', '{{').replace('}', '}}')


def flatten(list_of_lists):
    """
    Takes an iterable of iterables, returns a single iterable containing all items
    """
    return itertools.chain(*list_of_lists)


class BaseRouter:
    def __init__(self):
        """初始化路由注册表。

        初始化一个空列表用于存储路由注册信息，该列表将保存
        (prefix, viewset, basename)元组。
        """
        self.registry = []

    def register(self, prefix, viewset, basename=None):
        if basename is None:
            basename = self.get_default_basename(viewset)

        # 检查basename唯一性，避免重复注册
        if self.is_already_registered(basename):
            msg = (f'Router with basename "{basename}" is already registered. '
                   f'Please provide a unique basename for viewset "{viewset}"')
            raise ImproperlyConfigured(msg)

        # 将路由信息添加到注册表
        self.registry.append((prefix, viewset, basename))

        # 清除URL缓存以确保下次生成最新URL配置
        if hasattr(self, '_urls'):
            del self._urls

    def is_already_registered(self, new_basename):
        """
        Check if `basename` is already registered
        """
        return any(basename == new_basename for _prefix, _viewset, basename in self.registry)

    def get_default_basename(self, viewset):
        """
        If `basename` is not specified, attempt to automatically determine
        it from the viewset.
        """
        raise NotImplementedError('get_default_basename must be overridden')

    def get_urls(self):
        """
        Return a list of URL patterns, given the registered viewsets.
        """
        raise NotImplementedError('get_urls must be overridden')

    @property
    def urls(self):
        if not hasattr(self, '_urls'):
            self._urls = self.get_urls()
        return self._urls


class SimpleRouter(BaseRouter):

    # 定义ViewSet的默认路由配置列表
    # 包含基础CRUD路由和动态扩展路由两种类型，用于自动生成URL模式
    # 每个路由项定义了URL路径模板、HTTP方法映射、路由名称模板及附加参数
    routes = [
        # 基础列表路由配置
        # 处理集合资源的基础操作：
        # - GET: 获取资源列表（映射到list方法）
        # - POST: 创建新资源（映射到create方法）
        # URL模板：前缀+可选斜杠（如 /api/resource/）
        # 路由名称格式：{basename}-list（如 user-list）
        Route(
            url=r'^{prefix}{trailing_slash}$',
            mapping={
                'get': 'list',
                'post': 'create'
            },
            name='{basename}-list',
            detail=False,
            initkwargs={'suffix': 'List'}
        ),
        # 动态列表路由配置
        # 处理使用@action(detail=False)装饰器声明的扩展操作
        # URL模板：前缀/扩展路径/（如 /api/resource/custom_action/）
        # 路由名称格式：{basename}-{url_name}（如 user-custom_action）
        DynamicRoute(
            url=r'^{prefix}/{url_path}{trailing_slash}$',
            name='{basename}-{url_name}',
            detail=False,
            initkwargs={}
        ),
        # 基础详情路由配置
        # 处理单个资源的基础操作：
        # - GET: 获取单个资源（retrieve）
        # - PUT: 全量更新（update）
        # - PATCH: 部分更新（partial_update）
        # - DELETE: 删除资源（destroy）
        # URL模板：前缀/主键/（如 /api/resource/123/）
        # 路由名称格式：{basename}-detail（如 user-detail）
        Route(
            url=r'^{prefix}/{lookup}{trailing_slash}$',
            mapping={
                'get': 'retrieve',
                'put': 'update',
                'patch': 'partial_update',
                'delete': 'destroy'
            },
            name='{basename}-detail',
            detail=True,
            initkwargs={'suffix': 'Instance'}
        ),
        # 动态详情路由配置
        # 处理使用@action(detail=True)装饰器声明的扩展操作
        # URL模板：前缀/主键/扩展路径/（如 /api/resource/123/custom_action/）
        # 路由名称格式：{basename}-{url_name}（如 user-custom_action）
        DynamicRoute(
            url=r'^{prefix}/{lookup}/{url_path}{trailing_slash}$',
            name='{basename}-{url_name}',
            detail=True,
            initkwargs={}
        ),
    ]

    def __init__(self, trailing_slash=True, use_regex_path=True):
        """
        初始化路由配置实例
        
        参数:
            trailing_slash (bool): 是否在路径末尾添加斜杠。若为True，则路径末尾会自动添加'/'。
            use_regex_path (bool): 是否使用正则表达式路径匹配。若为True，则使用re_path进行路径匹配；
                                   否则使用普通路径匹配。
        
        返回值:
            None: 构造函数无返回值
        """
        # 配置路径斜杠后缀和路径匹配模式
        self.trailing_slash = '/' if trailing_slash else ''
        self._use_regex = use_regex_path
        
        # 根据路径匹配模式选择不同的配置
        if use_regex_path:
            """
            正则表达式路径模式配置：
            - _base_pattern: 正则分组命名模式
            - _default_value_pattern: 默认正则匹配规则（非斜杠和点的字符）
            - _url_conf: 使用re_path进行路径匹配
            """
            # url = r'^users/(?P<user_id>\d+)$'
            # 匹配 "/users/123" → user_id="123"
            # {lookup_prefix}{lookup_url_kwarg} 是查找的键
            # lookup_value 是查找的值，在这里就是正则表达式
            self._base_pattern = '(?P<{lookup_prefix}{lookup_url_kwarg}>{lookup_value})'
            self._default_value_pattern = '[^/.]+'
            self._url_conf = re_path
        else:
            """
            普通路径模式配置：
            - _base_pattern: 普通路径参数占位符格式
            - _default_value_pattern: 默认参数类型转换器
            - _url_conf: 使用path进行路径匹配
            
            后续处理：移除路由中的正则表达式锚点符号
            """
            # url = 'users/<int:user_id>'
            # 匹配 "/users/123" → user_id=123（整数类型）
            self._base_pattern = '<{lookup_value}:{lookup_prefix}{lookup_url_kwarg}>'
            self._default_value_pattern = 'str'
            self._url_conf = path
            
            # 清理路由中的正则表达式锚点符号
            _routes = []
            for route in self.routes:
                url_param = route.url
                # 移除正则表达式的起始和结束锚点
                if url_param[0] == '^':
                    url_param = url_param[1:]
                if url_param[-1] == '$':
                    url_param = url_param[:-1]

                _routes.append(route._replace(url=url_param))
            self.routes = _routes

        super().__init__()

    def get_default_basename(self, viewset):
        """
        If `basename` is not specified, attempt to automatically determine
        it from the viewset.
        """
        queryset = getattr(viewset, 'queryset', None)

        assert queryset is not None, '`basename` argument not specified, and could ' \
            'not automatically determine the name from the viewset, as ' \
            'it does not have a `.queryset` attribute.'

        return queryset.model._meta.object_name.lower()

    def get_routes(self, viewset):
        """
        增强 self.routes 列表，添加动态生成的路由条目。

        参数:
            viewset: 视图集实例，用于获取额外的自定义动作

        返回值:
            Route命名元组列表，包含原始路由和新生成的动态路由
        """
        # 将已知路由的动作映射展平为列表形式
        # 用于后续检查自定义动作是否存在命名冲突
        known_actions = list(flatten([route.mapping.values() for route in self.routes if isinstance(route, Route)]))
        extra_actions = viewset.get_extra_actions()

        # 检查自定义动作是否与现有路由冲突
        # 若存在重复命名则抛出配置异常
        not_allowed = [
            action.__name__ for action in extra_actions
            if action.__name__ in known_actions
        ]
        if not_allowed:
            msg = ('Cannot use the @action decorator on the following '
                   'methods, as they are existing routes: %s')
            raise ImproperlyConfigured(msg % ', '.join(not_allowed))

        # 将额外动作分为详情视图和列表视图两类
        detail_actions = [action for action in extra_actions if action.detail]
        list_actions = [action for action in extra_actions if not action.detail]

        # 根据路由类型生成动态路由
        # DynamicRoute条目会根据动作类型生成具体路径
        routes = []
        for route in self.routes:
            if isinstance(route, DynamicRoute) and route.detail:
                routes += [self._get_dynamic_route(route, action) for action in detail_actions]
            elif isinstance(route, DynamicRoute) and not route.detail:
                routes += [self._get_dynamic_route(route, action) for action in list_actions]
            else:
                routes.append(route)

        return routes

    def _get_dynamic_route(self, route, action):
        """
        生成动态路由配置，合并初始化参数并替换URL模板中的占位符

        @action(detail=True, url_path='activate', methods=['post'])
        def activate_user(self, request, *args, **kwargs):
            pass
        会生成类似 /users/123/activate/ 的 URL。

        参数:
            route: 原始路由对象，包含基础URL模板、名称模板和初始化参数
            action: 动作对象，包含动态URL路径、HTTP方法映射和动态参数
            
        返回值:
            Route: 新生成的路由实例，包含动态替换后的URL、名称和合并参数
        """
        # 合并基础参数与动作参数（优先级：action.kwargs > route.initkwargs）
        initkwargs = route.initkwargs.copy()
        initkwargs.update(action.kwargs)

        # 转义动态URL路径中的大括号，防止与格式化占位符冲突
        url_path = escape_curly_brackets(action.url_path)

        # 创建新路由实例，替换URL和名称模板中的动态部分
        return Route(
            url=route.url.replace('{url_path}', url_path),
            mapping=action.mapping,
            name=route.name.replace('{url_name}', action.url_name),
            detail=route.detail,
            initkwargs=initkwargs,
        )

    def get_method_map(self, viewset, method_map):
        """
        Given a viewset, and a mapping of http methods to actions,
        return a new mapping which only includes any mappings that
        are actually implemented by the viewset.
        """
        bound_methods = {}
        for method, action in method_map.items():
            if hasattr(viewset, action):
                bound_methods[method] = action
        return bound_methods

    def get_lookup_regex(self, viewset, lookup_prefix=''):
        """
        生成用于匹配单个实例的URL正则表达式片段
        
        参数:
            viewset: 视图集实例，需包含lookup_field、lookup_url_kwarg等属性
            lookup_prefix: 查找前缀字符串，用于支持嵌套路由器的路径拼接
            
        返回值:
            str: 格式化的URL正则表达式字符串，包含以下替换参数：
                {lookup_prefix}: 嵌套路由前缀
                {lookup_url_kwarg}: URL关键字参数名称
                {lookup_value}: 主键值匹配正则表达式
                
        功能说明:
            1. 优先使用视图集定义的lookup_field（默认'pk'）作为查找字段
            2. 支持通过lookup_url_kwarg自定义URL参数名称
            3. 提供两种值匹配模式：
               - 非正则模式：使用lookup_value_converter进行类型转换
               - 正则模式：通过lookup_value_regex定义匹配规则（默认'[0-9]+'）
            4. 返回的正则片段遵循以下格式：
               r'{lookup_prefix}(?P<{lookup_url_kwarg}>{lookup_value})'
        """
        # Use `pk` as default field, unset set.  Default regex should not
        # consume `.json` style suffixes and should break at '/' boundaries.
        lookup_field = getattr(viewset, 'lookup_field', 'pk')
        lookup_url_kwarg = getattr(viewset, 'lookup_url_kwarg', None) or lookup_field
        lookup_value = None
        
        # 处理非正则模式下的值转换器获取逻辑
        if not self._use_regex:
            # try to get a more appropriate attribute when not using regex
            lookup_value = getattr(viewset, 'lookup_value_converter', None)
        
        # 回退到正则模式处理（兼容旧版实现）
        if lookup_value is None:
            # fallback to legacy
            lookup_value = getattr(viewset, 'lookup_value_regex', self._default_value_pattern)
        
        # 使用基础模板生成最终正则表达式
        return self._base_pattern.format(
            lookup_prefix=lookup_prefix,
            lookup_url_kwarg=lookup_url_kwarg,
            lookup_value=lookup_value
        )

    def get_urls(self):
        """
        根据注册的ViewSet生成URL模式列表。

        参数:
            self: 当前对象实例，需包含以下属性:
                - registry: 注册的ViewSet列表，每个元素为(prefix, viewset, basename)
                - trailing_slash: 是否在URL末尾添加斜杠的布尔值
                - _url_conf: 用于生成URL配置的函数（如path或re_path）
        
        返回:
            list: 包含生成的URL模式的列表，每个元素为_url_conf生成的URL配置对象
        """
        ret = []

        # 遍历所有注册的ViewSet进行URL模式生成
        for prefix, viewset, basename in self.registry:
            lookup = self.get_lookup_regex(viewset)
            routes = self.get_routes(viewset)

            # 处理当前ViewSet的所有路由规则
            for route in routes:

                # 获取实际存在的视图动作映射关系
                mapping = self.get_method_map(viewset, route.mapping)
                if not mapping:
                    continue

                # 构建带格式替换的URL正则表达式
                regex = route.url.format(
                    prefix=prefix,
                    lookup=lookup,
                    trailing_slash=self.trailing_slash
                )

                # 特殊处理无前缀情况下的URL路径规范性问题
                if not prefix:
                    if self._url_conf is path:
                        if regex[0] == '/':
                            regex = regex[1:]
                    elif regex[:2] == '^/':
                        regex = '^' + regex[2:]

                # 合并路由初始化参数与基础参数
                initkwargs = route.initkwargs.copy()
                initkwargs.update({
                    'basename': basename,
                    'detail': route.detail,
                })

                # 创建视图实例并生成最终URL配置
                view = viewset.as_view(mapping, **initkwargs)
                name = route.name.format(basename=basename)
                ret.append(self._url_conf(regex, view, name=name))

        return ret


class APIRootView(views.APIView):
    """
    The default basic root view for DefaultRouter
    """
    _ignore_model_permissions = True
    schema = None  # exclude from schema
    api_root_dict = None

    def get(self, request, *args, **kwargs):
        # Return a plain {"name": "hyperlink"} response.
        ret = {}
        namespace = request.resolver_match.namespace
        for key, url_name in self.api_root_dict.items():
            if namespace:
                url_name = namespace + ':' + url_name
            try:
                ret[key] = reverse(
                    url_name,
                    args=args,
                    kwargs=kwargs,
                    request=request,
                    format=kwargs.get('format')
                )
            except NoReverseMatch:
                # Don't bail out if eg. no list routes exist, only detail routes.
                continue

        return Response(ret)


class DefaultRouter(SimpleRouter):
    """
    The default router extends the SimpleRouter, but also adds in a default
    API root view, and adds format suffix patterns to the URLs.
    """
    include_root_view = True
    include_format_suffixes = True
    root_view_name = 'api-root'
    default_schema_renderers = None
    APIRootView = APIRootView
    APISchemaView = SchemaView
    SchemaGenerator = SchemaGenerator

    def __init__(self, *args, **kwargs):
        if 'root_renderers' in kwargs:
            self.root_renderers = kwargs.pop('root_renderers')
        else:
            self.root_renderers = list(api_settings.DEFAULT_RENDERER_CLASSES)
        super().__init__(*args, **kwargs)

    def get_api_root_view(self, api_urls=None):
        """
        Return a basic root view.
        """
        api_root_dict = {}
        list_name = self.routes[0].name
        for prefix, viewset, basename in self.registry:
            api_root_dict[prefix] = list_name.format(basename=basename)

        return self.APIRootView.as_view(api_root_dict=api_root_dict)

    def get_urls(self):
        """
        Generate the list of URL patterns, including a default root view
        for the API, and appending `.json` style format suffixes.
        """
        urls = super().get_urls()

        if self.include_root_view:
            view = self.get_api_root_view(api_urls=urls)
            root_url = path('', view, name=self.root_view_name)
            urls.append(root_url)

        if self.include_format_suffixes:
            urls = format_suffix_patterns(urls)

        return urls
