from setuptools import setup, find_packages


extra = dict(
    install_requires=[
        "requests",
        "websocket",
    ]
)

PACKAGES = find_packages(include="browserdebuggertools*")

setup(
    name="browserdebuggertools",
    version="1.0.0",
    packages=PACKAGES,
    license=open("LICENSE.txt").read(),
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown'
)
