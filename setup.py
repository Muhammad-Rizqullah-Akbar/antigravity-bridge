from setuptools import setup, find_packages

setup(
    name="antigravity-bridge",
    version="1.0.0",
    description="Universal bridge connecting Hermes Agent with Google Antigravity models",
    author="Muhammad Rizqullah Akbar",
    author_email="inirizqullahakbar@gmail.com",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[],
    entry_points={
        "console_scripts": [
            "agb=antigravity_bridge.cli:main",
            "agb-connect=antigravity_bridge.cli:init_cmd",
            "antigravity-bridge=antigravity_bridge.cli:main",
        ],
    },
)
