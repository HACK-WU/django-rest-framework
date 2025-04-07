# 默认配置信息
```python
ISO_8601 = 'iso-8601'
DEFAULTS = {
    # --------------------------------------------
    # 基础API策略配置
    # --------------------------------------------
    
    # 默认响应渲染器（用于格式化响应数据）
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',         # JSON格式渲染器
        'rest_framework.renderers.BrowsableAPIRenderer',  # 可浏览API的HTML渲染器
    ],
    
    # 默认请求解析器（用于解析传入数据）
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',      # 解析JSON数据
        'rest_framework.parsers.FormParser',      # 解析表单数据
        'rest_framework.parsers.MultiPartParser'  # 解析多部分表单（文件上传）
    ],
    
    # 默认认证类（身份验证方式）
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',  # 使用Django的会话认证
        'rest_framework.authentication.BasicAuthentication'     # 基础HTTP认证
    ],
    
    # 默认权限类（访问控制）
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',  # 允许所有用户（包括未认证）
    ],
    
    # 默认限流类（API访问频率限制）
    'DEFAULT_THROTTLE_CLASSES': [],
    
    # 内容协商类（决定响应格式）
    'DEFAULT_CONTENT_NEGOTIATION_CLASS': 'rest_framework.negotiation.DefaultContentNegotiation',
    
    # 元数据类（API端点描述）
    'DEFAULT_METADATA_CLASS': 'rest_framework.metadata.SimpleMetadata',
    
    # 版本控制类（API版本管理）
    'DEFAULT_VERSIONING_CLASS': None,

    # --------------------------------------------
    # 通用视图行为配置
    # --------------------------------------------
    
    # 分页类（列表数据分页方式）
    'DEFAULT_PAGINATION_CLASS': None,
    
    # 默认过滤器后端（数据过滤方式）
    'DEFAULT_FILTER_BACKENDS': [],

    # --------------------------------------------
    # Schema配置（API文档生成）
    # --------------------------------------------
    'DEFAULT_SCHEMA_CLASS': 'rest_framework.schemas.openapi.AutoSchema',

    # --------------------------------------------
    # 限流策略配置
    # --------------------------------------------
    'DEFAULT_THROTTLE_RATES': {
        'user': None,   # 认证用户默认限流速率（示例：'100/day'）
        'anon': None,    # 匿名用户默认限流速率
    },
    'NUM_PROXIES': None,  # 代理服务器数量（用于准确获取客户端IP）

    # --------------------------------------------
    # 分页配置
    # --------------------------------------------
    'PAGE_SIZE': None,  # 每页默认数据条数

    # --------------------------------------------
    # 过滤配置
    # --------------------------------------------
    'SEARCH_PARAM': 'search',    # 搜索查询参数名
    'ORDERING_PARAM': 'ordering',# 排序查询参数名

    # --------------------------------------------
    # 版本控制配置
    # --------------------------------------------
    'DEFAULT_VERSION': None,      # 默认API版本
    'ALLOWED_VERSIONS': None,     # 允许的版本列表
    'VERSION_PARAM': 'version',   # 版本查询参数名

    # --------------------------------------------
    # 认证相关配置
    # --------------------------------------------
    # 未认证用户对应的用户模型
    'UNAUTHENTICATED_USER': 'django.contrib.auth.models.AnonymousUser',
    # 未认证令牌（一般不使用）
    'UNAUTHENTICATED_TOKEN': None,

    # --------------------------------------------
    # 视图配置
    # --------------------------------------------
    'VIEW_NAME_FUNCTION': 'rest_framework.views.get_view_name',          # 视图名称生成函数
    'VIEW_DESCRIPTION_FUNCTION': 'rest_framework.views.get_view_description',  # 视图描述生成函数

    # --------------------------------------------
    # 异常处理配置
    # --------------------------------------------
    'EXCEPTION_HANDLER': 'rest_framework.views.exception_handler',  # 自定义异常处理器
    'NON_FIELD_ERRORS_KEY': 'non_field_errors',  # 非字段错误的键名

    # --------------------------------------------
    # 测试配置
    # --------------------------------------------
    # 测试请求的渲染器
    'TEST_REQUEST_RENDERER_CLASSES': [
        'rest_framework.renderers.MultiPartRenderer',  # 多部分表单渲染器
        'rest_framework.renderers.JSONRenderer'        # JSON渲染器
    ],
    'TEST_REQUEST_DEFAULT_FORMAT': 'multipart',  # 测试请求默认格式

    # --------------------------------------------
    # 超链接相关配置
    # --------------------------------------------
    'URL_FORMAT_OVERRIDE': 'format',    # 格式覆盖参数名
    'FORMAT_SUFFIX_KWARG': 'format',    # 格式后缀参数名
    'URL_FIELD_NAME': 'url',            # URL字段名称

    # --------------------------------------------
    # 输入输出格式配置（日期时间）
    # --------------------------------------------
    'DATE_FORMAT': ISO_8601,              # 日期输出格式
    'DATE_INPUT_FORMATS': [ISO_8601],     # 日期输入格式
    
    'DATETIME_FORMAT': ISO_8601,          # 日期时间输出格式
    'DATETIME_INPUT_FORMATS': [ISO_8601], # 日期时间输入格式
    
    'TIME_FORMAT': ISO_8601,              # 时间输出格式
    'TIME_INPUT_FORMATS': [ISO_8601],     # 时间输入格式

    # --------------------------------------------
    # 编码配置
    # --------------------------------------------
    'UNICODE_JSON': True,            # 使用Unicode编码JSON
    'COMPACT_JSON': True,            # 生成紧凑的JSON
    'STRICT_JSON': True,             # 严格的JSON解析
    'COERCE_DECIMAL_TO_STRING': True,# 将Decimal类型转为字符串
    'UPLOADED_FILES_USE_URL': True,  # 文件字段使用URL表示

    # --------------------------------------------
    # 可浏览API配置
    # --------------------------------------------
    'HTML_SELECT_CUTOFF': 1000,  # 下拉选择框最大显示项数
    'HTML_SELECT_CUTOFF_TEXT': "More than {count} items...",  # 超出显示项的提示文本

    # --------------------------------------------
    # Schema高级配置
    # --------------------------------------------
    'SCHEMA_COERCE_PATH_PK': True,  # 将路径参数中的pk强制转换为ID字段
    # 方法名称映射（用于生成Schema）
    'SCHEMA_COERCE_METHOD_NAMES': {
        'retrieve': 'read',    # 将retrieve映射为read
        'destroy': 'delete'     # 将destroy映射为delete
    },
}
```
