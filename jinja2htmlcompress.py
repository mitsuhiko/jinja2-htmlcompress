# -*- coding: utf-8 -*-
"""
    jinja2htmlcompress
    ~~~~~~~~~~~~~~~~~~

    A Jinja2 extension that eliminates useless whitespace at template
    compilation time without extra overhead.

    :copyright: (c) 2011 by Armin Ronacher.
    :license: BSD, see LICENSE for more details.
"""
from __future__ import print_function
import re
import sys
import os
from warnings import warn

PY2 = sys.version_info < (3,0)
irange = xrange if PY2 else range
assert next  # fail early under pre-py26

from jinja2.ext import Extension
from jinja2.lexer import Token, describe_token
from jinja2 import TemplateSyntaxError



_tag_re = re.compile(r'(?:<(/?)([a-zA-Z0-9_-]+)\s*|(>\s*))(?s)')
_ws_normalize_re = re.compile(r'[ \t\r\n]+')


class StreamProcessContext(object):

    def __init__(self, stream):
        self.stream = stream
        self.token = None
        self.stack = []

    def fail(self, message):
        raise TemplateSyntaxError(message, self.token.lineno,
                                  self.stream.name, self.stream.filename)


def _make_dict_from_listing(listing):
    rv = {}
    for keys, value in listing:
        for key in keys:
            rv[key] = value
    return rv

#: policy key controlling whether this defaults to active globally
DEFAULT_ACTIVE_KEY = "htmlcompress.default_active"


class HTMLCompress(Extension):
    """Compression always on"""

    isolated_elements = set(['script', 'style', 'noscript', 'textarea', 'pre'])
    void_elements = set(['br', 'img', 'area', 'hr', 'param', 'input',
                         'embed', 'col'])
    block_elements = set(['div', 'p', 'form', 'ul', 'ol', 'li', 'table', 'tr',
                          'tbody', 'thead', 'tfoot', 'tr', 'td', 'th', 'dl',
                          'dt', 'dd', 'blockquote', 'h1', 'h2', 'h3', 'h4',
                          'h5', 'h6'])
    breaking_rules = _make_dict_from_listing([
        (['p'], set(['#block'])),
        (['li'], set(['li'])),
        (['td', 'th'], set(['td', 'th', 'tr', 'tbody', 'thead', 'tfoot'])),
        (['tr'], set(['tr', 'tbody', 'thead', 'tfoot'])),
        (['thead', 'tbody', 'tfoot'], set(['thead', 'tbody', 'tfoot'])),
        (['dd', 'dt'], set(['dl', 'dt', 'dd']))
    ])

    #: whether class should default to active (override by policy)
    default_active = True

    def get_policy_key(self, key, default=None):
        # NOTE: policy dict not added until jinja 2.9
        policies = getattr(self.environment, "policies", None) or {}
        return policies.get(key, default)

    def active_for_stream(self, stream):
        # TODO: check stream.filename, and only activate for certain exts, ala autoescape.
        return self.get_policy_key(DEFAULT_ACTIVE_KEY, self.default_active)

    def is_isolated(self, stack):
        for tag in reversed(stack):
            if tag in self.isolated_elements:
                return True
        return False

    def is_breaking(self, tag, other_tag):
        breaking = self.breaking_rules.get(other_tag)
        return breaking and (tag in breaking or
            ('#block' in breaking and tag in self.block_elements))

    def enter_tag(self, tag, ctx):
        while ctx.stack and self.is_breaking(tag, ctx.stack[-1]):
            self.leave_tag(ctx.stack[-1], ctx)
        if tag not in self.void_elements:
            ctx.stack.append(tag)

    def leave_tag(self, tag, ctx):
        if not ctx.stack:
            ctx.fail('Tried to leave "%s" but something closed '
                     'it already' % tag)
        if tag == ctx.stack[-1]:
            ctx.stack.pop()
            return
        for idx, other_tag in enumerate(reversed(ctx.stack)):
            if other_tag == tag:
                for num in irange(idx + 1):
                    ctx.stack.pop()
            elif not self.breaking_rules.get(other_tag):
                break

    def normalize(self, ctx):
        pos = 0
        buffer = []
        def write_data(value):
            if not self.is_isolated(ctx.stack):
                if not re.match(r'.+\w\s$', value):
                    if value[-2:] == "  ":
                        value = value.strip()
                value = _ws_normalize_re.sub(' ', value)
            buffer.append(value)

        for match in _tag_re.finditer(ctx.token.value):
            closes, tag, sole = match.groups()
            preamble = ctx.token.value[pos:match.start()]
            write_data(preamble)
            if sole:
                write_data(sole)
            else:
                buffer.append(match.group())
                (closes and self.leave_tag or self.enter_tag)(tag, ctx)
            pos = match.end()

        write_data(ctx.token.value[pos:])
        return u''.join(buffer)

    def filter_stream(self, stream):
        ctx = StreamProcessContext(stream)
        stack = []
        active = default_active = self.active_for_stream(stream)

        while 1:
            if stream.current.type == 'block_begin':

                peek_next = stream.look()

                if peek_next.test('name:strip'):
                    # {% strip [true|false] %}
                    stream.skip(2)
                    if stream.skip_if('name:false'):
                        enable = False
                    elif stream.skip_if('name:true'):
                        enable = True
                    else:
                        # implicit enable
                        enable = True
                    stream.expect("block_end")
                    stack.append(enable)
                    active = enable

                elif peek_next.test('name:endstrip'):
                    # {% endstrip %}
                    if not (stack and stack[-1] is not None):
                        ctx.fail('Unexpected tag endstrip')
                    stream.skip(2)
                    stream.expect("block_end")
                    stack.pop()
                    active = stack[-1] if stack else default_active

                elif stream.look().test('name:unstrip'):
                    # {% unstrip %}
                    warn("`{% unstrip %}` blocks are deprecated, use `{% strip false %}` instead", DeprecationWarning)
                    stream.skip(2)
                    stream.expect("block_end")
                    stack.append(None)
                    active = None

                elif stream.look().test('name:endunstrip'):
                    # {% endunstrip %}
                    if not (stack and stack[-1] is None):
                        ctx.fail('Unexpected tag endunstrip')
                    stream.skip(2)
                    stream.expect("block_end")
                    stack.pop()
                    active = stack[-1] if stack else default_active

            current = stream.current
            if active and current.type == 'data':
                ctx.token = current
                value = self.normalize(ctx)
                yield Token(current.lineno, 'data', value)
            else:
                yield current

            next(stream)


# XXX: deprecate in favor of HTMLCompress + setting policy['htmlcompress.default_active'] = False?
class SelectiveHTMLCompress(HTMLCompress):
    """Compression off by default; on inside {% strip %} {% endstrip %} tags"""

    default_active = False

# deprecated alias
InvertedSelectiveHTMLCompress = HTMLCompress
