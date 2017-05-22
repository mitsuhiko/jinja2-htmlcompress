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


def _compile_implicit_close_map(source):
    result = {}
    for keys, value in source.items():
        value = set(value.split())
        for key in keys.split():
            result[key] = value
    return result


#: policy key controlling whether this defaults to active globally
DEFAULT_ACTIVE_KEY = "htmlcompress.default_active"

#: special value used by implicit_close_map
LAST_CHILD = "#last-child"


class HTMLCompress(Extension):
    """Compression always on"""

    # NOTE: All of the following taken from HTML5 spec,
    #       mainly the element types & optional tags sections:
    #           http://w3c.github.io/html/syntax.html#writing-html-documents-elements
    #           http://w3c.github.io/html/syntax.html#optional-start-and-end-tags
    #
    #       Where noted, additional rules outside of the spec have been added
    #       in order to making parsing for resilient to odd ordering from template logic.

    #: set of tags whose contents will never be stripped;
    #: this is set of "raw text" and "escapable raw text" elements from HTML5 sec 8.1.2;
    #: as well as the PRE element (since whitespace also matters there)
    isolated_elements = set("script style textarea title pre".split())

    #: set of void (self-closing) elements; per HTML5 sec 8.1.2
    void_elements = set("area base br col embed hr img input link "
                        "meta param source track wbr".split())

    # #: set of tags that are block elements, and will always break inline text flow
    # #: TODO: find canonical source in HTML5 spec
    # block_elements = set("blockquote dd div dl dt form h1 h2 h3 h4 h5 h6 "
    #                      "li ol p pre table tbody td tfoot th thead tr tr ul".split())

    #: dict of tags that can be implicitly closed; maps tag -> set of following tags
    #: that are allowed to implicitly close it.  special value "#last-child" means
    #: tag can be implicitly closed if it's the last child of parent.
    #: taken from HTML5 sec 8.1.2.4
    implicit_close_map = _compile_implicit_close_map({
        # NOTE: for easy of definition, compile helper turns keys with spaces
        #       into multiple keys, and values treated as space-separated sets.

        "li": "li #last-child",

        # NOTE: "#last-child" not part of spec for DT tag
        "dt dd": "dt dd #last-child",

        # NOTE: "p" element can also be closed if "#last-child", but has special conditions
        #       that are encoded as part of allow_implicit_close_if_last_child()
        "p": "address article aside blockquote details div dl fieldset figcaption "
             "figure footer form h1 h2 h3 h4 h5 h6 header hr main menu nav ol "
             "p pre section table ul",

        "rt rp": "rt rp,#last-child",

        "option": "option optgroup #last-child",
        "optgroup": "optgroup #last-child",

        "menuitem": "menuitem hr menu #last-child",

        # TODO: colgroup can autoclose if not followed by space or comment
        #       For now, working around that by listed all common table elements.
        #       none of the following values are technically part of spec.
        "colgroup": "thead tfoot tbody tr th td #last-child",

        # TODO: caption can autoclose if not followed by space or comment

        # NOTE: all the following are part of spec:
        #       * thead: "#last-child", duplicate THEAD
        #       * tbody: "thead", duplicate TBODY
        #       * tfoot: "thead", "tbody", duplicate TFOOT
        "thead tbody tfoot": "thead tbody tfoot #last-child",

        # NOTE: TBODY, THEAD, TFOOT not part of spec
        "tr": "tbody thead tfoot tr #last-child",

        # NOTE: TBODY, THEAD, TFOOT not part of spec
        "th td": "tbody thead tfoot td th #last-child",
    })

    #: tags don't allow implicit close for "P:last-child"
    #: taken from HTML5 sec 8.1.2.4
    p_no_implicit_close_inside_elements = set("a audio del ins map noscript video".split())

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

    def allow_implicit_close_before(self, tag, next_tag):
        """
        test if HTML spec allows <tag> to be implicitly closed
        when followed by <next_tag>.
        """
        following_tags = self.implicit_close_map.get(tag)
        return following_tags and next_tag in following_tags

    def allow_implicit_close_if_last_child(self, tag, parent_tag):
        """
        test if HTML5 spec allows <tag> to implicitly closed 
        if it's the last element in parent.
        """
        if tag == "p":
            return parent_tag not in self.p_no_implicit_close_inside_elements
        return self.allow_implicit_close_before(tag, LAST_CHILD)

    def enter_tag(self, tag, ctx):
        """
        register opening of new tag
        """
        # implicitly close all tags that can be implicitly closed when followed by <tag>
        while ctx.stack and self.allow_implicit_close_before(ctx.stack[-1], tag):
            self.leave_tag(ctx.stack[-1], ctx)

        # if tag isn't self-closing, add it to stack
        if tag not in self.void_elements:
            ctx.stack.append(tag)

    def leave_tag(self, tag, ctx):
        """
        roll back stack to explicitly close <tag>
        """
        stack = ctx.stack
        end = len(stack)
        while end > 0:
            end -= 1
            other_tag = stack[end]

            # found match -- explicitly close this tag, and implicitly close all child tags
            if other_tag == tag:
                del stack[end:]
                return

            # if <other tag> doesn't allow implicit closing, don't bother searching
            # for <tag> further up hierarchy.  just assume <tag> had implicit end,
            # or was improperly unclosed, and leave stack unchanged.
            parent_tag = stack[end-1] if end else None
            if not self.allow_implicit_close_if_last_child(other_tag, parent_tag):
                return

        # <tag> not found in stack
        ctx.fail('Tried to leave %r tag, but something closed it already' % tag)

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
