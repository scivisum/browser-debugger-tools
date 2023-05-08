from setuptools import setup, find_packages


requires = [
        "requests",
        "websocket-client",
        "typing",
]


PACKAGES = find_packages(include="browserdebuggertools*")

setup(
    name="browserdebuggertools",
    version="6.0.3",
    python_requires='>=3.8',
    packages=PACKAGES,
    install_requires=requires,
    license="GNU General Public License v3",
    description="A client which calls remote web browser debugger methods",
    long_description_content_type="text/markdown",
    long_description=open("README.md").read(),
    url="https://github.com/scivisum/browser-debugger-tools",
    author="ThinkTribe LTD",
    author_email="rd@scivisum.co.uk",
    classifiers=[
        'Intended Audience :: Developers',
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.8",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent"
    ],
)
