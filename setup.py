try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

setup(
    name="mini-syndicate",
    version="0.0.4",
    author="Tony Garnock-Jones",
    author_email="tonyg@leastfixedpoint.com",
    license="GNU General Public License v3 or later (GPLv3+)",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
        "Programming Language :: Python :: 3",
    ],
    packages=["syndicate", "syndicate.mini"],
    url="https://github.com/syndicate-lang/mini-syndicate-py",
    description="Syndicate-like library for integrating Python with the Syndicate ecosystem",
    install_requires=['websockets', 'preserves'],
    python_requires=">=3.6, <4",
)
