"""
Generic views that provide commonly needed behaviour.
"""
from django.core.exceptions import ValidationError
from django.db.models.query import QuerySet
from django.http import Http404
from django.shortcuts import get_object_or_404 as _get_object_or_404

from rest_framework import mixins, views
from rest_framework.settings import api_settings


def get_object_or_404(queryset, *filter_args, **filter_kwargs):
    """
    Same as Django's standard shortcut, but make sure to also raise 404
    if the filter_kwargs don't match the required types.
    """
    try:
        return _get_object_or_404(queryset, *filter_args, **filter_kwargs)
    except (TypeError, ValueError, ValidationError):
        raise Http404


class GenericAPIView(views.APIView):
    """
    DRF通用API视图基类，提供RESTful接口的通用处理逻辑。

    特性：
    - 支持动态获取查询集和序列化类
    - 提供对象查询字段配置
    - 集成过滤后端支持
    - 支持分页处理

    继承自APIView，通过类属性配置核心组件，需至少设置queryset或serializer_class，
    或通过重写get_queryset()/get_serializer_class()方法实现。
    """
    # 核心配置属性（必须设置其一或通过方法覆盖）
    queryset = None
    """
    模型查询集，需为QuerySet实例。
    注意：直接访问该属性会触发缓存，应通过get_queryset()方法获取最新结果
    """

    # 默认序列化器类，用于请求/响应数据的序列化和反序列化
    serializer_class = None
    
    # 对象查询配置,模型对象查找字段，默认使用主键pk进行单对象查询
    lookup_field = 'pk'
    
    # 用于指定从 URL 中提取对象唯一标识符的关键字参数名称。
    # 默认情况下，DRF 使用 pk 作为参数名（如 /users/<pk>/）
    # 若 URL 中使用其他参数名（如 user_id），需通过 lookup_url_kwarg 显式指定。
    # 例如，URL 路径为 /users/<user_id>/，但模型的主键字段是 id。此时需设置：
    # lookup_field = 'id'
    # lookup_url_kwarg = 'user_id'
    lookup_url_kwarg = None

    # 过滤与分页配置
    filter_backends = api_settings.DEFAULT_FILTER_BACKENDS
    
    # 分页处理类，控制列表接口的分页行为
    pagination_class = api_settings.DEFAULT_PAGINATION_CLASS

    def __class_getitem__(cls, *args, **kwargs):
        """
        支持泛型类型检查的魔术方法
        
        返回：
            cls: 返回类自身实例，用于类型提示兼容
        """
        return cls

    def get_queryset(self):
        """
        获取视图使用的查询集（核心方法）

        实现要点：
        1. 强制子类必须设置queryset属性或重写本方法
        2. 确保每次请求都返回新的查询集实例
        3. 支持根据请求上下文动态调整查询集

        返回：
            QuerySet: 处理后的模型查询集对象

        异常：
            AssertionError: 当未设置queryset且未重写方法时抛出
        """
        # 验证类配置完整性
        assert self.queryset is not None, (
            "'%s' should either include a `queryset` attribute, "
            "or override the `get_queryset()` method."
            % self.__class__.__name__
        )

        queryset = self.queryset
        # 确保查询集重新实例化（避免缓存影响）
        if isinstance(queryset, QuerySet):
            queryset = queryset.all()
        return queryset

    def get_object(self):
        """
        Returns the object the view is displaying.

        You may want to override this if you need to provide non-standard
        queryset lookups.  Eg if objects are referenced using multiple
        keyword arguments in the url conf.

        Args:
            self: 视图类实例，包含请求上下文、URL参数等视图属性

        Returns:
            Model: 从数据库查询获得的模型对象实例，经过404检查和权限验证

        Raises:
            Http404: 当根据URL参数无法找到对应对象时抛出
            PermissionDenied: 当对象权限检查不通过时抛出
        """
        # 获取基础查询集并应用视图定义的过滤条件（如权限过滤、自定义过滤等）
        queryset = self.filter_queryset(self.get_queryset())

        # 处理URL查找标识符：确定用于模型查询的URL参数名称
        # 优先使用自定义lookup_url_kwarg，默认回退到lookup_field字段
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field

        # 验证URL配置是否包含必需的查询参数
        assert lookup_url_kwarg in self.kwargs, (
            'Expected view %s to be called with a URL keyword argument '
            'named "%s". Fix your URL conf, or set the `.lookup_field` '
            'attribute on the view correctly.' %
            (self.__class__.__name__, lookup_url_kwarg)
        )

        # 构建模型查询条件字典，格式：{模型字段: URL参数值}
        filter_kwargs = {self.lookup_field: self.kwargs[lookup_url_kwarg]}
        
        # 执行模型查询，自动处理404异常情况
        obj = get_object_or_404(queryset, **filter_kwargs)

        # 执行对象级权限校验（可能触发PermissionDenied异常）
        self.check_object_permissions(self.request, obj)

        return obj

    def get_serializer(self, *args, **kwargs):
        """
        Return the serializer instance that should be used for validating and
        deserializing input, and for serializing output.
        """
        serializer_class = self.get_serializer_class()
        kwargs.setdefault('context', self.get_serializer_context())
        return serializer_class(*args, **kwargs)

    def get_serializer_class(self):
        """
        Return the class to use for the serializer.
        Defaults to using `self.serializer_class`.

        You may want to override this if you need to provide different
        serializations depending on the incoming request.

        (Eg. admins get full serialization, others get basic serialization)
        """
        assert self.serializer_class is not None, (
            "'%s' should either include a `serializer_class` attribute, "
            "or override the `get_serializer_class()` method."
            % self.__class__.__name__
        )

        return self.serializer_class

    def get_serializer_context(self):
        """
        Extra context provided to the serializer class.
        """
        return {
            'request': self.request,
            'format': self.format_kwarg,
            'view': self
        }

    def filter_queryset(self, queryset):
        """
        Given a queryset, filter it with whichever filter backend is in use.

        You are unlikely to want to override this method, although you may need
        to call it either from a list view, or from a custom `get_object`
        method if you want to apply the configured filtering backend to the
        default queryset.
        """
        for backend in list(self.filter_backends):
            queryset = backend().filter_queryset(self.request, queryset, self)
        return queryset

    @property
    def paginator(self):
        """
        The paginator instance associated with the view, or `None`.
        """
        if not hasattr(self, '_paginator'):
            if self.pagination_class is None:
                self._paginator = None
            else:
                self._paginator = self.pagination_class()
        return self._paginator

    def paginate_queryset(self, queryset):
        """
        Return a single page of results, or `None` if pagination is disabled.
        """
        if self.paginator is None:
            return None
        return self.paginator.paginate_queryset(queryset, self.request, view=self)

    def get_paginated_response(self, data):
        """
        Return a paginated style `Response` object for the given output data.
        """
        assert self.paginator is not None
        return self.paginator.get_paginated_response(data)


# Concrete view classes that provide method handlers
# by composing the mixin classes with the base view.

class CreateAPIView(mixins.CreateModelMixin,
                    GenericAPIView):
    """
    Concrete view for creating a model instance.
    """
    def post(self, request, *args, **kwargs):
        return self.create(request, *args, **kwargs)


class ListAPIView(mixins.ListModelMixin,
                  GenericAPIView):
    """
    Concrete view for listing a queryset.
    """
    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)


class RetrieveAPIView(mixins.RetrieveModelMixin,
                      GenericAPIView):
    """
    Concrete view for retrieving a model instance.
    """
    def get(self, request, *args, **kwargs):
        return self.retrieve(request, *args, **kwargs)


class DestroyAPIView(mixins.DestroyModelMixin,
                     GenericAPIView):
    """
    Concrete view for deleting a model instance.
    """
    def delete(self, request, *args, **kwargs):
        return self.destroy(request, *args, **kwargs)


class UpdateAPIView(mixins.UpdateModelMixin,
                    GenericAPIView):
    """
    Concrete view for updating a model instance.
    """
    def put(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    def patch(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)


class ListCreateAPIView(mixins.ListModelMixin,
                        mixins.CreateModelMixin,
                        GenericAPIView):
    """
    Concrete view for listing a queryset or creating a model instance.
    """
    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        return self.create(request, *args, **kwargs)


class RetrieveUpdateAPIView(mixins.RetrieveModelMixin,
                            mixins.UpdateModelMixin,
                            GenericAPIView):
    """
    Concrete view for retrieving, updating a model instance.
    """
    def get(self, request, *args, **kwargs):
        return self.retrieve(request, *args, **kwargs)

    def put(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    def patch(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)


class RetrieveDestroyAPIView(mixins.RetrieveModelMixin,
                             mixins.DestroyModelMixin,
                             GenericAPIView):
    """
    Concrete view for retrieving or deleting a model instance.
    """
    def get(self, request, *args, **kwargs):
        return self.retrieve(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        return self.destroy(request, *args, **kwargs)


class RetrieveUpdateDestroyAPIView(mixins.RetrieveModelMixin,
                                   mixins.UpdateModelMixin,
                                   mixins.DestroyModelMixin,
                                   GenericAPIView):
    """
    Concrete view for retrieving, updating or deleting a model instance.
    """
    def get(self, request, *args, **kwargs):
        return self.retrieve(request, *args, **kwargs)

    def put(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    def patch(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        return self.destroy(request, *args, **kwargs)
