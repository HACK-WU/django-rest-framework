"""
Basic building blocks for generic class based views.

We don't bind behaviour to http method handlers yet,
which allows mixin classes to be composed in interesting ways.
"""
from rest_framework import status
from rest_framework.response import Response
from rest_framework.settings import api_settings


class CreateModelMixin:
    """
    Create a model instance.
    """
    def create(self, request, *args, **kwargs):
        """
        创建资源实例的标准入口点（来自CreateModelMixin）
        
        Args:
            request: HttpRequest对象，包含请求数据
            *args: 可变位置参数
            **kwargs: 可变关键字参数
            
        Returns:
            Response: 包含新创建对象数据和HTTP状态码的响应对象
        """
        # 序列化验证流程：获取序列化器实例并进行强验证
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # 核心创建逻辑：通过独立方法执行实际保存操作
        self.perform_create(serializer)
        
        # 生成响应头（主要用于Location头的自动填充）
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        """
        实际执行对象保存的钩子方法（可被子类重写）
        
        Args:
            serializer: 已验证的序列化器实例
        """
        # 默认直接调用序列化器的save方法
        serializer.save()

    def get_success_headers(self, data):
        """
        生成成功响应头（主要实现Location头的自动构建）
        
        Args:
            data: 序列化后的数据字典
            
        Returns:
            dict: 包含Location头的字典（当数据中存在URL字段时）
        """
        # 尝试从序列化数据中提取URL字段作为Location头
        try:
            return {'Location': str(data[api_settings.URL_FIELD_NAME])}
        except (TypeError, KeyError):
            # 当数据不符合预期格式时返回空头
            return {}



class ListModelMixin:
    """
    List a queryset.
    """
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class RetrieveModelMixin:
    """
    Retrieve a model instance.
    """
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)


class UpdateModelMixin:
    """
    Update a model instance.
    """
    def update(self, request, *args, **kwargs):
        """
        处理对象更新的核心方法（支持部分更新）
        
        参数：
        request: Request对象，包含客户端传入的更新数据
        *args: 可变位置参数
        **kwargs: 可变关键字参数，包含路由参数等
        
        返回值：
        Response: 包含序列化后的更新数据，状态码通常为200
        
        流程说明：
        1. 处理部分更新标志
        2. 获取并序列化目标对象
        3. 执行数据验证和对象更新
        4. 处理预取缓存失效问题
        """
        # 从kwargs中取出partial标志，默认关闭完整更新
        partial = kwargs.pop('partial', False)
        
        # 通过路由参数获取要操作的数据对象实例
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        
        # 执行实际更新操作（可能包含自定义的更新逻辑）
        self.perform_update(serializer)

        # 处理预取缓存失效问题：当存在预取缓存时强制清空
        if getattr(instance, '_prefetched_objects_cache', None):
            # Django ORM机制要求：更新后需手动清除关联对象的预取缓存
            instance._prefetched_objects_cache = {}

        # 返回标准格式的响应（包含序列化后的数据和状态码）
        return Response(serializer.data)


    def perform_update(self, serializer):
        serializer.save()

    def partial_update(self, request, *args, **kwargs):
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)


class DestroyModelMixin:
    """
    Destroy a model instance.
    """
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def perform_destroy(self, instance):
        instance.delete()
