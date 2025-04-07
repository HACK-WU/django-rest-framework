# Serializer 序列化器

## 序列化器执行流程

```python
from rest_framework import serializers

class PeopleSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    age = serializers.IntegerField()

zhang_san = {
    "name": "zhangsan",
    "age": 20
}

zhangsan_serializer = PeopleSerializer(data=zhang_san)
zhangsan_serializer.is_valid()
print(zhangsan_serializer.data)
# >> {'name': 'zhangsan', 'age': 20}
```

### Serializer 的实例化流程

```mermaid
sequenceDiagram
    participant C as SerializerMetaclass 
    participant B as BaseSerializer
    participant A as Serializer
    participant D as ListSerilizer

    C->>C:_get_declared_fields<br>获取定义的字段：self._declared_fields
    C->>B:None
    B->>B:self.initial_data=data<br>原始数据赋值给initial_data
    critical  否序列化多个对象
        B->>B:  "many" in kwargs?

    option "NO"
        B->>A: return Serializer

    option "yes"
        B->>D: return ListSerializer
    end


```

### Serializer序列化器data数据校验流程(is_valid)

#### 1、简易流程图

```mermaid
flowchart TD
    Start([Start])-->A["_validate_data=run_validation(initial_data)"]
    A-->B{ValidationError?}
    B-->|Yes|C[errors=exc]-->G["_validate_data={}"]
    B-->|No|D["errors={}"]
    G-->E["return len(errors)"]
    D-->E
    E-->End([End])

```

#### 2、详细校验流程

```mermaid
sequenceDiagram
    participant A as is_valid
    participant B as run_validation 
    participant C as to_internal_value
    participant D as run_validators
    participant E as validate 
    
    A->>B:data
    
    B->>C:param data:转为内部值
    C->>C:fields = self._writable_fields<br>获取到可写字段
    loop fields<br>进行字段校验
    C->>C:ret={}
    C->>C:primitive_value=filed.get_value(data)<br>获取原始值
    C->>C:validate_data=field.run_validation(primitive_value)<br>字段级别校验
    C->>C:validata_data=validate_method(validate_data)<br>使用自定义方法对字段进行校验
    C->>C:set_value(ret,valitda_data)<br>将校验后的字段保存到ret中
    end 
    C->>C: retun ret: 将ret作为最终数据返回

    C->>B:return data
    B->>D:param data:字段级别校验
    B->>E:param data:全局校验器
    activate  E
    E->>B:return data
    deactivate  E 
    B->>A: return data

    A->>A:_valitedate_data=data<br>最终校验后的数据保存在_validate_data中

    
    
```

### Serializer.data 获取数据流程

```mermaid
sequenceDiagram
    participant A as data
    participant B as to_representation

    break 检查initial_data是否已被校验
        A->>A: init_data存在<br>但是_validate_data不存在
        A->>A: show error message
    end

    critical 检查instance 模型示例是否存在
        A->>A: self.instance is not None?
    option yes
        A->>A: data=self.instance
    option no
        A->>A: data=self._validate_data
    end

    A->>B:param data: 转为外部值
    B->>B:ret={}
    B->>B:fields = self._readable_fields<br>获取可读字段
    loop fileds
        B->>B:attribute = field.get_attribute(data)<br>获取字段值
        B->>B:ret[field.field_name] = field.to_representation(attribute)<br>字段级别，转为外部值，并保存到ret中
    end
    B->>A: return ret<br>返回最终数据ret
    
```







