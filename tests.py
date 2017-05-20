# -*- coding: utf-8 -*-
"""
    jinja2htmlcompress
    ~~~~~~~~~~~~~~~~~~

    A Jinja2 extension that eliminates useless whitespace at template
    compilation time without extra overhead.

    :copyright: (c) 2011 by Armin Ronacher.
    :license: BSD, see LICENSE for more details.
"""

try:
    import unittest2 as ut
except ImportError:
    import unittest as ut

from jinja2 import Environment
from jinja2htmlcompress import (
    HTMLCompress, SelectiveHTMLCompress, InvertedSelectiveHTMLCompress,
    DEFAULT_ACTIVE_KEY as DA_KEY,
)

class BaseCompressorTest(ut.TestCase):

    maxDiff = None

    compressor = None

    def render(self, content, policies=None, **kwds):
        """
        helper to render content using specified compressor
        """
        env = Environment(extensions=[self.compressor])
        if policies:
            env.policies.update(policies)
        tmpl = env.from_string(content)
        return tmpl.render(**kwds)

class HTMLCompressTest(BaseCompressorTest):

    compressor = HTMLCompress

    def test_sample_1(self):
        result = self.render('''\
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
                <pre>
                    Preformatted text
                        Indented
                </pre>
                <li><a href="{{ href }}">{{ title }}</a><br>Test   Foo
                <li><a href="{{ href }}">{{ title }}</a><img src=test.png>
              </body>
            </html>
        ''', title=42, href='index.html')
        self.assertEqual(result, '''\
<html><head><title>42</title></head><script type=text/javascript>
                if (foo < 42) {
                  document.write('Foo < Bar');
                }
              </script><body><pre>
                    Preformatted text
                        Indented
                </pre><li><a href="index.html">42</a><br>Test Foo<li><a href="index.html">42</a><img src=test.png></body></html>''')

    def test_policy_unset(self):
        self.assertEqual(self.render('''<span>  foo  bar  </span>'''),
                         '''<span>foo bar</span>''')

    def test_policy_true(self):
        self.assertEqual(self.render('''<span>  foo  bar  </span>''', policies={DA_KEY: True}),
                         '''<span>foo bar</span>''')

    def test_policy_false(self):
        self.assertEqual(self.render('''<span>  foo  bar  </span>''', policies={DA_KEY: False}),
                         '''<span>  foo  bar  </span>''')

    def test_nested(self):
        result = self.render('''
    {% strip %}
<span>   foo  
    {% strip false %}
        <span>   bar   {% strip true %}
                <span>   baz    </span>
        {% endstrip %}   </span>
{% endstrip %}
''')
        self.assertEqual(result, ''' <span>foo
        <span>   bar   <span>baz</span>   </span>
''')


class SelectiveHTMLCompressTest(BaseCompressorTest):

    compressor = SelectiveHTMLCompress

    def test_sample_1(self):
        result = self.render('''
        Normal   <span>    unchanged </span>   stuff
        {% strip %}Stripped <span class=foo  >   test   </span>
        <a href="foo">  test </a> {{ foo }}
        Normal <stuff>   again {{ foo }}  </stuff>
        <p>
          Foo<br>Bar
          Baz
        <p>
          Moep    <span>Test</span>    Moep
        </p>
        {% endstrip %}''', foo=42)

        self.assertEqual(result, '''
        Normal   <span>    unchanged </span>   stuff
        Stripped <span class=foo>test</span><a href="foo">test </a> 42 Normal <stuff>again 42</stuff>\
<p>Foo<br>Bar Baz<p>Moep<span>Test</span>Moep</p>''')

    def test_policy_unset(self):
        self.assertEqual(self.render('''<span>  foo  bar  </span>'''),
                         '''<span>  foo  bar  </span>''')

    def test_policy_true(self):
        self.assertEqual(self.render('''<span>  foo  bar  </span>''', policies={DA_KEY: True}),
                         '''<span>foo bar</span>''')

    def test_policy_false(self):
        self.assertEqual(self.render('''<span>  foo  bar  </span>''', policies={DA_KEY: False}),
                         '''<span>  foo  bar  </span>''')


class InvertedHTMLCompressTest(BaseCompressorTest):

    compressor = InvertedSelectiveHTMLCompress

    def test_sample_1(self):
        result = self.render('''
        {% unstrip %}
        Normal   <span>    unchanged </span>   stuff
        {% endunstrip %}

        Stripped <span class=foo  >   test   </span>
        <a href="foo">  test </a> {{ foo }}
        Normal <stuff>   again {{ foo }}  </stuff>
        <p>
          Foo<br>Bar
          Baz
        <p>
          Moep    <span>Test</span>    Moep
        </p>
    ''', foo=42)

        self.assertEqual(result, '''
        Normal   <span>    unchanged </span>   stuff
         Stripped <span class=foo>test</span><a href="foo">test </a> 42 Normal <stuff>again 42</stuff>\
<p>Foo<br>Bar Baz<p>Moep<span>Test</span>Moep</p>''')
