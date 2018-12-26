from setuptools import setup, find_packages
from lain_sdk import __version__


requirements = [
    'six>=1.9.0',
    'future>=0.16.0',
    'Jinja2>=2.7.3',
    'PyYAML>=3.12',
    'enum34;python_version<"3.4"',
    'docker>=2.6.1',
    'requests',
    'jsonschema>=2.5.1',
    'marshmallow>=3.0.0b16',
    'marshmallow_enum>=1.4.1',
    'python-box>=3.2.1',
    'humanfriendly>=4.16.1',
]


setup(
    name="einplus_lain_sdk",
    version=__version__,
    packages=find_packages(exclude=('scripts')),
    include_package_data=True,
    install_requires=requirements,
)
