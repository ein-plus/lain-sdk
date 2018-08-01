from setuptools import setup, find_packages
from lain_sdk import __version__


requirements = [
    'six>=1.9.0',
    'future>=0.16.0',
    'Jinja2==2.7.3',
    'PyYAML>=3.12',
    'enum34;python_version<"3.4"',
    'requests>=2.6.1',
    'docker==2.6.1',
    'jsonschema==2.5.1',
]


setup(
    name="einplus_lain_sdk",
    version=__version__,
    packages=find_packages(),
    include_package_data=True,
    data_files=[
    ],
    scripts=['lain_release'],
    install_requires=requirements,
)
