"""
Utility functions to return a formatted name and description for a given view.
"""
import re

from django.utils.encoding import force_str
from django.utils.html import escape
from django.utils.safestring import mark_safe

from rest_framework.compat import apply_markdown


def remove_trailing_string(content, trailing):
    """
    Strip trailing component `trailing` from `content` if it exists.
    Used when generating names from view classes.
    """
    if content.endswith(trailing) and content != trailing:
        return content[:-len(trailing)]
    return content


def dedent(content):
    """
    Remove leading indent from a block of text.
    Used when generating descriptions from docstrings.

    Note that python's `textwrap.dedent` doesn't quite cut it,
    as it fails to dedent multiline docstrings that include
    unindented text on the initial line.
    """
    content = force_str(content)
    lines = [line for line in content.splitlines()[1:] if line.lstrip()]

    # unindent the content if needed
    if lines:
        whitespace_counts = min([len(line) - len(line.lstrip(' ')) for line in lines])
        tab_counts = min([len(line) - len(line.lstrip('\t')) for line in lines])
        if whitespace_counts:
            whitespace_pattern = '^' + (' ' * whitespace_counts)
            content = re.sub(re.compile(whitespace_pattern, re.MULTILINE), '', content)
        elif tab_counts:
            whitespace_pattern = '^' + ('\t' * tab_counts)
            content = re.sub(re.compile(whitespace_pattern, re.MULTILINE), '', content)
    return content.strip()


def camelcase_to_spaces(content):
    """
    Translate 'CamelCaseNames' to 'Camel Case Names'.
    Used when generating names from view classes.
    """
    camelcase_boundary = '(((?<=[a-z])[A-Z])|([A-Z](?![A-Z]|$)))'
    content = re.sub(camelcase_boundary, ' \\1', content).strip()
    return ' '.join(content.split('_')).title()


def markup_description(description):
    """
    Apply HTML markup to the given description.
    """
    if apply_markdown:
        description = apply_markdown(description)
    else:
        description = escape(description).replace('\n', '<br />')
        description = '<p>' + description + '</p>'
    return mark_safe(description)


class lazy_format:
    """
    延迟字符串格式化直到实际需要时，适用于格式字符串或参数需要惰性求值的场景

    避免使用Django的惰性实现，以提升性能

    Attributes:
        format_string: 待格式化的原始字符串模板
        args: 格式化所需的位置参数
        kwargs: 格式化所需的关键字参数
        result: 缓存格式化后的最终结果
    """
    __slots__ = ('format_string', 'args', 'kwargs', 'result')

    def __init__(self, format_string, *args, **kwargs):
        """
        初始化延迟格式化对象

        Args:
            format_string: 需要延迟格式化的字符串模板
            *args: 字符串模板的位置参数
            **kwargs: 字符串模板的关键字参数
        """
        self.result = None
        self.format_string = format_string
        self.args = args
        self.kwargs = kwargs

    def __str__(self):
        """
        执行实际格式化操作并返回结果字符串

        首次调用时会进行实际格式化计算，后续调用直接返回缓存结果。
        格式化完成后会清理原始参数以释放内存
        """
        # 首次访问时执行实际格式化操作
        if self.result is None:
            self.result = self.format_string.format(*self.args, **self.kwargs)
            # 清理原始参数释放引用
            self.format_string, self.args, self.kwargs = None, None, None
        return self.result

    def __mod__(self, value):
        """
        支持使用%运算符进行格式化

        用于兼容旧式字符串格式化操作，实际调用标准字符串的%格式化方法
        """
        return str(self) % value
