

  -- jinja2-htmlcompress

    a Jinja2 extension that removes whitespace between HTML tags.

    Example usage:

      env = Environment(extensions=['jinja2htmlcompress.HTMLCompress'])

    How does it work?  It throws away all whitespace between HTML tags
    it can find at runtime.  It will however preserve pre, textarea, style
    and script tags because this kinda makes sense.  In order to force
    whitespace you can use ``{{ " " }}``.

    Unlike filters that work at template runtime, this remotes whitespace
    at compile time and does not add an overhead in template execution.

    What if you only want to selective strip stuff?

      env = Environment(extensions=['jinja2htmlcompress.SelectiveHTMLCompress'])

    And then mark blocks with ``{% strip %}``:

      {% strip %} ... {% endstrip %}

