"""
Content negotiation deals with selecting an appropriate renderer given the
incoming request.  Typically this will be based on the request's Accept header.
"""
from django.http import Http404

from rest_framework import exceptions
from rest_framework.settings import api_settings
from rest_framework.utils.mediatypes import (
    _MediaType, media_type_matches, order_by_precedence
)


class BaseContentNegotiation:
    def select_parser(self, request, parsers):
        raise NotImplementedError('.select_parser() must be implemented')

    def select_renderer(self, request, renderers, format_suffix=None):
        raise NotImplementedError('.select_renderer() must be implemented')


class DefaultContentNegotiation(BaseContentNegotiation):
    settings = api_settings

    def select_parser(self, request, parsers):
        """
        Given a list of parsers and a media type, return the appropriate
        parser to handle the incoming request.
        """
        for parser in parsers:
            if media_type_matches(parser.media_type, request.content_type):
                return parser
        return None

    def select_renderer(self, request, renderers, format_suffix=None):
        """
        根据请求和可用渲染器选择合适的渲染器及媒体类型

        Args:
            request (Request): 请求对象，用于获取查询参数和头部信息
            renderers (list): 可用渲染器列表，包含支持的渲染器实例
            format_suffix (str, optional): 格式后缀（如.json），来自URL路径参数

        Returns:
            tuple: 包含两个元素的元组：
                - 选中的渲染器实例
                - 对应的完整媒体类型字符串

        Raises:
            exceptions.NotAcceptable: 当没有可接受的渲染器时抛出
        """
        # 处理格式覆盖逻辑（通过查询参数或路径后缀）
        # 示例："?format=json" 或 URL路径中的 ".json"
        format_query_param = self.settings.URL_FORMAT_OVERRIDE
        format = format_suffix or request.query_params.get(format_query_param)

        # 根据格式参数过滤可用渲染器
        if format:
            renderers = self.filter_renderers(renderers, format)

        # 获取客户端支持的Accept媒体类型列表
        accepts = self.get_accept_list(request)

        # 按优先级顺序遍历所有Accept媒体类型配置
        # 优先匹配更具体的媒体类型（如application/json优先于*/*）
        for media_type_set in order_by_precedence(accepts):
            # 遍历每个渲染器及其支持的媒体类型
            for renderer in renderers:
                for media_type in media_type_set:
                    # 检查当前渲染器是否匹配客户端要求的媒体类型
                    if media_type_matches(renderer.media_type, media_type):
                        # 处理媒体类型参数优先级（如q值、版本参数等）
                        media_type_wrapper = _MediaType(media_type)
                        
                        # 当渲染器的媒体类型比客户端要求的更具体时
                        if (
                            _MediaType(renderer.media_type).precedence >
                            media_type_wrapper.precedence
                        ):
                            # 组合基础媒体类型和客户端参数（如保持indent=8参数）
                            full_media_type = ';'.join(
                                (renderer.media_type,) +
                                tuple(
                                    '{}={}'.format(key, value)
                                    for key, value in media_type_wrapper.params.items()
                                )
                            )
                            return renderer, full_media_type
                        else:
                            # 直接使用客户端提供的完整媒体类型
                            return renderer, media_type

        # 没有找到符合Accept头要求的渲染器时抛出异常
        raise exceptions.NotAcceptable(available_renderers=renderers)


    def filter_renderers(self, renderers, format):
        """
        If there is a '.json' style format suffix, filter the renderers
        so that we only negotiation against those that accept that format.
        """
        renderers = [renderer for renderer in renderers
                     if renderer.format == format]
        if not renderers:
            raise Http404
        return renderers

    def get_accept_list(self, request):
        """
        Given the incoming request, return a tokenized list of media
        type strings.
        """
        header = request.META.get('HTTP_ACCEPT', '*/*')
        return [token.strip() for token in header.split(',')]
