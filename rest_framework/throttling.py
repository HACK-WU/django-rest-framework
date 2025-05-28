"""
Provides various throttling policies.
"""
import time

from django.core.cache import cache as default_cache
from django.core.exceptions import ImproperlyConfigured

from rest_framework.settings import api_settings


class BaseThrottle:
    """
    Rate throttling of requests.
    """

    def allow_request(self, request, view):
        """
        Return `True` if the request should be allowed, `False` otherwise.
        """
        raise NotImplementedError('.allow_request() must be overridden')

    def get_ident(self, request):
        """
        Identify the machine making the request by parsing HTTP_X_FORWARDED_FOR
        if present and number of proxies is > 0. If not use all of
        HTTP_X_FORWARDED_FOR if it is available, if not use REMOTE_ADDR.
        """
        xff = request.META.get('HTTP_X_FORWARDED_FOR')
        remote_addr = request.META.get('REMOTE_ADDR')
        num_proxies = api_settings.NUM_PROXIES

        if num_proxies is not None:
            if num_proxies == 0 or xff is None:
                return remote_addr
            addrs = xff.split(',')
            client_addr = addrs[-min(num_proxies, len(addrs))]
            return client_addr.strip()

        return ''.join(xff.split()) if xff else remote_addr

    def wait(self):
        """
        Optionally, return a recommended number of seconds to wait before
        the next request.
        """
        return None


class SimpleRateThrottle(BaseThrottle):
    """
    基于缓存的简单限流实现，要求子类必须重写`.get_cache_key()`方法。

    属性:
        cache (Cache): 使用的缓存实例，默认使用default_cache
        timer (function): 时间戳获取函数，默认使用time.time
        cache_format (str): 缓存键格式模板，包含%(scope)s和%(ident)s变量
        scope (str | None): 限流作用域标识符
        THROTTLE_RATES (dict): 存储各作用域对应限流速率的字典

    限流速率通过rate属性设置，格式为'number_of_requests/period'，
    period支持单位：秒(s/sec)、分(m/min)、小时(h/hour)、天(d/day)
    """
    cache = default_cache
    timer = time.time
    cache_format = 'throttle_%(scope)s_%(ident)s'
    scope = None
    THROTTLE_RATES = api_settings.DEFAULT_THROTTLE_RATES

    def __init__(self):
        """
        初始化限流器，配置请求速率和时间窗口参数。

        如果子类未定义rate属性，则通过get_rate()获取默认速率，
        并解析为每秒请求数和时间窗口长度（秒）。
        """
        if not getattr(self, 'rate', None):
            self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)

    def get_cache_key(self, request, view):
        """
        生成用于限流的唯一缓存键。必须由子类重写。

        参数:
            request (HttpRequest): 当前请求对象
            view (View): 处理请求的视图实例

        返回:
            str | None: 返回缓存键字符串，若不应限制则返回None

        异常:
            NotImplementedError: 如果子类未实现该方法
        """
        raise NotImplementedError('.get_cache_key() must be overridden')

    def get_rate(self):
        """
        获取当前作用域对应的默认请求速率配置。

        返回:
            str: 限流速率字符串（如'100/day'）

        异常:
            ImproperlyConfigured: 当未设置scope且找不到对应速率配置时抛出
        """
        if not getattr(self, 'scope', None):
            msg = ("You must set either `.scope` or `.rate` for '%s' throttle" %
                   self.__class__.__name__)
            raise ImproperlyConfigured(msg)

        try:
            return self.THROTTLE_RATES[self.scope]
        except KeyError:
            msg = "No default throttle rate set for '%s' scope" % self.scope
            raise ImproperlyConfigured(msg)


    def parse_rate(self, rate):
        """
        将请求速率字符串解析为允许的请求数和时间周期。

        参数:
            rate (str): 请求速率字符串，格式为"<数量>/<周期>"，例如"5/m"表示每分钟5次请求。
                        周期可选单位: s(秒), m(分钟), h(小时), d(天)

        返回:
            tuple: 包含两个元素的元组
                  - num_requests (int): 允许的请求数量
                  - duration (int): 时间周期对应的秒数
        """
        if rate is None:
            return (None, None)
        num, period = rate.split('/')
        num_requests = int(num)
        # 将周期字符转换为对应的秒数
        duration = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}[period[0]]
        return (num_requests, duration)

    def allow_request(self, request, view):
        """
        判断当前请求是否应该被限流。

        参数:
            request: 当前请求对象
            view: 被访问的视图对象

        返回:
            bool: True表示允许请求，False表示需要限流

        注意:
            成功时调用throttle_success()，失败时调用throttle_failure()
        """
        if self.rate is None:
            return True

        self.key = self.get_cache_key(request, view)
        if self.key is None:
            return True

        self.history = self.cache.get(self.key, [])
        self.now = self.timer()

        # 清理历史记录中已过期的请求时间戳
        while self.history and self.history[-1] <= self.now - self.duration:
            self.history.pop()

        # 检查当前请求数是否超过限制
        if len(self.history) >= self.num_requests:
            return self.throttle_failure()
        return self.throttle_success()

    def throttle_success(self):
        """
        处理请求成功通过限流的情况。

        功能:
            将当前请求时间戳插入历史记录首部，
            并更新缓存中的请求历史记录
        """
        self.history.insert(0, self.now)
        self.cache.set(self.key, self.history, self.duration)
        return True

    def throttle_failure(self):
        """
        处理请求被限流的情况。

        返回:
            bool: 始终返回False表示请求被拒绝
        """
        return False

    def wait(self):
        """
        计算推荐的下次请求等待时间。

        返回:
            float/None: 需要等待的秒数（保留小数），或None表示无可用请求配额
        """
        if self.history:
            # 计算从最近一次请求开始的时间窗口剩余时间
            remaining_duration = self.duration - (self.now - self.history[-1])
        else:
            # 如果没有历史记录，使用完整时间窗口
            remaining_duration = self.duration

        # 计算剩余可用请求数
        available_requests = self.num_requests - len(self.history) + 1
        if available_requests <= 0:
            return None

        # 返回单次请求应等待的平均时间
        return remaining_duration / float(available_requests)


class AnonRateThrottle(SimpleRateThrottle):
    """
    Limits the rate of API calls that may be made by a anonymous users.

    The IP address of the request will be used as the unique cache key.
    """
    scope = 'anon'

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            return None  # Only throttle unauthenticated requests.

        return self.cache_format % {
            'scope': self.scope,
            'ident': self.get_ident(request)
        }


class UserRateThrottle(SimpleRateThrottle):
    """
    Limits the rate of API calls that may be made by a given user.

    The user id will be used as a unique cache key if the user is
    authenticated.  For anonymous requests, the IP address of the request will
    be used.
    """
    scope = 'user'

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            ident = request.user.pk
        else:
            ident = self.get_ident(request)

        return self.cache_format % {
            'scope': self.scope,
            'ident': ident
        }


class ScopedRateThrottle(SimpleRateThrottle):
    """
    Limits the rate of API calls by different amounts for various parts of
    the API.  Any view that has the `throttle_scope` property set will be
    throttled.  The unique cache key will be generated by concatenating the
    user id of the request, and the scope of the view being accessed.
    """
    scope_attr = 'throttle_scope'

    def __init__(self):
        # Override the usual SimpleRateThrottle, because we can't determine
        # the rate until called by the view.
        pass

    def allow_request(self, request, view):
        # We can only determine the scope once we're called by the view.
        self.scope = getattr(view, self.scope_attr, None)

        # If a view does not have a `throttle_scope` always allow the request
        if not self.scope:
            return True

        # Determine the allowed request rate as we normally would during
        # the `__init__` call.
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)

        # We can now proceed as normal.
        return super().allow_request(request, view)

    def get_cache_key(self, request, view):
        """
        If `view.throttle_scope` is not set, don't apply this throttle.

        Otherwise generate the unique cache key by concatenating the user id
        with the `.throttle_scope` property of the view.
        """
        if request.user and request.user.is_authenticated:
            ident = request.user.pk
        else:
            ident = self.get_ident(request)

        return self.cache_format % {
            'scope': self.scope,
            'ident': ident
        }
