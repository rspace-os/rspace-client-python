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
    version='1.3.2',
    description='A client which helps calling RSpace APIs',
    long_description=long_description,
    url='https://github.com/rspace-os/rspace-client-python',
    author='Research Innovations Ltd',
    author_email='s1310787@sms.ed.ac.uk',
    license='Apache Software License',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Libraries',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
    ],
    keywords='rspace api client research space',
    packages=find_packages(exclude=['examples']),
    install_requires=['requests', 'six'],
    extras_require={
        'dev': [],
        'test': [],
    }
)
