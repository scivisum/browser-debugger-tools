from setuptools import setup, find_packages


extra = dict(
    install_requires=[
        "requests",
        "websocket",
    ]
)

PACKAGES = find_packages(exclude=(
    "devtoolstestsite",
    "devtoolsutils",
    "devtoolschrome.tests*"
))

setup(
    name="pydevtoolschrome",
    version="1.0.0",
    packages=PACKAGES,
    license=open("LICENSE.txt").read(),
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown'
)
