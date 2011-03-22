# -*- coding: utf-8 -*-
"""
    jinja2htmlcompress
    ~~~~~~~~~~~~~~~~~~

    A Jinja2 extension that eliminates useless whitespace at template
    compilation time without extra overhead.

    :copyright: (c) 2011 by Armin Ronacher.
    :license: BSD, see LICENSE for more details.
"""
import re
from jinja2.ext import Extension
from jinja2.lexer import Token, describe_token
from jinja2 import TemplateSyntaxError


_tag_re = re.compile(r'(?:<(/?)([a-zA-Z0-9_-]+)\s*|(>\s*))(?s)')


class HTMLCompress(Extension):
    isolated_tags = frozenset(['script', 'style', 'pre', 'textarea'])

    def isolated(self, stack):
        for tag in reversed(stack):
            if tag in self.isolated_tags:
                return True
        return False

    def normalize(self, token, stack, stream):
        pos = 0
        buffer = []
        def write_data(value):
            if not self.isolated(stack):
                value = value.strip()
            buffer.append(value)

        for match in _tag_re.finditer(token.value):
            closes, tag, sole = match.groups()
            preamble = token.value[pos:match.start()]
            write_data(preamble)
            if sole:
                write_data(sole)
            else:
                buffer.append(match.group())
                if closes:
                    if stack.pop() != tag:
                        raise TemplateSyntaxError('HTML has to be balanced '
                            'when htmlcompress extension is active',
                            token.lineno, stream.name, stream.filename)
                else:
                    stack.append(tag)
            pos = match.end()

        write_data(token.value[pos:])
        return u''.join(buffer)

    def filter_stream(self, stream):
        stack = []
        for token in stream:
            if token.type != 'data':
                yield token
                continue
            value = self.normalize(token, stack, stream)
            yield Token(token.lineno, 'data', value)


class SelectiveHTMLCompress(HTMLCompress):

    def filter_stream(self, stream):
        def fail(msg):
            raise TemplateSyntaxError(msg, stream.current.lineno,
                                      stream.name, stream.filename)
        stack = []
        strip_depth = 0
        while 1:
            if stream.current.type == 'block_begin':
                if stream.look().test('name:strip') or \
                   stream.look().test('name:endstrip'):
                    stream.skip()
                    if stream.current.value == 'strip':
                        strip_depth += 1
                    else:
                        strip_depth -= 1
                        if strip_depth < 0:
                            fail('Unexpected tag endstrip')
                    stream.skip()
                    if stream.current.type != 'block_end':
                        fail('expected end of block, got %s' %
                             describe_token(stream.current))
                    stream.skip()
            if strip_depth > 0 and stream.current.type == 'data':
                value = self.normalize(stream.current, stack, stream)
                yield Token(stream.current.lineno, 'data', value)
            else:
                yield stream.current
            stream.next()


def test():
    from jinja2 import Environment
    env = Environment(extensions=[HTMLCompress])
    tmpl = env.from_string('''
        <html>
          <head>
            <title>{{ title }}</title>
          </head>
          <script type=text/javascript>
            if (foo < 42) {
              document.write('Foo < Bar');
            }
          </script>
          <body>
            <li><a href="{{ href }}">{{ title }}</a></li>
          </body>
        </html>
    ''')
    print tmpl.render(title=42, href='index.html')

    env = Environment(extensions=[SelectiveHTMLCompress])
    tmpl = env.from_string('''
        Normal   <span>  unchanged </span> stuff
        {% strip %}Stripped <span class=foo  >   test   </span>
        <a href="foo">  test </a> {{ foo }}
        {% endstrip %}
        Normal <stuff>   again {{ foo }}  </stuff>
    ''')
    print tmpl.render(foo=42)


if __name__ == '__main__':
    test()
