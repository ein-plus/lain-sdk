# -*- coding: utf-8 -*-

from os import path

import pytest

PWD = path.dirname(path.realpath(__file__))
FIXTURE_DATA_PATH = path.join(PWD, 'data')


@pytest.fixture
def old_prepare_yaml():
    yaml_file = path.join(FIXTURE_DATA_PATH, 'old_prepare.yaml')
    with open(yaml_file) as f:
        meta_yaml = f.read()
    return meta_yaml


@pytest.fixture
def new_prepare_yaml():
    yaml_file = path.join(FIXTURE_DATA_PATH, 'new_prepare.yaml')
    with open(yaml_file) as f:
        meta_yaml = f.read()
    return meta_yaml


@pytest.fixture
def release_yaml():
    yaml_file = path.join(FIXTURE_DATA_PATH, 'release.yaml')
    with open(yaml_file) as f:
        meta_yaml = f.read()
    return meta_yaml
