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


class HTMLCompress(Extension):

    def normalize(self, value):
        value = re.sub(r'\s*<', '<', value)
        return re.sub(r'>\s*', '>', value)

    def filter_stream(self, stream):
        for token in stream:
            if token.type != 'data':
                yield token
                continue
            yield Token(token.lineno, 'data', self.normalize(token.value))


def test():
    from jinja2 import Environment
    env = Environment(extensions=[HTMLCompress], autoescape=True)
    tmpl = env.from_string('''
        <html>
          <head>
            <title>{{ title }}</title>
          </head>
          <body>
            <li><a href="{{ href }}">{{ title }}</a></li>
          </body>
        </html>
    ''')
    print tmpl.render(title=42, href='index.html')


if __name__ == '__main__':
    test()
