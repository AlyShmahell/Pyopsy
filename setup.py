from os.path import exists

from setuptools import find_packages, setup

setup(
    name="pyopsy",
    version="3.0.0",
    author="Aly Shmahell",
    url="https://github.com/AlyShmahell/Pyopsy",
    description="The definitive concise python profiler, with minimal dependency and a small footprint, it is feature-complete with a cli, a web UI and dedicated file-logging.",
    long_description=(
        open("README.md", encoding="utf-8").read() if exists("README.md") else ""
    ),
    long_description_content_type="text/markdown",
    packages=find_packages(include=["pyopsy", "pyopsy.*"]),
    package_data={"pyopsy.serve": ["assets/*"]},
    include_package_data=True,
    install_requires=[
        "psutil==7.1.0",
    ],
    python_requires=">=3.12.9",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: BSD-3-Clause License",
        "Operating System :: OS Independent",
    ],
)
