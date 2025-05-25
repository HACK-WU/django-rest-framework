"""
Provides a set of pluggable permission policies.
"""
from django.http import Http404

from rest_framework import exceptions

SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS')


class OperationHolderMixin:
    def __and__(self, other):
        return OperandHolder(AND, self, other)

    def __or__(self, other):
        return OperandHolder(OR, self, other)

    def __rand__(self, other):
        return OperandHolder(AND, other, self)

    def __ror__(self, other):
        return OperandHolder(OR, other, self)

    def __invert__(self):
        return SingleOperandHolder(NOT, self)


class SingleOperandHolder(OperationHolderMixin):
    def __init__(self, operator_class, op1_class):
        self.operator_class = operator_class
        self.op1_class = op1_class

    def __call__(self, *args, **kwargs):
        op1 = self.op1_class(*args, **kwargs)
        return self.operator_class(op1)


class OperandHolder(OperationHolderMixin):
    def __init__(self, operator_class, op1_class, op2_class):
        self.operator_class = operator_class
        self.op1_class = op1_class
        self.op2_class = op2_class

    def __call__(self, *args, **kwargs):
        op1 = self.op1_class(*args, **kwargs)
        op2 = self.op2_class(*args, **kwargs)
        return self.operator_class(op1, op2)

    def __eq__(self, other):
        return (
            isinstance(other, OperandHolder) and
            self.operator_class == other.operator_class and
            self.op1_class == other.op1_class and
            self.op2_class == other.op2_class
        )

    def __hash__(self):
        return hash((self.operator_class, self.op1_class, self.op2_class))


class AND:
    def __init__(self, op1, op2):
        self.op1 = op1
        self.op2 = op2

    def has_permission(self, request, view):
        return (
            self.op1.has_permission(request, view) and
            self.op2.has_permission(request, view)
        )

    def has_object_permission(self, request, view, obj):
        return (
            self.op1.has_object_permission(request, view, obj) and
            self.op2.has_object_permission(request, view, obj)
        )


class OR:
    def __init__(self, op1, op2):
        self.op1 = op1
        self.op2 = op2

    def has_permission(self, request, view):
        return (
            self.op1.has_permission(request, view) or
            self.op2.has_permission(request, view)
        )

    def has_object_permission(self, request, view, obj):
        return (
            self.op1.has_permission(request, view)
            and self.op1.has_object_permission(request, view, obj)
        ) or (
            self.op2.has_permission(request, view)
            and self.op2.has_object_permission(request, view, obj)
        )


class NOT:
    def __init__(self, op1):
        self.op1 = op1

    def has_permission(self, request, view):
        return not self.op1.has_permission(request, view)

    def has_object_permission(self, request, view, obj):
        return not self.op1.has_object_permission(request, view, obj)


class BasePermissionMetaclass(OperationHolderMixin, type):
    pass


class BasePermission(metaclass=BasePermissionMetaclass):
    """
    A base class from which all permission classes should inherit.
    """

    def has_permission(self, request, view):
        """
        Return `True` if permission is granted, `False` otherwise.
        """
        return True

    def has_object_permission(self, request, view, obj):
        """
        Return `True` if permission is granted, `False` otherwise.
        """
        return True


class AllowAny(BasePermission):
    """
    Allow any access.
    This isn't strictly required, since you could use an empty
    permission_classes list, but it's useful because it makes the intention
    more explicit.
    """

    def has_permission(self, request, view):
        return True


class IsAuthenticated(BasePermission):
    """
    Allows access only to authenticated users.
    """

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)


class IsAdminUser(BasePermission):
    """
    Allows access only to admin users.
    """

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_staff)


class IsAuthenticatedOrReadOnly(BasePermission):
    """
    The request is authenticated as a user, or is a read-only request.
    """

    def has_permission(self, request, view):
        return bool(
            request.method in SAFE_METHODS or
            request.user and
            request.user.is_authenticated
        )


class DjangoModelPermissions(BasePermission):
    """
    The request is authenticated using `django.contrib.auth` permissions.
    See: https://docs.djangoproject.com/en/dev/topics/auth/#permissions

    It ensures that the user is authenticated, and has the appropriate
    `add`/`change`/`delete` permissions on the model.

    This permission can only be applied against view classes that
    provide a `.queryset` attribute.
    """

    # Map HTTP methods to required Django model permission codes
    # Format uses app_label and model_name string substitutions
    # 结构说明：
    # - 键：HTTP方法（大写）
    # - 值：权限字符串列表，支持格式字符串替换
    # 默认配置：
    # - 写操作需要对应模型权限
    # - 读操作不需要额外权限（空列表）
    perms_map = {
        'GET': [],
        'OPTIONS': [],
        'HEAD': [],
        'POST': ['%(app_label)s.add_%(model_name)s'],
        'PUT': ['%(app_label)s.change_%(model_name)s'],
        'PATCH': ['%(app_label)s.change_%(model_name)s'],
        'DELETE': ['%(app_label)s.delete_%(model_name)s'],
    }

    # 是否强制要求用户必须通过认证
    # 当设置为True时，未认证用户直接返回无权限
    authenticated_users_only = True

    def get_required_permissions(self, method, model_cls):
        """
        根据HTTP方法和数据模型类获取需要的权限列表

        Parameters:
        method -- HTTP请求方法（字符串，如'POST'）
        model_cls -- Django模型类对象

        Returns:
        list -- 格式化后的完整权限字符串列表

        Raises:
        MethodNotAllowed -- 当传入不支持的HTTP方法时抛出
        """
        kwargs = {
            'app_label': model_cls._meta.app_label,
            'model_name': model_cls._meta.model_name
        }

        if method not in self.perms_map:
            raise exceptions.MethodNotAllowed(method)

        return [perm % kwargs for perm in self.perms_map[method]]

    def _queryset(self, view):
        """
        验证视图的查询集配置并返回有效查询集

        Parameters:
        view -- Django视图实例

        Returns:
        QuerySet -- 视图关联的模型查询集

        Raises:
        AssertionError -- 当视图未定义queryset或get_queryset方法时抛出
        """
        # 验证视图是否正确定义了查询集获取方式
        assert hasattr(view, 'get_queryset') \
            or getattr(view, 'queryset', None) is not None, (
            'Cannot apply {} on a view that does not set '
            '`.queryset` or have a `.get_queryset()` method.'
        ).format(self.__class__.__name__)

        # 优先使用动态查询集获取方式
        if hasattr(view, 'get_queryset'):
            queryset = view.get_queryset()
            assert queryset is not None, (
                '{}.get_queryset() returned None'.format(view.__class__.__name__)
            )
            return queryset
        return view.queryset

    def has_permission(self, request, view):
        """
        核心权限校验方法，判断请求是否具有访问权限

        Parameters:
        request -- HttpRequest对象，包含用户和请求信息
        view -- Django视图实例

        Returns:
        bool -- True表示有权限，False表示无权限

        处理逻辑：
        1. 基础认证检查
        2. 处理特殊标记的视图豁免权限检查
        3. 获取模型类并生成所需权限列表
        4. 验证用户是否拥有全部所需权限
        """
        # 认证用户检查（当authenticated_users_only=True时）
        if not request.user or (
           not request.user.is_authenticated and self.authenticated_users_only):
            return False

        # 处理特殊豁免标记（如DefaultRouter的根视图）
        if getattr(view, '_ignore_model_permissions', False):
            return True

        # 获取视图关联的模型类
        queryset = self._queryset(view)
        # 生成当前请求方法需要的权限列表
        perms = self.get_required_permissions(request.method, queryset.model)

        # 验证用户是否拥有所有需要的权限
        return request.user.has_perms(perms)


class DjangoModelPermissionsOrAnonReadOnly(DjangoModelPermissions):
    """
    Similar to DjangoModelPermissions, except that anonymous users are
    allowed read-only access.
    """
    authenticated_users_only = False


class DjangoObjectPermissions(DjangoModelPermissions):
    """
    The request is authenticated using Django's object-level permissions.
    It requires an object-permissions-enabled backend, such as Django Guardian.

    It ensures that the user is authenticated, and has the appropriate
    `add`/`change`/`delete` permissions on the object using .has_perms.

    This permission can only be applied against view classes that
    provide a `.queryset` attribute.
    """
    perms_map = {
        'GET': [],
        'OPTIONS': [],
        'HEAD': [],
        'POST': ['%(app_label)s.add_%(model_name)s'],
        'PUT': ['%(app_label)s.change_%(model_name)s'],
        'PATCH': ['%(app_label)s.change_%(model_name)s'],
        'DELETE': ['%(app_label)s.delete_%(model_name)s'],
    }

    def get_required_object_permissions(self, method, model_cls):
        kwargs = {
            'app_label': model_cls._meta.app_label,
            'model_name': model_cls._meta.model_name
        }

        if method not in self.perms_map:
            raise exceptions.MethodNotAllowed(method)

        return [perm % kwargs for perm in self.perms_map[method]]

    def has_object_permission(self, request, view, obj):
        """
        检查请求用户是否对特定对象具有操作权限。

        Args:
            request (HttpRequest): 当前HTTP请求对象，包含用户、方法等信息。
            view (View): 当前处理的Django视图实例，用于获取模型查询集。
            obj (Model): 需要验证权限的目标对象实例。

        Returns:
            bool: 若用户具有权限返回True；否则返回False或抛出Http404异常。

        Note:
            该函数需在类级别权限校验(has_permission)通过后调用。
        """
        # authentication checks have already executed via has_permission
        queryset = self._queryset(view)
        model_cls = queryset.model
        user = request.user

        # 获取当前请求方法对应的对象级权限要求
        perms = self.get_required_object_permissions(request.method, model_cls)

        # 核心权限校验逻辑：验证用户是否具备所有要求的权限
        if not user.has_perms(perms, obj):
            # 权限不足时的处理策略：
            # 1. 安全方法（GET/HEAD/OPTIONS）直接返回404
            # 2. 非安全方法需额外检查读权限来决定返回404或403
            if request.method in SAFE_METHODS:
                # 安全方法因读权限不足直接隐藏对象存在性
                raise Http404

            # 非安全方法需二次检查读权限
            read_perms = self.get_required_object_permissions('GET', model_cls)
            if not user.has_perms(read_perms, obj):
                # 读权限也不存在时隐藏对象
                raise Http404

            # 有读权限但无写权限时返回权限拒绝
            return False

        return True

