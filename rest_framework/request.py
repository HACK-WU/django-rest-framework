"""
The Request class is used as a wrapper around the standard request object.

The wrapped request then offers a richer API, in particular :

    - content automatically parsed according to `Content-Type` header,
      and available as `request.data`
    - full support of PUT method, including support for file uploads
    - form overloading of HTTP method, content type and content
"""
import io
import sys
from contextlib import contextmanager

from django.conf import settings
from django.http import HttpRequest, QueryDict
from django.http.request import RawPostDataException
from django.utils.datastructures import MultiValueDict
from django.utils.http import parse_header_parameters

from rest_framework import exceptions
from rest_framework.settings import api_settings


def is_form_media_type(media_type):
    """
    Return True if the media type is a valid form media type.
    """
    base_media_type, params = parse_header_parameters(media_type)
    return (base_media_type == 'application/x-www-form-urlencoded' or
            base_media_type == 'multipart/form-data')


class override_method:
    """
    A context manager that temporarily overrides the method on a request,
    additionally setting the `view.request` attribute.

    Usage:

        with override_method(view, request, 'POST') as request:
            ... # Do stuff with `view` and `request`
    """

    def __init__(self, view, request, method):
        self.view = view
        self.request = request
        self.method = method
        self.action = getattr(view, 'action', None)

    def __enter__(self):
        self.view.request = clone_request(self.request, self.method)
        # For viewsets we also set the `.action` attribute.
        action_map = getattr(self.view, 'action_map', {})
        self.view.action = action_map.get(self.method.lower())
        return self.view.request

    def __exit__(self, *args, **kwarg):
        self.view.request = self.request
        self.view.action = self.action


class WrappedAttributeError(Exception):
    pass


@contextmanager
def wrap_attributeerrors():
    """
    Used to re-raise AttributeErrors caught during authentication, preventing
    these errors from otherwise being handled by the attribute access protocol.
    """
    try:
        yield
    except AttributeError:
        info = sys.exc_info()
        exc = WrappedAttributeError(str(info[1]))
        raise exc.with_traceback(info[2])


class Empty:
    """
    Placeholder for unset attributes.
    Cannot use `None`, as that may be a valid value.
    """
    pass


def _hasattr(obj, name):
    return not getattr(obj, name) is Empty


def clone_request(request, method):
    """
    Internal helper method to clone a request, replacing with a different
    HTTP method.  Used for checking permissions against other methods.
    """
    ret = Request(request=request._request,
                  parsers=request.parsers,
                  authenticators=request.authenticators,
                  negotiator=request.negotiator,
                  parser_context=request.parser_context)
    ret._data = request._data
    ret._files = request._files
    ret._full_data = request._full_data
    ret._content_type = request._content_type
    ret._stream = request._stream
    ret.method = method
    if hasattr(request, '_user'):
        ret._user = request._user
    if hasattr(request, '_auth'):
        ret._auth = request._auth
    if hasattr(request, '_authenticator'):
        ret._authenticator = request._authenticator
    if hasattr(request, 'accepted_renderer'):
        ret.accepted_renderer = request.accepted_renderer
    if hasattr(request, 'accepted_media_type'):
        ret.accepted_media_type = request.accepted_media_type
    if hasattr(request, 'version'):
        ret.version = request.version
    if hasattr(request, 'versioning_scheme'):
        ret.versioning_scheme = request.versioning_scheme
    return ret


class ForcedAuthentication:
    """
    This authentication class is used if the test client or request factory
    forcibly authenticated the request.
    """

    def __init__(self, force_user, force_token):
        self.force_user = force_user
        self.force_token = force_token

    def authenticate(self, request):
        return (self.force_user, self.force_token)


class Request:
    """
    Wrapper allowing to enhance a standard `HttpRequest` instance.

    Kwargs:
        request (HttpRequest): 原始请求实例，必须为django.http.HttpRequest类型
        parsers (list/tuple, optional): 用于解析请求内容的解析器集合，默认为空元组
        authenticators (list/tuple, optional): 用于请求用户认证的认证器集合，默认为空元组
        negotiator (object, optional): 内容协商处理器，默认使用内置的_default_negotiator
        parser_context (dict, optional): 解析器上下文字典，包含请求相关元数据，默认会创建包含
            request和encoding键的基础上下文
    """

    def __init__(self, request, parsers=None, authenticators=None,
                 negotiator=None, parser_context=None):
        # 强制类型校验确保request参数合法性
        assert isinstance(request, HttpRequest), (
            'The `request` argument must be an instance of '
            '`django.http.HttpRequest`, not `{}.{}`.'
            .format(request.__class__.__module__, request.__class__.__name__)
        )

        # 核心属性初始化
        self._request = request
        self.parsers = parsers or ()
        self.authenticators = authenticators or ()
        self.negotiator = negotiator or self._default_negotiator()
        self.parser_context = parser_context
        
        # 延迟初始化占位符
        self._data = Empty
        self._files = Empty
        self._full_data = Empty
        self._content_type = Empty
        self._stream = Empty


        # 构建解析器上下文
        #
        if self.parser_context is None:
            self.parser_context = {}
        self.parser_context['request'] = self
        self.parser_context['encoding'] = request.encoding or settings.DEFAULT_CHARSET

        # 处理强制认证场景
        """
        强制认证是Django REST framework中用于测试场景的特殊认证机制，主要作用如下：
        1、设计目的
            -专为测试客户端和请求工厂设计
            -允许绕过常规认证流程
            -直接注入预设的认证凭证
        2、核心特征
            通过设置请求对象的特殊属性激活：
            request._force_auth_user = test_user  # 注入测试用户
            request._force_auth_token = test_token  # 注入测试令牌
            
        3、通过通过中间件触发强制认证
           # 在middleware.py中添加
            class PostmanBypassAuthMiddleware:
                def __init__(self, get_response):
                    self.get_response = get_response
            
                def __call__(self, request):
                    # 通过特定Header触发模拟认证
                    if request.META.get('HTTP_X_FORCE_AUTH') == 'postman':
                        request._force_auth_user = User.objects.get(username='postman_user')
                        request._force_auth_token = 'postman_demo_token'
                    return self.get_response(request)
            
            # settings.py配置
            MIDDLEWARE = [
                ...
                'yourapp.middleware.PostmanBypassAuthMiddleware',
            ]        
        """
        force_user = getattr(request, '_force_auth_user', None)
        force_token = getattr(request, '_force_auth_token', None)
        if force_user is not None or force_token is not None:
            forced_auth = ForcedAuthentication(force_user, force_token)
            self.authenticators = (forced_auth,)


    def __repr__(self):
        return '<%s.%s: %s %r>' % (
            self.__class__.__module__,
            self.__class__.__name__,
            self.method,
            self.get_full_path())

    # Allow generic typing checking for requests.
    def __class_getitem__(cls, *args, **kwargs):
        return cls

    def _default_negotiator(self):
        return api_settings.DEFAULT_CONTENT_NEGOTIATION_CLASS()

    @property
    def content_type(self):
        meta = self._request.META
        return meta.get('CONTENT_TYPE', meta.get('HTTP_CONTENT_TYPE', ''))

    @property
    def stream(self):
        """
        Returns an object that may be used to stream the request content.
        """
        if not _hasattr(self, '_stream'):
            self._load_stream()
        return self._stream

    @property
    def query_params(self):
        """
        More semantically correct name for request.GET.
        """
        return self._request.GET

    @property
    def data(self):
        if not _hasattr(self, '_full_data'):
            with wrap_attributeerrors():
                self._load_data_and_files()
        return self._full_data

    @property
    def user(self):
        """
        Returns the user associated with the current request, as authenticated
        by the authentication classes provided to the request.
        """
        if not hasattr(self, '_user'):
            with wrap_attributeerrors():
                self._authenticate()
        return self._user

    @user.setter
    def user(self, value):
        """
        Sets the user on the current request. This is necessary to maintain
        compatibility with django.contrib.auth where the user property is
        set in the login and logout functions.

        Note that we also set the user on Django's underlying `HttpRequest`
        instance, ensuring that it is available to any middleware in the stack.
        """
        self._user = value
        self._request.user = value

    @property
    def auth(self):
        """
        Returns any non-user authentication information associated with the
        request, such as an authentication token.
        """
        if not hasattr(self, '_auth'):
            with wrap_attributeerrors():
                self._authenticate()
        return self._auth

    @auth.setter
    def auth(self, value):
        """
        Sets any non-user authentication information associated with the
        request, such as an authentication token.
        """
        self._auth = value
        self._request.auth = value

    @property
    def successful_authenticator(self):
        """
        Return the instance of the authentication instance class that was used
        to authenticate the request, or `None`.
        """
        if not hasattr(self, '_authenticator'):
            with wrap_attributeerrors():
                self._authenticate()
        return self._authenticator

    def _load_data_and_files(self):
        """
        Parses the request content into `self.data`.
        """
        if not _hasattr(self, '_data'):
            self._data, self._files = self._parse()
            if self._files:
                self._full_data = self._data.copy()
                self._full_data.update(self._files)
            else:
                self._full_data = self._data

            # if a form media type, copy data & files refs to the underlying
            # http request so that closable objects are handled appropriately.
            if is_form_media_type(self.content_type):
                self._request._post = self.POST
                self._request._files = self.FILES

    def _load_stream(self):
        """
        加载并返回请求内容体作为流对象

        方法逻辑说明：
        - 从请求META信息中解析内容长度
        - 根据内容长度和请求状态决定返回的流对象形式

        返回值：
            io.BytesIO | django.core.handlers.wsgi.WSGIRequest | None:
                - None: 内容长度为0时返回
                - 原始请求对象：当内容长度非0且请求未被读取过时
                - BytesIO对象：当请求体已被部分读取时，用内存流包装已读取的内容

        异常处理：
            捕获内容长度转换异常，将无效长度视为0处理
        """
        """
        Return the content body of the request, as a stream.
        """
        meta = self._request.META
        # 解析请求头中的内容长度，处理可能的转换异常
        try:
            content_length = int(
                meta.get('CONTENT_LENGTH', meta.get('HTTP_CONTENT_LENGTH', 0))
            )
        except (ValueError, TypeError):
            content_length = 0

        # 根据内容长度和请求状态设置数据流
        if content_length == 0:
            # 无内容时设置为空
            self._stream = None
        elif not self._request._read_started:
            # 请求未被读取时使用原始请求对象作为流
            self._stream = self._request
        else:
            # 请求已被部分读取时使用内存流包装已读取内容
            self._stream = io.BytesIO(self.body)


    def _supports_form_parsing(self):
        """
        Return True if this requests supports parsing form data.
        """
        # 1.application/x-www-form-urlencoded 格式数据示例
        # POST /api/submit/ HTTP/1.1
        # Content-Type: application/x-www-form-urlencoded
        #
        # username=admin&password=123456

        # 2.multipart/form-data 格式数据示例
        # POST /api/upload/ HTTP/1.1
        # Content-Type: multipart/form-data; boundary=----WebKitFormBoundary
        #
        # ------WebKitFormBoundary
        # Content-Disposition: form-data; name="file"; filename="example.txt"
        # Content-Type: text/plain
        #
        # This is an example file.<文件二进制内容>
        # ------WebKitFormBoundary--

        form_media = (
            'application/x-www-form-urlencoded',
            'multipart/form-data'
        )
        return any(parser.media_type in form_media for parser in self.parsers)

    def _parse(self):
        """
        解析请求内容并提取数据和文件

        方法会尝试从请求流中解析内容，根据内容类型选择合适的解析器进行处理。
        支持表单数据解析，处理中间件已访问POST的情况，并处理空流或空媒体类型的情况。

        返回:
            tuple: 包含两个元素的元组，第一个元素为解析后的数据(通常为字典或QueryDict)，
                第二个元素为解析后的文件数据(通常为MultiValueDict)

        异常:
            UnsupportedMediaType: 当没有找到支持当前媒体类型的解析器时抛出
            ParseError: 解析过程中发生错误时抛出
        """
        # 获取请求的内容类型
        media_type = self.content_type
        try:
            # 尝试获取请求体数据流
            stream = self.stream
        except RawPostDataException:
            # 处理请求流已被读取的情况（例如中间件已处理过POST）
            if not hasattr(self._request, '_post'):
                raise
            # 当支持表单解析时直接返回已解析的表单数据
            if self._supports_form_parsing():
                return (self._request.POST, self._request.FILES)
            stream = None

        # 处理空流或未指定媒体类型的情况
        if stream is None or media_type is None:
            # 根据媒体类型决定返回空表单数据还是普通空字典
            if media_type and is_form_media_type(media_type):
                empty_data = QueryDict('', encoding=self._request._encoding)
            else:
                empty_data = {}
            empty_files = MultiValueDict()
            return (empty_data, empty_files)

        # 根据内容协商选择合适的数据解析器
        parser = self.negotiator.select_parser(self, self.parsers)

        # 没有可用解析器时抛出媒体类型不支持异常
        if not parser:
            raise exceptions.UnsupportedMediaType(media_type)

        try:
            # 调用解析器进行实际的内容解析
            parsed = parser.parse(stream, media_type, self.parser_context)
        except Exception:
            # 解析失败时初始化空数据容器并重新抛出异常
            self._data = QueryDict('', encoding=self._request._encoding)
            self._files = MultiValueDict()
            self._full_data = self._data
            raise

        # 处理解析器返回结果，适配不同解析器的返回格式
        try:
            # 标准情况：解析器返回包含data和files属性的对象
            return (parsed.data, parsed.files)
        except AttributeError:
            # 兼容情况：解析器直接返回数据，初始化空文件字典
            empty_files = MultiValueDict()
            return (parsed, empty_files)

    def _authenticate(self):
        """
        Attempt to authenticate the request using each authentication instance
        in turn.
        """
        for authenticator in self.authenticators:
            try:
                user_auth_tuple = authenticator.authenticate(self)
            except exceptions.APIException:
                self._not_authenticated()
                raise

            if user_auth_tuple is not None:
                self._authenticator = authenticator
                self.user, self.auth = user_auth_tuple
                return

        self._not_authenticated()

    def _not_authenticated(self):
        """
        Set authenticator, user & authtoken representing an unauthenticated request.

        Defaults are None, AnonymousUser & None.
        """
        self._authenticator = None

        if api_settings.UNAUTHENTICATED_USER:
            self.user = api_settings.UNAUTHENTICATED_USER()
        else:
            self.user = None

        if api_settings.UNAUTHENTICATED_TOKEN:
            self.auth = api_settings.UNAUTHENTICATED_TOKEN()
        else:
            self.auth = None

    def __getattr__(self, attr):
        """
        If an attribute does not exist on this instance, then we also attempt
        to proxy it to the underlying HttpRequest object.
        """
        try:
            _request = self.__getattribute__("_request")
            return getattr(_request, attr)
        except AttributeError:
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{attr}'")

    @property
    def POST(self):
        # Ensure that request.POST uses our request parsing.
        if not _hasattr(self, '_data'):
            with wrap_attributeerrors():
                self._load_data_and_files()
        if is_form_media_type(self.content_type):
            return self._data
        return QueryDict('', encoding=self._request._encoding)

    @property
    def FILES(self):
        # Leave this one alone for backwards compat with Django's request.FILES
        # Different from the other two cases, which are not valid property
        # names on the WSGIRequest class.
        if not _hasattr(self, '_files'):
            with wrap_attributeerrors():
                self._load_data_and_files()
        return self._files

    def force_plaintext_errors(self, value):
        # Hack to allow our exception handler to force choice of
        # plaintext or html error responses.
        self._request.is_ajax = lambda: value
