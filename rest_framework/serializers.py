"""
Serializers and ModelSerializers are similar to Forms and ModelForms.
Unlike forms, they are not constrained to dealing with HTML output, and
form encoded input.

Serialization in REST framework is a two-phase process:

1. Serializers marshal between complex types like model instances, and
python primitives.
2. The process of marshalling between python primitives and request and
response content is handled by parsers and renderers.
"""

import contextlib
import copy
import inspect
import traceback
from collections import defaultdict
from collections.abc import Mapping

from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models
from django.db.models.fields import Field as DjangoModelField
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from rest_framework.compat import (
    get_referenced_base_fields_from_q, postgres_fields
)
from rest_framework.exceptions import ErrorDetail, ValidationError
from rest_framework.fields import get_error_detail
from rest_framework.settings import api_settings
from rest_framework.utils import html, model_meta, representation
from rest_framework.utils.field_mapping import (
    ClassLookupDict, get_field_kwargs, get_nested_relation_kwargs,
    get_relation_kwargs, get_url_kwargs
)
from rest_framework.utils.serializer_helpers import (
    BindingDict, BoundField, JSONBoundField, NestedBoundField, ReturnDict,
    ReturnList
)
from rest_framework.validators import (
    UniqueForDateValidator, UniqueForMonthValidator, UniqueForYearValidator,
    UniqueTogetherValidator
)

# Note: We do the following so that users of the framework can use this style:
#
#     example_field = serializers.CharField(...)
#
# This helps keep the separation between model fields, form fields, and
# serializer fields more explicit.
from rest_framework.fields import (  # NOQA # isort:skip
    BooleanField, CharField, ChoiceField, DateField, DateTimeField, DecimalField,
    DictField, DurationField, EmailField, Field, FileField, FilePathField, FloatField,
    HiddenField, HStoreField, IPAddressField, ImageField, IntegerField, JSONField,
    ListField, ModelField, MultipleChoiceField, ReadOnlyField,
    RegexField, SerializerMethodField, SlugField, TimeField, URLField, UUIDField,
)
from rest_framework.relations import (  # NOQA # isort:skip
    HyperlinkedIdentityField, HyperlinkedRelatedField, ManyRelatedField,
    PrimaryKeyRelatedField, RelatedField, SlugRelatedField, StringRelatedField,
)

# Non-field imports, but public API
from rest_framework.fields import (  # NOQA # isort:skip
    CreateOnlyDefault, CurrentUserDefault, SkipField, empty
)
from rest_framework.relations import Hyperlink, PKOnlyObject  # NOQA # isort:skip

# We assume that 'validators' are intended for the child serializer,
# rather than the parent serializer.
LIST_SERIALIZER_KWARGS = (
    'read_only', 'write_only', 'required', 'default', 'initial', 'source',
    'label', 'help_text', 'style', 'error_messages', 'allow_empty',
    'instance', 'data', 'partial', 'context', 'allow_null',
    'max_length', 'min_length'
)
LIST_SERIALIZER_KWARGS_REMOVE = ('allow_empty', 'min_length', 'max_length')

ALL_FIELDS = '__all__'


# BaseSerializer
# --------------

class BaseSerializer(Field):
    """
    BaseSerializer 类提供了一个最小化的基类，可用于编写自定义序列化器实现

    注意：该类严格限制操作/属性的使用顺序，以确保正确的使用方式

    参数说明：
        data  : 可选参数，当传入数据时进入'数据反序列化模式'，否则进入'序列化模式'
        context : 可选上下文字典，可用于传递额外数据到序列化器
        instance : 可选对象实例，用于序列化模式下的对象表示
        many : 布尔值，标识是否处理多个对象（原始代码未完整可能需要实际参数列表）

    方法及属性可用性规则：
    当传入 data 参数时：
        - is_valid()       可用
        - initial_data     可用
        - validated_data   仅在调用 is_valid() 后可用
        - errors           仅在调用 is_valid() 后可用
        - data             仅在调用 is_valid() 后可用

    当未传入 data 参数时（序列化模式）：
        - is_valid()       不可用
        - initial_data     不可用
        - validated_data   不可用
        - errors           不可用
        - data             直接可用（用于获取序列化后的数据表示）

    返回值：
        无，作为基类需要子类实现具体逻辑
    """


    def __init__(self, instance=None, data=empty, **kwargs):
        self.instance = instance
        if data is not empty:
            self.initial_data = data
        self.partial = kwargs.pop('partial', False)
        self._context = kwargs.pop('context', {})
        kwargs.pop('many', None)
        super().__init__(**kwargs)

    def __new__(cls, *args, **kwargs):
        # We override this method in order to automatically create
        # `ListSerializer` classes instead when `many=True` is set.
        if kwargs.pop('many', False):
            return cls.many_init(*args, **kwargs)
        return super().__new__(cls, *args, **kwargs)

    # Allow type checkers to make serializers generic.
    def __class_getitem__(cls, *args, **kwargs):
        return cls

    @classmethod
    def many_init(cls, *args, **kwargs):
        """
        类方法，用于在创建`many=True`的列表序列化器时初始化父类`ListSerializer`

        Args:
            cls (Serializer): 当前序列化器类，将作为子序列化器使用
            *args: 可变位置参数，将传递给子序列化器和父列表序列化器
            **kwargs: 可变关键字参数，需要分离出父类和子类的参数

        Returns:
            ListSerializer: 实例化的列表序列化器对象或其子类对象

        实现说明:
            1. 分离出需要传递给父列表序列化器的参数
            2. 创建子序列化器实例
            3. 合并父类特定参数
            4. 最终创建并返回列表序列化器实例
        """
        # 初始化父类参数存储字典
        list_kwargs = {}
        
        # 分离需要从kwargs中移除并专门传递给父类的参数
        # LIST_SERIALIZER_KWARGS_REMOVE包含需要移交给父类的参数名列表
        for key in LIST_SERIALIZER_KWARGS_REMOVE:
            value = kwargs.pop(key, None)
            if value is not None:
                list_kwargs[key] = value

        # 创建子序列化器实例，将剩余参数传递给子类
        list_kwargs['child'] = cls(*args, **kwargs)

        # 从原始kwargs中筛选出父类允许使用的参数进行合并
        # LIST_SERIALIZER_KWARGS定义了父类可接受的参数名列表
        list_kwargs.update({
            key: value for key, value in kwargs.items()
            if key in LIST_SERIALIZER_KWARGS
        })

        # 获取Meta类配置，确定要使用的列表序列化器类
        meta = getattr(cls, 'Meta', None)
        list_serializer_class = getattr(meta, 'list_serializer_class', ListSerializer)

        # 使用处理后的参数实例化列表序列化器
        return list_serializer_class(*args, **list_kwargs)


    def to_internal_value(self, data):
        raise NotImplementedError('`to_internal_value()` must be implemented.')

    def to_representation(self, instance):
        raise NotImplementedError('`to_representation()` must be implemented.')

    def update(self, instance, validated_data):
        raise NotImplementedError('`update()` must be implemented.')

    def create(self, validated_data):
        raise NotImplementedError('`create()` must be implemented.')

    def save(self, **kwargs):
        assert hasattr(self, '_errors'), (
            'You must call `.is_valid()` before calling `.save()`.'
        )

        assert not self.errors, (
            'You cannot call `.save()` on a serializer with invalid data.'
        )

        # Guard against incorrect use of `serializer.save(commit=False)`
        assert 'commit' not in kwargs, (
            "'commit' is not a valid keyword argument to the 'save()' method. "
            "If you need to access data before committing to the database then "
            "inspect 'serializer.validated_data' instead. "
            "You can also pass additional keyword arguments to 'save()' if you "
            "need to set extra attributes on the saved model instance. "
            "For example: 'serializer.save(owner=request.user)'.'"
        )

        assert not hasattr(self, '_data'), (
            "You cannot call `.save()` after accessing `serializer.data`."
            "If you need to access data before committing to the database then "
            "inspect 'serializer.validated_data' instead. "
        )

        validated_data = {**self.validated_data, **kwargs}

        if self.instance is not None:
            self.instance = self.update(self.instance, validated_data)
            assert self.instance is not None, (
                '`update()` did not return an object instance.'
            )
        else:
            self.instance = self.create(validated_data)
            assert self.instance is not None, (
                '`create()` did not return an object instance.'
            )

        return self.instance

    def is_valid(self, *, raise_exception=False):
        assert hasattr(self, 'initial_data'), (
            'Cannot call `.is_valid()` as no `data=` keyword argument was '
            'passed when instantiating the serializer instance.'
        )

        if not hasattr(self, '_validated_data'):
            try:
                self._validated_data = self.run_validation(self.initial_data)
            except ValidationError as exc:
                self._validated_data = {}
                self._errors = exc.detail
            else:
                self._errors = {}

        if self._errors and raise_exception:
            raise ValidationError(self.errors)

        return not bool(self._errors)

    @property
    def data(self):
        """
        获取序列化后的数据表示

        该方法负责在安全状态下返回序列化后的数据。在访问数据前必须确保已调用`.is_valid()`完成验证，
        否则会抛出异常。数据生成采用延迟计算机制，只在首次访问时生成并缓存结果。

        Returns:
            dict: 序列化后的数据结果，具体类型由`to_representation`方法决定

        Raises:
            AssertionError: 当未经验证直接访问数据时抛出
        """
        
        # 前置条件检查：确保在访问数据前已完成验证
        if hasattr(self, 'initial_data') and not hasattr(self, '_validated_data'):
            msg = (
                'When a serializer is passed a `data` keyword argument you '
                'must call `.is_valid()` before attempting to access the '
                'serialized `.data` representation.\n'
                'You should either call `.is_valid()` first, '
                'or access `.initial_data` instead.'
            )
            raise AssertionError(msg)

        # 延迟数据生成逻辑：根据对象状态选择不同的数据源进行序列化
        if not hasattr(self, '_data'):
            # 情况1：存在实例对象且无验证错误时，序列化实例对象
            if self.instance is not None and not getattr(self, '_errors', None):
                self._data = self.to_representation(self.instance)
            
            # 情况2：存在已验证数据且无错误时，序列化已验证数据
            elif hasattr(self, '_validated_data') and not getattr(self, '_errors', None):
                self._data = self.to_representation(self.validated_data)
            
            # 默认情况：获取初始化数据
            else:
                self._data = self.get_initial()
                
        return self._data


    @property
    def errors(self):
        if not hasattr(self, '_errors'):
            msg = 'You must call `.is_valid()` before accessing `.errors`.'
            raise AssertionError(msg)
        return self._errors

    @property
    def validated_data(self):
        if not hasattr(self, '_validated_data'):
            msg = 'You must call `.is_valid()` before accessing `.validated_data`.'
            raise AssertionError(msg)
        return self._validated_data


# Serializer & ListSerializer classes
# -----------------------------------

class SerializerMetaclass(type):
    """
    序列化器的元类，用于自动收集字段定义

    该元类会在类上创建_declared_fields字典属性，自动收集当前类及其父类中
    所有Field类型的属性，并正确处理字段继承关系

    Attributes:
        _declared_fields: 字典类型，存储字段名与对应Field实例的映射关系
    """

    @classmethod
    def _get_declared_fields(cls, bases, attrs):
        """
        收集当前类和基类中声明的字段定义

        Args:
            bases: tuple类型，当前类的基类元组
            attrs: dict类型，当前类的属性字典

        Returns:
            dict: 排序合并后的字段字典，包含当前类及其基类的所有Field定义，
                键为字段名，值为对应的Field实例
        """
        # 处理当前类定义的字段
        # 从类属性中提取所有Field实例，并按创建顺序排序
        fields = [(field_name, attrs.pop(field_name))
                  for field_name, obj in list(attrs.items())
                  if isinstance(obj, Field)]
        fields.sort(key=lambda x: x[1]._creation_counter)

        # 处理基类继承的字段
        # 使用known集合防止子类字段被父类覆盖，维护多继承时的字段优先级
        known = set(attrs)

        def visit(name):
            """标记字段名为已处理，防止后续重复添加"""
            known.add(name)
            return name

        # 按基类声明顺序逆向收集字段（Python MRO的逆向）
        # 保证后继承的基类字段优先级低于先继承的基类,先收集子类字段，再收集父类字段。
        base_fields = [
            (visit(name), f)
            for base in bases if hasattr(base, '_declared_fields')
            for name, f in base._declared_fields.items() if name not in known
        ]

        # 合并基类字段和当前类字段，基类字段在前
        return dict(base_fields + fields)

    def __new__(cls, name, bases, attrs):
        """
        创建新类时自动处理字段定义

        Args:
            name: str类型，要创建的类名
            bases: tuple类型，基类元组
            attrs: dict类型，类属性字典

        Returns:
            type: 新创建的类实例
        """
        # 在类创建时设置_declared_fields属性
        attrs['_declared_fields'] = cls._get_declared_fields(bases, attrs)
        return super().__new__(cls, name, bases, attrs)



def as_serializer_error(exc):
    assert isinstance(exc, (ValidationError, DjangoValidationError))

    if isinstance(exc, DjangoValidationError):
        detail = get_error_detail(exc)
    else:
        detail = exc.detail

    if isinstance(detail, Mapping):
        # If errors may be a dict we use the standard {key: list of values}.
        # Here we ensure that all the values are *lists* of errors.
        return {
            key: value if isinstance(value, (list, Mapping)) else [value]
            for key, value in detail.items()
        }
    elif isinstance(detail, list):
        # Errors raised as a list are non-field errors.
        return {
            api_settings.NON_FIELD_ERRORS_KEY: detail
        }
    # Errors raised as a string are non-field errors.
    return {
        api_settings.NON_FIELD_ERRORS_KEY: [detail]
    }


class Serializer(BaseSerializer, metaclass=SerializerMetaclass):
    default_error_messages = {
        'invalid': _('Invalid data. Expected a dictionary, but got {datatype}.')
    }

    def set_value(self, dictionary, keys, value):
        """
        在嵌套字典结构中设置指定路径的值，支持多级键创建/更新


        参数:
        dictionary (dict): 要被修改的目标字典对象，会被原地修改
        keys (list): 表示嵌套路径的键列表，空列表表示直接合并value到根字典
        value: 要设置的目标值，可以是任意数据类型或字典对象
        
        返回值:
        无返回值，直接修改输入的dictionary参数
        
        示例:
        set_value({'a': 1}, [], {'b': 2}) -> {'a': 1, 'b': 2}
        set_value({'a': 1}, ['x'], 2) -> {'a': 1, 'x': 2}
        set_value({'a': 1}, ['x', 'y'], 2) -> {'a': 1, 'x': {'y': 2}}
        """
        # 处理空键列表的特殊情况：直接合并value到根字典
        if not keys:
            dictionary.update(value)
            return

        # 遍历除最后一个键之外的所有中间键
        # 自动创建不存在的中间字典结构
        for key in keys[:-1]:
            if key not in dictionary:
                dictionary[key] = {}
            dictionary = dictionary[key]

        # 在最终的嵌套层级设置目标值
        dictionary[keys[-1]] = value


    @cached_property
    def fields(self):
        """
        A dictionary of {field_name: field_instance}.
        """
        # `fields` is evaluated lazily. We do this to ensure that we don't
        # have issues importing modules that use ModelSerializers as fields,
        # even if Django's app-loading stage has not yet run.

        # book_name = serializers.CharField(source='name')
        # 通过BindingDict去绑定book_name与name的映射关系。
        # 如下，这里传入的key是book_name，value是CharField
        fields = BindingDict(self)
        for key, value in self.get_fields().items():
            fields[key] = value
        return fields

    @property
    def _writable_fields(self):
        for field in self.fields.values():
            if not field.read_only:
                yield field

    @property
    def _readable_fields(self):
        for field in self.fields.values():
            if not field.write_only:
                yield field

    def get_fields(self):
        """
        Returns a dictionary of {field_name: field_instance}.
        """
        # Every new serializer is created with a clone of the field instances.
        # This allows users to dynamically modify the fields on a serializer
        # instance without affecting every other serializer instance.
        return copy.deepcopy(self._declared_fields)

    def get_validators(self):
        """
        Returns a list of validator callables.
        """
        # Used by the lazily-evaluated `validators` property.
        meta = getattr(self, 'Meta', None)
        validators = getattr(meta, 'validators', None)
        return list(validators) if validators else []

    def get_initial(self):
        if hasattr(self, 'initial_data'):
            # initial_data may not be a valid type
            if not isinstance(self.initial_data, Mapping):
                return {}

            return {
                field_name: field.get_value(self.initial_data)
                for field_name, field in self.fields.items()
                if (field.get_value(self.initial_data) is not empty) and
                not field.read_only
            }

        return {
            field.field_name: field.get_initial()
            for field in self.fields.values()
            if not field.read_only
        }

    def get_value(self, dictionary):
        # We override the default field access in order to support
        # nested HTML forms.
        if html.is_html_input(dictionary):
            return html.parse_html_dict(dictionary, prefix=self.field_name) or empty
        return dictionary.get(self.field_name, empty)

    def run_validation(self, data=empty):
        """
        执行序列化器的完整验证流程

        Args:
            data: 要验证的原始输入数据，默认为空值标记

        Returns:
            经过清洗和验证的数据，如果输入为空值则直接返回空数据

        Raises:
            ValidationError: 当验证过程中发现错误时抛出
        """
        # 第一阶段：空值检查
        (is_empty_value, data) = self.validate_empty_values(data)
        if is_empty_value:
            return data

        # 第二阶段：数据转换和验证
        # 将原始数据转换为内部表示形式
        value = self.to_internal_value(data)
        
        try:
            # 执行字段级别验证器，可以在内部的Meta类中定义上validators，这样所有的字段都会使用这些验证器
            # 例如：
            # class Meta:
            #     validators = [MyCustomValidator()]
            #
            self.run_validators(value)
            # 执行对象级验证（自定义validate方法）
            value = self.validate(value)
            assert value is not None, '.validate() should return the validated data'
        except (ValidationError, DjangoValidationError) as exc:
            # 统一将验证错误转换为DRF的序列化错误格式
            raise ValidationError(detail=as_serializer_error(exc))

        return value


    def _read_only_defaults(self):
        fields = [
            field for field in self.fields.values()
            if (field.read_only) and (field.default != empty) and (field.source != '*') and ('.' not in field.source)
        ]

        defaults = {}
        for field in fields:
            try:
                default = field.get_default()
            except SkipField:
                continue
            defaults[field.source] = default

        return defaults

    def run_validators(self, value):
        """
        执行字段验证器，处理只读字段的默认值合并逻辑

        Args:
            value (dict/any): 需要验证的输入值。当为字典类型时，会自动合并只读字段的默认值；
                            非字典类型时直接使用原始值进行验证

        Returns:
            None: 该方法没有返回值，验证结果通过抛出 ValidationError 异常来反馈
        """
        # 处理字典类型的输入值：合并只读字段默认值与传入值
        if isinstance(value, dict):
            # 获取只读字段的默认值作为基础字典
            to_validate = self._read_only_defaults()
            # 同时展示只读字段的默认值，并使用传入值覆盖
            to_validate.update(value)
        else:
            # 非字典类型直接使用原始值
            to_validate = value
        # 运行Field级别的验证器
        super().run_validators(to_validate)


    def to_internal_value(self, data):
        """
        将原始数据类型字典转换为内部值字典

        Args:
            data: 原始输入数据，要求为字典类型(Mapping)

        Returns:
            dict: 处理后的字典，包含通过验证的字段数据

        Raises:
            ValidationError: 当输入数据不符合要求或字段验证失败时抛出
        """
        """
        Dict of native values <- Dict of primitive datatypes.
        """
        # 输入类型检查：确保数据为字典类型
        if not isinstance(data, Mapping):
            message = self.error_messages['invalid'].format(
                datatype=type(data).__name__
            )
            raise ValidationError({
                api_settings.NON_FIELD_ERRORS_KEY: [message]
            }, code='invalid')

        # 初始化返回结构和错误容器
        ret = {}
        errors = {}
        # 获取所有可写字段定义
        # fields type: Field
        fields = self._writable_fields 

        # 遍历处理每个字段的验证逻辑
        for field in fields:
            # 获取字段的定制验证方法（如果存在）
            validate_method = getattr(self, 'validate_' + field.field_name, None)
            # 从原始数据中提取字段值
            primitive_value = field.get_value(data)
            try:
                # 执行字段基础验证
                validated_value = field.run_validation(primitive_value)
                # 执行字段自定义验证方法
                if validate_method is not None:
                    validated_value = validate_method(validated_value)
            # 处理不同框架的验证错误类型
            except ValidationError as exc:
                errors[field.field_name] = exc.detail
            except DjangoValidationError as exc:
                errors[field.field_name] = get_error_detail(exc)
            except SkipField:
                pass
            else:
                # 将验证通过的值写入返回字典
                # 通过source_attrs构建基于原始字段的字典。
                self.set_value(ret, field.source_attrs, validated_value)

        # 存在验证错误时抛出聚合异常
        if errors:
            raise ValidationError(errors)

        return ret


    def to_representation(self, instance):
        """
        Object instance -> Dict of primitive datatypes.
        """
        ret = {}
        fields = self._readable_fields

        for field in fields:
            try:
                attribute = field.get_attribute(instance)
            except SkipField:
                continue

            # We skip `to_representation` for `None` values so that fields do
            # not have to explicitly deal with that case.
            #
            # For related fields with `use_pk_only_optimization` we need to
            # resolve the pk value.
            check_for_none = attribute.pk if isinstance(attribute, PKOnlyObject) else attribute
            if check_for_none is None:
                ret[field.field_name] = None
            else:
                ret[field.field_name] = field.to_representation(attribute)

        return ret

    def validate(self, attrs):
        return attrs

    def __repr__(self):
        return representation.serializer_repr(self, indent=1)

    # The following are used for accessing `BoundField` instances on the
    # serializer, for the purposes of presenting a form-like API onto the
    # field values and field errors.

    def __iter__(self):
        for field in self.fields.values():
            yield self[field.field_name]

    def __getitem__(self, key):
        field = self.fields[key]
        value = self.data.get(key)
        error = self.errors.get(key) if hasattr(self, '_errors') else None
        if isinstance(field, Serializer):
            return NestedBoundField(field, value, error)
        if isinstance(field, JSONField):
            return JSONBoundField(field, value, error)
        return BoundField(field, value, error)

    # Include a backlink to the serializer class on return objects.
    # Allows renderers such as HTMLFormRenderer to get the full field info.

    @property
    def data(self):
        ret = super().data
        return ReturnDict(ret, serializer=self)

    @property
    def errors(self):
        ret = super().errors
        if isinstance(ret, list) and len(ret) == 1 and getattr(ret[0], 'code', None) == 'null':
            # Edge case. Provide a more descriptive error than
            # "this field may not be null", when no data is passed.
            detail = ErrorDetail('No data provided', code='null')
            ret = {api_settings.NON_FIELD_ERRORS_KEY: [detail]}
        return ReturnDict(ret, serializer=self)


# There's some replication of `ListField` here,
# but that's probably better than obfuscating the call hierarchy.

class ListSerializer(BaseSerializer):
    child = None
    many = True

    default_error_messages = {
        'not_a_list': _('Expected a list of items but got type "{input_type}".'),
        'empty': _('This list may not be empty.'),
        'max_length': _('Ensure this field has no more than {max_length} elements.'),
        'min_length': _('Ensure this field has at least {min_length} elements.')
    }

    def __init__(self, *args, **kwargs):
        self.child = kwargs.pop('child', copy.deepcopy(self.child))
        self.allow_empty = kwargs.pop('allow_empty', True)
        self.max_length = kwargs.pop('max_length', None)
        self.min_length = kwargs.pop('min_length', None)
        assert self.child is not None, '`child` is a required argument.'
        assert not inspect.isclass(self.child), '`child` has not been instantiated.'
        super().__init__(*args, **kwargs)
        self.child.bind(field_name='', parent=self)

    def get_initial(self):
        if hasattr(self, 'initial_data'):
            return self.to_representation(self.initial_data)
        return []

    def get_value(self, dictionary):
        """
        Given the input dictionary, return the field value.
        """
        # We override the default field access in order to support
        # lists in HTML forms.
        if html.is_html_input(dictionary):
            return html.parse_html_list(dictionary, prefix=self.field_name, default=empty)
        return dictionary.get(self.field_name, empty)

    def run_validation(self, data=empty):
        """
        We override the default `run_validation`, because the validation
        performed by validators and the `.validate()` method should
        be coerced into an error dictionary with a 'non_fields_error' key.
        """
        (is_empty_value, data) = self.validate_empty_values(data)
        if is_empty_value:
            return data

        value = self.to_internal_value(data)
        try:
            self.run_validators(value)
            value = self.validate(value)
            assert value is not None, '.validate() should return the validated data'
        except (ValidationError, DjangoValidationError) as exc:
            raise ValidationError(detail=as_serializer_error(exc))

        return value

    def run_child_validation(self, data):
        """
        Run validation on child serializer.
        You may need to override this method to support multiple updates. For example:

        self.child.instance = self.instance.get(pk=data['id'])
        self.child.initial_data = data
        return super().run_child_validation(data)
        """
        return self.child.run_validation(data)

    def to_internal_value(self, data):
        """
        将原始数据转换为内部表示形式（包含数据验证和格式转换）

        Args:
            data: 需要处理的原始输入数据，可能是HTML表单数据或原始数据类型组成的列表

        Returns:
            list: 由经过验证的字典组成的列表，每个字典包含转换后的内部值

        Raises:
            ValidationError: 当数据不符合以下条件时抛出：
                - 输入不是列表类型
                - 不允许空列表时传入空列表
                - 列表长度超过max_length限制
                - 列表长度不足min_length限制
                - 列表元素验证失败
        """
        # 处理HTML表单输入的预处理逻辑
        if html.is_html_input(data):
            data = html.parse_html_list(data, default=[])

        # 基础类型校验：确保输入是列表类型
        if not isinstance(data, list):
            message = self.error_messages['not_a_list'].format(
                input_type=type(data).__name__
            )
            raise ValidationError({
                api_settings.NON_FIELD_ERRORS_KEY: [message]
            }, code='not_a_list')

        # 空列表校验逻辑
        if not self.allow_empty and len(data) == 0:
            message = self.error_messages['empty']
            raise ValidationError({
                api_settings.NON_FIELD_ERRORS_KEY: [message]
            }, code='empty')

        # 列表长度上限校验
        if self.max_length is not None and len(data) > self.max_length:
            message = self.error_messages['max_length'].format(max_length=self.max_length)
            raise ValidationError({
                api_settings.NON_FIELD_ERRORS_KEY: [message]
            }, code='max_length')

        # 列表长度下限校验
        if self.min_length is not None and len(data) < self.min_length:
            message = self.error_messages['min_length'].format(min_length=self.min_length)
            raise ValidationError({
                api_settings.NON_FIELD_ERRORS_KEY: [message]
            }, code='min_length')

        # 初始化结果容器和错误容器
        ret = []
        errors = []

        # 遍历处理每个列表元素
        for item in data:
            try:
                # 执行子元素级验证
                validated = self.run_child_validation(item)
            except ValidationError as exc:
                errors.append(exc.detail)
            else:
                ret.append(validated)
                errors.append({})

        # 汇总处理过程中产生的错误
        if any(errors):
            raise ValidationError(errors)

        return ret


    def to_representation(self, data):
        """
        List of object instances -> List of dicts of primitive datatypes.
        """
        # Dealing with nested relationships, data can be a Manager,
        # so, first get a queryset from the Manager if needed
        iterable = data.all() if isinstance(data, models.manager.BaseManager) else data

        return [
            self.child.to_representation(item) for item in iterable
        ]

    def validate(self, attrs):
        return attrs

    def update(self, instance, validated_data):
        raise NotImplementedError(
            "Serializers with many=True do not support multiple update by "
            "default, only multiple create. For updates it is unclear how to "
            "deal with insertions and deletions. If you need to support "
            "multiple update, use a `ListSerializer` class and override "
            "`.update()` so you can specify the behavior exactly."
        )

    def create(self, validated_data):
        return [
            self.child.create(attrs) for attrs in validated_data
        ]

    def save(self, **kwargs):
        """
        Save and return a list of object instances.
        """
        # Guard against incorrect use of `serializer.save(commit=False)`
        assert 'commit' not in kwargs, (
            "'commit' is not a valid keyword argument to the 'save()' method. "
            "If you need to access data before committing to the database then "
            "inspect 'serializer.validated_data' instead. "
            "You can also pass additional keyword arguments to 'save()' if you "
            "need to set extra attributes on the saved model instance. "
            "For example: 'serializer.save(owner=request.user)'.'"
        )

        validated_data = [
            {**attrs, **kwargs} for attrs in self.validated_data
        ]

        if self.instance is not None:
            self.instance = self.update(self.instance, validated_data)
            assert self.instance is not None, (
                '`update()` did not return an object instance.'
            )
        else:
            self.instance = self.create(validated_data)
            assert self.instance is not None, (
                '`create()` did not return an object instance.'
            )

        return self.instance

    def is_valid(self, *, raise_exception=False):
        # This implementation is the same as the default,
        # except that we use lists, rather than dicts, as the empty case.
        assert hasattr(self, 'initial_data'), (
            'Cannot call `.is_valid()` as no `data=` keyword argument was '
            'passed when instantiating the serializer instance.'
        )

        if not hasattr(self, '_validated_data'):
            try:
                self._validated_data = self.run_validation(self.initial_data)
            except ValidationError as exc:
                self._validated_data = []
                self._errors = exc.detail
            else:
                self._errors = []

        if self._errors and raise_exception:
            raise ValidationError(self.errors)

        return not bool(self._errors)

    def __repr__(self):
        return representation.list_repr(self, indent=1)

    # Include a backlink to the serializer class on return objects.
    # Allows renderers such as HTMLFormRenderer to get the full field info.

    @property
    def data(self):
        ret = super().data
        return ReturnList(ret, serializer=self)

    @property
    def errors(self):
        ret = super().errors
        if isinstance(ret, list) and len(ret) == 1 and getattr(ret[0], 'code', None) == 'null':
            # Edge case. Provide a more descriptive error than
            # "this field may not be null", when no data is passed.
            detail = ErrorDetail('No data provided', code='null')
            ret = {api_settings.NON_FIELD_ERRORS_KEY: [detail]}
        if isinstance(ret, dict):
            return ReturnDict(ret, serializer=self)
        return ReturnList(ret, serializer=self)


# ModelSerializer & HyperlinkedModelSerializer
# --------------------------------------------

def raise_errors_on_nested_writes(method_name, serializer, validated_data):
    """
    Give explicit errors when users attempt to pass writable nested data.

    If we don't do this explicitly they'd get a less helpful error when
    calling `.save()` on the serializer.

    We don't *automatically* support these sorts of nested writes because
    there are too many ambiguities to define a default behavior.

    Eg. Suppose we have a `UserSerializer` with a nested profile. How should
    we handle the case of an update, where the `profile` relationship does
    not exist? Any of the following might be valid:

    * Raise an application error.
    * Silently ignore the nested part of the update.
    * Automatically create a profile instance.
    """
    ModelClass = serializer.Meta.model
    model_field_info = model_meta.get_field_info(ModelClass)

    # Ensure we don't have a writable nested field. For example:
    #
    # class UserSerializer(ModelSerializer):
    #     ...
    #     profile = ProfileSerializer()
    assert not any(
        isinstance(field, BaseSerializer) and
        (field.source in validated_data) and
        (field.source in model_field_info.relations) and
        isinstance(validated_data[field.source], (list, dict))
        for field in serializer._writable_fields
    ), (
        'The `.{method_name}()` method does not support writable nested '
        'fields by default.\nWrite an explicit `.{method_name}()` method for '
        'serializer `{module}.{class_name}`, or set `read_only=True` on '
        'nested serializer fields.'.format(
            method_name=method_name,
            module=serializer.__class__.__module__,
            class_name=serializer.__class__.__name__
        )
    )

    # Ensure we don't have a writable dotted-source field. For example:
    #
    # class UserSerializer(ModelSerializer):
    #     ...
    #     address = serializer.CharField('profile.address')
    #
    # Though, non-relational fields (e.g., JSONField) are acceptable. For example:
    #
    # class NonRelationalPersonModel(models.Model):
    #     profile = JSONField()
    #
    # class UserSerializer(ModelSerializer):
    #     ...
    #     address = serializer.CharField('profile.address')
    assert not any(
        len(field.source_attrs) > 1 and
        (field.source_attrs[0] in validated_data) and
        (field.source_attrs[0] in model_field_info.relations) and
        isinstance(validated_data[field.source_attrs[0]], (list, dict))
        for field in serializer._writable_fields
    ), (
        'The `.{method_name}()` method does not support writable dotted-source '
        'fields by default.\nWrite an explicit `.{method_name}()` method for '
        'serializer `{module}.{class_name}`, or set `read_only=True` on '
        'dotted-source serializer fields.'.format(
            method_name=method_name,
            module=serializer.__class__.__module__,
            class_name=serializer.__class__.__name__
        )
    )


class ModelSerializer(Serializer):
    """
    A `ModelSerializer` is just a regular `Serializer`, except that:

    * A set of default fields are automatically populated.
    * A set of default validators are automatically populated.
    * Default `.create()` and `.update()` implementations are provided.

    The process of automatically determining a set of serializer fields
    based on the model fields is reasonably complex, but you almost certainly
    don't need to dig into the implementation.

    If the `ModelSerializer` class *doesn't* generate the set of fields that
    you need you should either declare the extra/differing fields explicitly on
    the serializer class, or simply use a `Serializer` class.
    """
    serializer_field_mapping = {
        models.AutoField: IntegerField,
        models.BigIntegerField: IntegerField,
        models.BooleanField: BooleanField,
        models.CharField: CharField,
        models.CommaSeparatedIntegerField: CharField,
        models.DateField: DateField,
        models.DateTimeField: DateTimeField,
        models.DecimalField: DecimalField,
        models.DurationField: DurationField,
        models.EmailField: EmailField,
        models.Field: ModelField,
        models.FileField: FileField,
        models.FloatField: FloatField,
        models.ImageField: ImageField,
        models.IntegerField: IntegerField,
        models.NullBooleanField: BooleanField,
        models.PositiveIntegerField: IntegerField,
        models.PositiveSmallIntegerField: IntegerField,
        models.SlugField: SlugField,
        models.SmallIntegerField: IntegerField,
        models.TextField: CharField,
        models.TimeField: TimeField,
        models.URLField: URLField,
        models.UUIDField: UUIDField,
        models.GenericIPAddressField: IPAddressField,
        models.FilePathField: FilePathField,
    }
    if hasattr(models, 'JSONField'):
        serializer_field_mapping[models.JSONField] = JSONField
    if postgres_fields:
        serializer_field_mapping[postgres_fields.HStoreField] = HStoreField
        serializer_field_mapping[postgres_fields.ArrayField] = ListField
        serializer_field_mapping[postgres_fields.JSONField] = JSONField
    serializer_related_field = PrimaryKeyRelatedField
    serializer_related_to_field = SlugRelatedField
    serializer_url_field = HyperlinkedIdentityField
    serializer_choice_field = ChoiceField

    # The field name for hyperlinked identity fields. Defaults to 'url'.
    # You can modify this using the API setting.
    #
    # Note that if you instead need modify this on a per-serializer basis,
    # you'll also need to ensure you update the `create` method on any generic
    # views, to correctly handle the 'Location' response header for
    # "HTTP 201 Created" responses.
    url_field_name = None

    # Default `create` and `update` behavior...
    def create(self, validated_data):
        """
        We have a bit of extra checking around this in order to provide
        descriptive messages when something goes wrong, but this method is
        essentially just:

            return ExampleModel.objects.create(**validated_data)

        If there are many to many fields present on the instance then they
        cannot be set until the model is instantiated, in which case the
        implementation is like so:

            example_relationship = validated_data.pop('example_relationship')
            instance = ExampleModel.objects.create(**validated_data)
            instance.example_relationship = example_relationship
            return instance

        The default implementation also does not handle nested relationships.
        If you want to support writable nested relationships you'll need
        to write an explicit `.create()` method.
        """
        raise_errors_on_nested_writes('create', self, validated_data)

        ModelClass = self.Meta.model

        # Remove many-to-many relationships from validated_data.
        # They are not valid arguments to the default `.create()` method,
        # as they require that the instance has already been saved.
        info = model_meta.get_field_info(ModelClass)
        many_to_many = {}
        for field_name, relation_info in info.relations.items():
            if relation_info.to_many and (field_name in validated_data):
                many_to_many[field_name] = validated_data.pop(field_name)

        try:
            instance = ModelClass._default_manager.create(**validated_data)
        except TypeError:
            tb = traceback.format_exc()
            msg = (
                'Got a `TypeError` when calling `%s.%s.create()`. '
                'This may be because you have a writable field on the '
                'serializer class that is not a valid argument to '
                '`%s.%s.create()`. You may need to make the field '
                'read-only, or override the %s.create() method to handle '
                'this correctly.\nOriginal exception was:\n %s' %
                (
                    ModelClass.__name__,
                    ModelClass._default_manager.name,
                    ModelClass.__name__,
                    ModelClass._default_manager.name,
                    self.__class__.__name__,
                    tb
                )
            )
            raise TypeError(msg)

        # Save many-to-many relationships after the instance is created.
        if many_to_many:
            for field_name, value in many_to_many.items():
                field = getattr(instance, field_name)
                field.set(value)

        return instance

    def update(self, instance, validated_data):
        raise_errors_on_nested_writes('update', self, validated_data)
        info = model_meta.get_field_info(instance)

        # Simply set each attribute on the instance, and then save it.
        # Note that unlike `.create()` we don't need to treat many-to-many
        # relationships as being a special case. During updates we already
        # have an instance pk for the relationships to be associated with.
        m2m_fields = []
        for attr, value in validated_data.items():
            if attr in info.relations and info.relations[attr].to_many:
                m2m_fields.append((attr, value))
            else:
                setattr(instance, attr, value)

        instance.save()

        # Note that many-to-many fields are set after updating instance.
        # Setting m2m fields triggers signals which could potentially change
        # updated instance and we do not want it to collide with .update()
        for attr, value in m2m_fields:
            field = getattr(instance, attr)
            field.set(value)

        return instance

    # Determine the fields to apply...

    def get_fields(self):
        """
        获取并构建序列化器所需的字段字典。

        该方法负责收集所有显式声明的字段，并根据模型元数据自动生成未声明字段的实例。
        同时处理额外的关键字参数、隐藏字段及深度限制验证。

        Returns:
            dict: 字段名字典，键为字段名称，值为对应的字段实例。
        """

        # 初始化URL字段名为默认值（如果未设置）
        if self.url_field_name is None:
            self.url_field_name = api_settings.URL_FIELD_NAME

        # 元类属性校验
        # 确保序列化器类包含Meta内部类且定义了model属性
        assert hasattr(self, 'Meta'), (
            'Class {serializer_class} missing "Meta" attribute'.format(
                serializer_class=self.__class__.__name__
            )
        )
        assert hasattr(self.Meta, 'model'), (
            'Class {serializer_class} missing "Meta.model" attribute'.format(
                serializer_class=self.__class__.__name__
            )
        )
        # 禁止在抽象模型上使用序列化器
        if model_meta.is_abstract_model(self.Meta.model):
            raise ValueError(
                'Cannot use ModelSerializer with Abstract Models.'
            )

        # 准备基础数据
        # 深拷贝已声明字段防止原始数据被修改
        declared_fields = copy.deepcopy(self._declared_fields)
        # 获取模型引用和嵌套深度配置
        model = getattr(self.Meta, 'model')
        depth = getattr(self.Meta, 'depth', 0)

        # 深度参数校验
        # 确保深度值在0-10的合理范围内
        if depth is not None:
            assert depth >= 0, "'depth' may not be negative."
            assert depth <= 10, "'depth' may not be greater than 10."

        # 模型元数据解析
        # 获取模型字段关系等元信息
        info = model_meta.get_field_info(model)
        # 确定最终要处理的字段名称列表
        field_names = self.get_field_names(declared_fields, info)

        # 扩展参数处理
        # 获取额外参数并处理唯一性约束相关配置
        extra_kwargs = self.get_extra_kwargs()
        extra_kwargs, hidden_fields = self.get_uniqueness_extra_kwargs(
            field_names, declared_fields, extra_kwargs
        )

        # 字段实例化流程
        fields = {}
        for field_name in field_names:
            # 优先使用显式声明的字段
            if field_name in declared_fields:
                fields[field_name] = declared_fields[field_name]
                continue

            # 自动生成字段配置
            # 从扩展参数中获取字段级配置
            extra_field_kwargs = extra_kwargs.get(field_name, {})
            # 确定字段数据源，默认为字段名本身
            source = extra_field_kwargs.get('source', '*')
            if source == '*':
                source = field_name

            # 动态构建字段
            # 根据模型元数据确定字段类型和配置
            field_class, field_kwargs = self.build_field(
                source, info, model, depth
            )
            # 合并全局扩展参数到字段配置
            field_kwargs = self.include_extra_kwargs(
                field_kwargs, extra_field_kwargs
            )
            # 实例化字段对象
            fields[field_name] = field_class(**field_kwargs)

        # 合并隐藏字段
        # 将需要隐藏的特殊字段加入最终字段字典
        fields.update(hidden_fields)

        return fields

    # Methods for determining the set of field names to include...

    def get_field_names(self, declared_fields, info):
        """
        Returns the list of all field names that should be created when
        instantiating this serializer class. This is based on the default
        set of fields, but also takes into account the `Meta.fields` or
        `Meta.exclude` options if they have been specified.
        """
        fields = getattr(self.Meta, 'fields', None)
        exclude = getattr(self.Meta, 'exclude', None)

        if fields and fields != ALL_FIELDS and not isinstance(fields, (list, tuple)):
            raise TypeError(
                'The `fields` option must be a list or tuple or "__all__". '
                'Got %s.' % type(fields).__name__
            )

        if exclude and not isinstance(exclude, (list, tuple)):
            raise TypeError(
                'The `exclude` option must be a list or tuple. Got %s.' %
                type(exclude).__name__
            )

        assert not (fields and exclude), (
            "Cannot set both 'fields' and 'exclude' options on "
            "serializer {serializer_class}.".format(
                serializer_class=self.__class__.__name__
            )
        )

        assert not (fields is None and exclude is None), (
            "Creating a ModelSerializer without either the 'fields' attribute "
            "or the 'exclude' attribute has been deprecated since 3.3.0, "
            "and is now disallowed. Add an explicit fields = '__all__' to the "
            "{serializer_class} serializer.".format(
                serializer_class=self.__class__.__name__
            ),
        )

        if fields == ALL_FIELDS:
            fields = None

        if fields is not None:
            # Ensure that all declared fields have also been included in the
            # `Meta.fields` option.

            # Do not require any fields that are declared in a parent class,
            # in order to allow serializer subclasses to only include
            # a subset of fields.
            required_field_names = set(declared_fields)
            for cls in self.__class__.__bases__:
                required_field_names -= set(getattr(cls, '_declared_fields', []))

            for field_name in required_field_names:
                assert field_name in fields, (
                    "The field '{field_name}' was declared on serializer "
                    "{serializer_class}, but has not been included in the "
                    "'fields' option.".format(
                        field_name=field_name,
                        serializer_class=self.__class__.__name__
                    )
                )
            return fields

        # Use the default set of field names if `Meta.fields` is not specified.
        fields = self.get_default_field_names(declared_fields, info)

        if exclude is not None:
            # If `Meta.exclude` is included, then remove those fields.
            for field_name in exclude:
                assert field_name not in self._declared_fields, (
                    "Cannot both declare the field '{field_name}' and include "
                    "it in the {serializer_class} 'exclude' option. Remove the "
                    "field or, if inherited from a parent serializer, disable "
                    "with `{field_name} = None`."
                    .format(
                        field_name=field_name,
                        serializer_class=self.__class__.__name__
                    )
                )

                assert field_name in fields, (
                    "The field '{field_name}' was included on serializer "
                    "{serializer_class} in the 'exclude' option, but does "
                    "not match any model field.".format(
                        field_name=field_name,
                        serializer_class=self.__class__.__name__
                    )
                )
                fields.remove(field_name)

        return fields

    def get_default_field_names(self, declared_fields, model_info):
        """
        Return the default list of field names that will be used if the
        `Meta.fields` option is not specified.
        """
        return (
            [model_info.pk.name] +
            list(declared_fields) +
            list(model_info.fields) +
            list(model_info.forward_relations)
        )

    # Methods for constructing serializer fields...

    def build_field(self, field_name, info, model_class, nested_depth):
        """
        Return a two tuple of (cls, kwargs) to build a serializer field with.
        """
        if field_name in info.fields_and_pk:
            model_field = info.fields_and_pk[field_name]
            return self.build_standard_field(field_name, model_field)

        elif field_name in info.relations:
            relation_info = info.relations[field_name]
            if not nested_depth:
                return self.build_relational_field(field_name, relation_info)
            else:
                return self.build_nested_field(field_name, relation_info, nested_depth)

        elif hasattr(model_class, field_name):
            return self.build_property_field(field_name, model_class)

        elif field_name == self.url_field_name:
            return self.build_url_field(field_name, model_class)

        return self.build_unknown_field(field_name, model_class)

    def build_standard_field(self, field_name, model_field):
        """
        Create regular model fields.
        """
        field_mapping = ClassLookupDict(self.serializer_field_mapping)

        field_class = field_mapping[model_field]
        field_kwargs = get_field_kwargs(field_name, model_field)

        # Special case to handle when a OneToOneField is also the primary key
        if model_field.one_to_one and model_field.primary_key:
            field_class = self.serializer_related_field
            field_kwargs['queryset'] = model_field.related_model.objects

        if 'choices' in field_kwargs:
            # Fields with choices get coerced into `ChoiceField`
            # instead of using their regular typed field.
            field_class = self.serializer_choice_field
            # Some model fields may introduce kwargs that would not be valid
            # for the choice field. We need to strip these out.
            # Eg. models.DecimalField(max_digits=3, decimal_places=1, choices=DECIMAL_CHOICES)
            valid_kwargs = {
                'read_only', 'write_only',
                'required', 'default', 'initial', 'source',
                'label', 'help_text', 'style',
                'error_messages', 'validators', 'allow_null', 'allow_blank',
                'choices'
            }
            for key in list(field_kwargs):
                if key not in valid_kwargs:
                    field_kwargs.pop(key)

        if not issubclass(field_class, ModelField):
            # `model_field` is only valid for the fallback case of
            # `ModelField`, which is used when no other typed field
            # matched to the model field.
            field_kwargs.pop('model_field', None)

        if not issubclass(field_class, CharField) and not issubclass(field_class, ChoiceField):
            # `allow_blank` is only valid for textual fields.
            field_kwargs.pop('allow_blank', None)

        is_django_jsonfield = hasattr(models, 'JSONField') and isinstance(model_field, models.JSONField)
        if (postgres_fields and isinstance(model_field, postgres_fields.JSONField)) or is_django_jsonfield:
            # Populate the `encoder` argument of `JSONField` instances generated
            # for the model `JSONField`.
            field_kwargs['encoder'] = getattr(model_field, 'encoder', None)
            if is_django_jsonfield:
                field_kwargs['decoder'] = getattr(model_field, 'decoder', None)

        if postgres_fields and isinstance(model_field, postgres_fields.ArrayField):
            # Populate the `child` argument on `ListField` instances generated
            # for the PostgreSQL specific `ArrayField`.
            child_model_field = model_field.base_field
            child_field_class, child_field_kwargs = self.build_standard_field(
                'child', child_model_field
            )
            field_kwargs['child'] = child_field_class(**child_field_kwargs)

        return field_class, field_kwargs

    def build_relational_field(self, field_name, relation_info):
        """
        Create fields for forward and reverse relationships.
        """
        field_class = self.serializer_related_field
        field_kwargs = get_relation_kwargs(field_name, relation_info)

        to_field = field_kwargs.pop('to_field', None)
        if to_field and not relation_info.reverse and not relation_info.related_model._meta.get_field(to_field).primary_key:
            field_kwargs['slug_field'] = to_field
            field_class = self.serializer_related_to_field

        # `view_name` is only valid for hyperlinked relationships.
        if not issubclass(field_class, HyperlinkedRelatedField):
            field_kwargs.pop('view_name', None)

        return field_class, field_kwargs

    def build_nested_field(self, field_name, relation_info, nested_depth):
        """
        Create nested fields for forward and reverse relationships.
        """
        class NestedSerializer(ModelSerializer):
            class Meta:
                model = relation_info.related_model
                depth = nested_depth - 1
                fields = '__all__'

        field_class = NestedSerializer
        field_kwargs = get_nested_relation_kwargs(relation_info)

        return field_class, field_kwargs

    def build_property_field(self, field_name, model_class):
        """
        Create a read only field for model methods and properties.
        """
        field_class = ReadOnlyField
        field_kwargs = {}

        return field_class, field_kwargs

    def build_url_field(self, field_name, model_class):
        """
        Create a field representing the object's own URL.
        """
        field_class = self.serializer_url_field
        field_kwargs = get_url_kwargs(model_class)

        return field_class, field_kwargs

    def build_unknown_field(self, field_name, model_class):
        """
        Raise an error on any unknown fields.
        """
        raise ImproperlyConfigured(
            'Field name `%s` is not valid for model `%s` in `%s.%s`.' %
            (field_name, model_class.__name__, self.__class__.__module__, self.__class__.__name__)
        )

    def include_extra_kwargs(self, kwargs, extra_kwargs):
        """
        Include any 'extra_kwargs' that have been included for this field,
        possibly removing any incompatible existing keyword arguments.
        """
        if extra_kwargs.get('read_only', False):
            for attr in [
                'required', 'default', 'allow_blank', 'min_length',
                'max_length', 'min_value', 'max_value', 'validators', 'queryset'
            ]:
                kwargs.pop(attr, None)

        if extra_kwargs.get('default') and kwargs.get('required') is False:
            kwargs.pop('required')

        if extra_kwargs.get('read_only', kwargs.get('read_only', False)):
            extra_kwargs.pop('required', None)  # Read only fields should always omit the 'required' argument.

        kwargs.update(extra_kwargs)

        return kwargs

    # Methods for determining additional keyword arguments to apply...

    def get_extra_kwargs(self):
        """
        Return a dictionary mapping field names to a dictionary of
        additional keyword arguments.
        """
        extra_kwargs = copy.deepcopy(getattr(self.Meta, 'extra_kwargs', {}))

        read_only_fields = getattr(self.Meta, 'read_only_fields', None)
        if read_only_fields is not None:
            if not isinstance(read_only_fields, (list, tuple)):
                raise TypeError(
                    'The `read_only_fields` option must be a list or tuple. '
                    'Got %s.' % type(read_only_fields).__name__
                )
            for field_name in read_only_fields:
                kwargs = extra_kwargs.get(field_name, {})
                kwargs['read_only'] = True
                extra_kwargs[field_name] = kwargs

        else:
            # Guard against the possible misspelling `readonly_fields` (used
            # by the Django admin and others).
            assert not hasattr(self.Meta, 'readonly_fields'), (
                'Serializer `%s.%s` has field `readonly_fields`; '
                'the correct spelling for the option is `read_only_fields`.' %
                (self.__class__.__module__, self.__class__.__name__)
            )

        return extra_kwargs

    def get_unique_together_constraints(self, model):
        """
        Returns iterator of (fields, queryset, condition_fields, condition),
        each entry describes an unique together constraint on `fields` in `queryset`
        with respect of constraint's `condition`.
        """
        for parent_class in [model] + list(model._meta.parents):
            for unique_together in parent_class._meta.unique_together:
                yield unique_together, model._default_manager, [], None
            for constraint in parent_class._meta.constraints:
                if isinstance(constraint, models.UniqueConstraint) and len(constraint.fields) > 1:
                    if constraint.condition is None:
                        condition_fields = []
                    else:
                        condition_fields = list(get_referenced_base_fields_from_q(constraint.condition))
                    yield (constraint.fields, model._default_manager, condition_fields, constraint.condition)

    def get_uniqueness_extra_kwargs(self, field_names, declared_fields, extra_kwargs):
        """
        Return any additional field options that need to be included as a
        result of uniqueness constraints on the model. This is returned as
        a two-tuple of:

        ('dict of updated extra kwargs', 'mapping of hidden fields')
        """
        if getattr(self.Meta, 'validators', None) is not None:
            return (extra_kwargs, {})

        model = getattr(self.Meta, 'model')
        model_fields = self._get_model_fields(
            field_names, declared_fields, extra_kwargs
        )

        # Determine if we need any additional `HiddenField` or extra keyword
        # arguments to deal with `unique_for` dates that are required to
        # be in the input data in order to validate it.
        unique_constraint_names = set()

        for model_field in model_fields.values():
            # Include each of the `unique_for_*` field names.
            unique_constraint_names |= {model_field.unique_for_date, model_field.unique_for_month,
                                        model_field.unique_for_year}

        unique_constraint_names -= {None}

        # Include each of the `unique_together` and `UniqueConstraint` field names,
        # so long as all the field names are included on the serializer.
        for unique_together_list, queryset, condition_fields, condition in self.get_unique_together_constraints(model):
            unique_together_list_and_condition_fields = set(unique_together_list) | set(condition_fields)
            if set(field_names).issuperset(unique_together_list_and_condition_fields):
                unique_constraint_names |= unique_together_list_and_condition_fields

        # Now we have all the field names that have uniqueness constraints
        # applied, we can add the extra 'required=...' or 'default=...'
        # arguments that are appropriate to these fields, or add a `HiddenField` for it.
        hidden_fields = {}
        uniqueness_extra_kwargs = {}

        for unique_constraint_name in unique_constraint_names:
            # Get the model field that is referred too.
            unique_constraint_field = model._meta.get_field(unique_constraint_name)

            if getattr(unique_constraint_field, 'auto_now_add', None):
                default = CreateOnlyDefault(timezone.now)
            elif getattr(unique_constraint_field, 'auto_now', None):
                default = timezone.now
            elif unique_constraint_field.has_default():
                default = unique_constraint_field.default
            elif unique_constraint_field.null:
                default = None
            else:
                default = empty

            if unique_constraint_name in model_fields:
                # The corresponding field is present in the serializer
                if default is empty:
                    uniqueness_extra_kwargs[unique_constraint_name] = {'required': True}
                else:
                    uniqueness_extra_kwargs[unique_constraint_name] = {'default': default}
            elif default is not empty:
                # The corresponding field is not present in the
                # serializer. We have a default to use for it, so
                # add in a hidden field that populates it.
                hidden_fields[unique_constraint_name] = HiddenField(default=default)

        # Update `extra_kwargs` with any new options.
        for key, value in uniqueness_extra_kwargs.items():
            if key in extra_kwargs:
                value.update(extra_kwargs[key])
            extra_kwargs[key] = value

        return extra_kwargs, hidden_fields

    def _get_model_fields(self, field_names, declared_fields, extra_kwargs):
        """
        Returns all the model fields that are being mapped to by fields
        on the serializer class.
        Returned as a dict of 'model field name' -> 'model field'.
        Used internally by `get_uniqueness_field_options`.
        """
        model = getattr(self.Meta, 'model')
        model_fields = {}

        for field_name in field_names:
            if field_name in declared_fields:
                # If the field is declared on the serializer
                field = declared_fields[field_name]
                source = field.source or field_name
            else:
                try:
                    source = extra_kwargs[field_name]['source']
                except KeyError:
                    source = field_name

            if '.' in source or source == '*':
                # Model fields will always have a simple source mapping,
                # they can't be nested attribute lookups.
                continue

            with contextlib.suppress(FieldDoesNotExist):
                field = model._meta.get_field(source)
                if isinstance(field, DjangoModelField):
                    model_fields[source] = field

        return model_fields

    # Determine the validators to apply...

    def get_validators(self):
        """
        Determine the set of validators to use when instantiating serializer.
        """
        # If the validators have been declared explicitly then use that.
        validators = getattr(getattr(self, 'Meta', None), 'validators', None)
        if validators is not None:
            return list(validators)

        # Otherwise use the default set of validators.
        return (
            self.get_unique_together_validators() +
            self.get_unique_for_date_validators()
        )

    def get_unique_together_validators(self):
        """
        Determine a default set of validators for any unique_together constraints.
        """
        # The field names we're passing though here only include fields
        # which may map onto a model field. Any dotted field name lookups
        # cannot map to a field, and must be a traversal, so we're not
        # including those.
        field_sources = {
            field.field_name: field.source for field in self._writable_fields
            if (field.source != '*') and ('.' not in field.source)
        }

        # Special Case: Add read_only fields with defaults.
        field_sources.update({
            field.field_name: field.source for field in self.fields.values()
            if (field.read_only) and (field.default != empty) and (field.source != '*') and ('.' not in field.source)
        })

        # Invert so we can find the serializer field names that correspond to
        # the model field names in the unique_together sets. This also allows
        # us to check that multiple fields don't map to the same source.
        source_map = defaultdict(list)
        for name, source in field_sources.items():
            source_map[source].append(name)

        # Note that we make sure to check `unique_together` both on the
        # base model class, but also on any parent classes.
        validators = []
        for unique_together, queryset, condition_fields, condition in self.get_unique_together_constraints(self.Meta.model):
            # Skip if serializer does not map to all unique together sources
            unique_together_and_condition_fields = set(unique_together) | set(condition_fields)
            if not set(source_map).issuperset(unique_together_and_condition_fields):
                continue

            for source in unique_together_and_condition_fields:
                assert len(source_map[source]) == 1, (
                    "Unable to create `UniqueTogetherValidator` for "
                    "`{model}.{field}` as `{serializer}` has multiple "
                    "fields ({fields}) that map to this model field. "
                    "Either remove the extra fields, or override "
                    "`Meta.validators` with a `UniqueTogetherValidator` "
                    "using the desired field names."
                    .format(
                        model=self.Meta.model.__name__,
                        serializer=self.__class__.__name__,
                        field=source,
                        fields=', '.join(source_map[source]),
                    )
                )

            field_names = tuple(source_map[f][0] for f in unique_together)
            validator = UniqueTogetherValidator(
                queryset=queryset,
                fields=field_names,
                condition_fields=tuple(source_map[f][0] for f in condition_fields),
                condition=condition,
            )
            validators.append(validator)
        return validators

    def get_unique_for_date_validators(self):
        """
        Determine a default set of validators for the following constraints:

        * unique_for_date
        * unique_for_month
        * unique_for_year
        """
        info = model_meta.get_field_info(self.Meta.model)
        default_manager = self.Meta.model._default_manager
        field_names = [field.source for field in self.fields.values()]

        validators = []

        for field_name, field in info.fields_and_pk.items():
            if field.unique_for_date and field_name in field_names:
                validator = UniqueForDateValidator(
                    queryset=default_manager,
                    field=field_name,
                    date_field=field.unique_for_date
                )
                validators.append(validator)

            if field.unique_for_month and field_name in field_names:
                validator = UniqueForMonthValidator(
                    queryset=default_manager,
                    field=field_name,
                    date_field=field.unique_for_month
                )
                validators.append(validator)

            if field.unique_for_year and field_name in field_names:
                validator = UniqueForYearValidator(
                    queryset=default_manager,
                    field=field_name,
                    date_field=field.unique_for_year
                )
                validators.append(validator)

        return validators


class HyperlinkedModelSerializer(ModelSerializer):
    """
    A type of `ModelSerializer` that uses hyperlinked relationships instead
    of primary key relationships. Specifically:

    * A 'url' field is included instead of the 'id' field.
    * Relationships to other instances are hyperlinks, instead of primary keys.
    """
    serializer_related_field = HyperlinkedRelatedField

    def get_default_field_names(self, declared_fields, model_info):
        """
        Return the default list of field names that will be used if the
        `Meta.fields` option is not specified.
        """
        return (
            [self.url_field_name] +
            list(declared_fields) +
            list(model_info.fields) +
            list(model_info.forward_relations)
        )

    def build_nested_field(self, field_name, relation_info, nested_depth):
        """
        Create nested fields for forward and reverse relationships.
        """
        class NestedSerializer(HyperlinkedModelSerializer):
            class Meta:
                model = relation_info.related_model
                depth = nested_depth - 1
                fields = '__all__'

        field_class = NestedSerializer
        field_kwargs = get_nested_relation_kwargs(relation_info)

        return field_class, field_kwargs
