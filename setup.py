"""A setuptools based setup module.
"""

from setuptools import setup, find_packages
from codecs import open
from os import path

here = path.abspath(path.dirname(__file__))

with open(path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='rspace-client',
    version='1.6.0-alpha',
    description='A client which helps calling RSpace APIs',
    long_description_content_type='text/markdown',
    url='https://github.com/rspace-os/rspace-client-python',
    author='Research Innovations Ltd',
    author_email='richard@researchspace.com',
    license='Apache Software License',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Libraries',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
    ],
    keywords='rspace api client researchspace eln',
    packages=find_packages(exclude=['examples']),
    install_requires=['requests', 'six','BeautifulSoup4'],
    extras_require={
        'dev': [],
        'test': [],
    }
)
