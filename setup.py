from pathlib import Path
from setuptools import setup, find_packages

README = Path("README.md")
long_description = README.read_text(encoding="utf-8") if README.exists() else ""

setup(
    name="superalloy-rag",
    version="0.1.0",
    description="Retrieval-augmented generation tool for nickel-based superalloys",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="",
    packages=find_packages(exclude=("tests", "docs")),
    include_package_data=True,
    python_requires=">=3.8",
    install_requires=[
        "weaviate-client>=4.0.0",
        "requests>=2.0.0",
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    license="MIT",
)