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
from warnings import warn

assert next  # fail early under pre-py26

from jinja2.ext import Extension
from jinja2.lexer import Token, describe_token
from jinja2 import TemplateSyntaxError

#: regex used to find tag heads ("<tag" or "</tag") and tag tails (">")
_tag_re = re.compile(r'''
    (?:
        <
        (?P<closes>/?)
        (?P<tag>[a-zA-Z0-9_-]+)
        # NOTE: important NOT to strip trailing space,
        #       so it becomes part of preamble of tail porition
        |
        (?P<tail>>\s*)
    )
    ''', re.X | re.S | re.U)

#: regex used to normalize all whitespace
_ws_normalize_re = re.compile(r'\s+', re.U)


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



class StreamProcessContext(object):
    """
    Helper class which handles (loosely) parsing HTML state, and stripping whitespace 
    from tokens.
    """

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

    #: set of tags that don't need ANY whitespace around them preserved.
    #: this includes all the block elements on
    #:      https://developer.mozilla.org/en-US/docs/Web/HTML/Block-level_elements
    #: plus table-related tags, HTML, HEAD, TITLE, and SCRIPT
    spaceless_elements = set(
        "address article aside blockquote body canvas dd div dl dt fieldset "
        "figcaption figure footer form h1 h2 h3 h4 h5 h6 head header hgroup hr "
        "html li main nav noscript ol output p pre section script "
        "table thead title tbody tfoot tr td th ul video".split())
    spaceless_elements |= void_elements

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

    def __init__(self, ext, stream):
        self.ext = ext  # HTMLCompress instance we're bound to
        self.stream = stream  # reference to TokenStream
        self.token = None  # current data token we're parsing html for
        self.stack = []  # stack of html tags we're within
        self.last_tag = None  # set to tag name encountered
        self.last_closed = False  # if last marker was closing marker
        self.in_marker = False  # if parsed "<tag" or "</tag>", but not end ">" marker

    def fail(self, message, token=None):
        if token is None:
            token = self.token
            assert token
        raise TemplateSyntaxError(message, token.lineno,
                                  self.stream.name, self.stream.filename)

    def can_compress(self):
        """
        test if stripping should be allowed for current stack state.
        false if within any tag where whitespace is important (e.g. PRE)
        """
        return self.isolated_elements.isdisjoint(self.stack)

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

    def enter_tag(self, tag):
        """
        register opening of new tag
        """
        # implicitly close all tags that can be implicitly closed when followed by <tag>
        stack = self.stack
        while stack and self.allow_implicit_close_before(stack[-1], tag):
            self.leave_tag(stack[-1])

        # if tag isn't self-closing, add it to stack
        if tag not in self.void_elements:
            stack.append(tag)

    def leave_tag(self, tag):
        """
        roll back stack to explicitly close <tag>
        """
        stack = self.stack
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
        self.fail('Tried to leave %r tag, but something closed it already' % tag)

    def _feed(self, source, strip_leading_space=False):
        """
        helper for normalize() -- takes in source string,
        parses into chunks, advances tag stack, and yields space-compressed chunks.
        """
        # TODO: this doesn't handle html comments & CDATA, so tags w/in these blocks may confuse it.
        # TODO: handle implicit start tags (e.g. colgroup)
        pos = 0
        compress_spaces = _ws_normalize_re.sub
        can_compress = self.can_compress()

        for match in _tag_re.finditer(source):
            closes, tag, tail = match.group("closes", "tag", "tail")
            end = match.end()

            if tail:
                # found end of tag marker (">") -- content will be attr=value pairs since
                # start of tag, ">", and optional trailing space.
                assert not (closes or tag)
                if can_compress:
                    # preamble should be all "attr=value" pairs since header of tag marker.
                    # if it's all spaces, can strip it -- otherwise need to preserve
                    # leading space between tag & attrs
                    preamble = source[pos:match.start()].rstrip()

                    # For inline tags, we want to preserve 1 space after closing tag marker.
                    # For all other cases, can strip trailing space.
                    content = match.group()
                    if not self.last_closed or self.last_tag in self.spaceless_elements:
                        content = content.rstrip()
                    yield compress_spaces(" ", preamble + content)
                else:
                    yield source[pos:end]

            else:
                # found start of tag marker ("<tag")
                # preamble should be non-tag content since last marker.
                tag = tag.lower()
                if can_compress:
                    # Can strip leading whitespace if followed a tag marker,
                    # but if it's at start of source, we can't know if it's needed
                    preamble = source[pos:match.start()]
                    if pos or strip_leading_space:
                        preamble = preamble.lstrip()

                    # For inline tags, we want to preserve at least one space before their opening
                    # marker.  For all other cases, can strip trailing space from preamble.
                    if closes or tag in self.spaceless_elements:
                        preamble = preamble.rstrip()

                    # if content ends with a space, we want to let tail end code handle it...
                    # can strip space if there's no attrs in between.
                    yield compress_spaces(" ", preamble + match.group())
                else:
                    yield source[pos:end]

                # update tag stack & related state
                (closes and self.leave_tag or self.enter_tag)(tag)
                can_compress = self.can_compress()
                self.last_closed = closes
                self.last_tag = tag

            self.in_marker = not tail
            pos = end

        content = source[pos:]
        if can_compress:
            # XXX: can we strip anything here?
            content = compress_spaces(" ", content)
        yield content

    def normalize(self, token, **kwds):
        """
        given data token, parse & strip whitespace
        from it's contents using html-aware parser.
        """
        self.token = token
        return u''.join(self._feed(token.value, **kwds))


class HTMLCompress(Extension):
    """
    Compression always on
    """

    #: whether class should default to active (override by policy)
    default_active = True

    def get_policy_key(self, key, default=None):
        """
        helper to read key from policies dict.
        """
        # NOTE: policy dict not added until jinja 2.9
        policies = getattr(self.environment, "policies", None) or {}
        return policies.get(key, default)

    def active_for_stream(self, stream):
        """
        test if stripping should be enabled by default for specified template
        """
        # TODO: check stream.filename, and only activate for certain exts, ala autoescape.
        return self.get_policy_key(DEFAULT_ACTIVE_KEY, self.default_active)

    def filter_stream(self, stream):
        """
        filter template token stream -- 
        recognizes & removes ``{% strip %}`` and related tags,
        and strips whitespace from data tokens per current 'strip' state.
        """

        # FIXME: Current lexer-level approach allows strip blocks to "cross" other blocks...
        #        e.g. "{% strip %} ... {% if %} ... {% endstrip %} ... {% endif %}".
        #        a parser-level approach would fix this; any existing usages of that type
        #        may throw an error in the future.
        #
        #        Additionally, the current html psuedo-parser approach may fail to parse
        #        the tag hierarchy correctly in cases such as duplicate open tags,
        #        e.g. "{% if ... %} <a> ... {% else } <a> ... {% endif %} ... </a>",
        #        or strip tags that cross tag hierarchy boundaries,
        #        e.g. "<a> ... {% strip %} ... </a> ... {% endstrip %}"
        #
        #        At a minimum, this code should try to detect & warn user about these cases.

        ctx = StreamProcessContext(self, stream)
        stack = []
        active = default_active = self.active_for_stream(stream)

        #: flag if last token was recognized as not requiring normalize() to preserve leading spaces
        strip_leading_space = stream.skip_if("initial")

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
                        ctx.fail('Unexpected tag endstrip', token=peek_next)
                    stream.skip(2)
                    stream.expect("block_end")
                    stack.pop()
                    active = stack[-1] if stack else default_active

                elif stream.look().test('name:unstrip'):
                    # {% unstrip %}
                    warn("`{% unstrip %}` blocks are deprecated, use `{% strip false %}` instead",
                         DeprecationWarning)
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
            if current.type == "data":
                if active:
                    value = ctx.normalize(current, strip_leading_space=strip_leading_space)
                    yield Token(current.lineno, 'data', value)
                else:
                    yield current
                    value = current.value
                strip_leading_space = (value and value[-1].isspace())
            else:
                yield current
                # XXX: would be easier at parser level, could skip over comment nodes;
                #      handle if/thens better, etc.
                strip_leading_space = False

            next(stream)


# XXX: deprecate in favor of HTMLCompress + setting policy['htmlcompress.default_active'] = False?
class SelectiveHTMLCompress(HTMLCompress):
    """Compression off by default; on inside {% strip %} {% endstrip %} tags"""

    default_active = False

# deprecated alias
InvertedSelectiveHTMLCompress = HTMLCompress
