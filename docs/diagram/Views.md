# APIView

## APIview.as_view 执行流程



```mermaid
sequenceDiagram
    participant  A as as_view<br>DRF   
    participant E as View<br>Django

    A->>E: super().as_view
    E-->>A: returen view<br>返回视图函数
    A->>A: csrf_exempt(view) csrf认证豁免
    
   
```





## APIVIew.dispatch: request请求处理执行流程

```mermaid
sequenceDiagram
    participant  A as Django request请求处理 
    participant  B as dispatch
    participant  C as Initial
    participant  D as class Request<br>drf中的request对象
    
    A->>B: 
    B->>D: 获得新的Request对象
    D-->>B: return request
    B->>B: default_response_headers<br>设置默认响应头
    B->>C:  
    C->>C: get_renderers<br>确定渲染器和媒体类型
    C->>D: perform_authentication<br>身份认证
    C->>C: check_permissions<br>权限认证
    C->>C: check_throttles<br>限流

    B->>B: 根据HTTP方法选择对应处理函数: handler
    B->>B: response=handler(request)<br>处理请求，获取响应
    B->>B: finalize_response<br>最终响应处理（内容渲染/响应头设置等） 
    B-->>A: response
```



## GenericAPIView 获取单个数据

```mermaid
sequenceDiagram
    participant A as 客户端
    participant B as GenericAPIView
    participant C as QuerySet 
    participant F as Filter<br>过滤器
    participant E as Permissions<br>权限
    participant D as Serializer<br>序列化器
    

    A->>B: get_object
    B->>C: get_queryset
    C-->>B: return queryset
    B->>F: filter_queryset(queryset)
    F-->>B: return queryset
    B->>B: obj=get_object_or_404<br>获取到单个obj 
    B->>E: check_object_permissions(obj)
    B-->>A: return obj

    A->>B:get_serilizer
    B->>D: get_serializer_class
    D-->>B: return serializer_class
    B->>B: get_serializer_context<br>获取上下文内容
    B-->>A: return serializer_instance<br>序列化器实例

    A-->>A: serializer_instance(obj).data<br>序列化数据，并获取结果

```



## RetrieveModelViewSet(RetrieveModelMixin,GenericViewSet)

```mermaid
sequenceDiagram
    participant D as 客户端
    participant A as RetrieveModelMixin
    participant B as GenericAPIView
  

    D->>A: 发起请求GET,获取单个数据
    A->>B: get_object
    B-->>A: return obj
    A->>B:get_serialaizer
    B-->>A: return serializer_instance<br>序列化器实例
    A-->>D: return  serializer_instance(obj).data<br>序列化数据，并获取结果








```

## ListModelViewSet(ListModelMixin,GenericViewSet)

```mermaid
sequenceDiagram
    participant C as 客户端
    participant A as ListModelMixin
    participant B as GenericAPIView
    participant F as Pagination<br>分页器
    C ->> A: 发情请求GET
    A ->> B: filter_queryset(get_queryset())
    B -->> A: return queryset
    A ->> B: paginate_queryset(queryset)
    B ->> F: pagination_class()<br>获取分页器
    F -->> B: return paginator
    B ->> B: page=paginate_queryset(queryset)<br>执行分页
    B -->> A: return page

    critical 分页数据是否存在
        A ->> A: page is None?

    option No 分页成功
        A ->> B: get_serializer(page, many=True)
    option Yes 分页失败
        A ->> B: get_serializer(queryset, many=True)
    end
    B -->> A: return serializer
    A -->> C: return serializer.data
```

