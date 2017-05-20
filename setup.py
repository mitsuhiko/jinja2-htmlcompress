#!/usr/bin/env python
"""
jinja2htmlcompress setup script
"""
#=============================================================================
# imports
#=============================================================================
from setuptools import setup, find_packages

#=============================================================================
# static text
#=============================================================================
SUMMARY = "a Jinja2 extension that removes whitespace between HTML tags."

DESCRIPTION = open("README").read()

KEYWORDS = "jinja2"

CLASSIFIERS = """
Intended Audience :: Developers
Operating System :: OS Independent
Programming Language :: Python :: 2
Programming Language :: Python :: 3
License :: OSI Approved :: BSD License
Topic :: Software Development :: Libraries
""".strip().splitlines()

#=============================================================================
# setup
#=============================================================================
setup(
    # metadata
    name="jinja2htmlcompress",
    version="1.0",

    author="Armin Ronacher",
    author_email="armin.ronacher@active-4.com",
    url="https://github.com/mitsuhiko/jinja2-htmlcompress",

    description=SUMMARY,
    long_description=DESCRIPTION,
    keywords=KEYWORDS,
    classifiers=CLASSIFIERS,

    # package info
    packages=find_packages(),
    package_data={},
)

#=============================================================================
# eof
#=============================================================================
