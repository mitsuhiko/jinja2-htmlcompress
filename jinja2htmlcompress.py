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
from jinja2.lexer import Token
from jinja2 import TemplateSyntaxError


_tag_re = re.compile(r'<(/?)([a-zA-Z0-9_-]+)')


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
            closes, tag = match.groups()
            preamble = token.value[pos:match.start()]
            write_data(preamble)
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


def test():
    from jinja2 import Environment
    env = Environment(extensions=[HTMLCompress], autoescape=True)
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


if __name__ == '__main__':
    test()
