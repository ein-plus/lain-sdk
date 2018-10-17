# -*- coding: utf-8 -*-

from lain_sdk.lain_yaml import LainYaml

YAML = 'tests/lain.yaml'


class TestLainYaml:

    def test_vars_accessible(self):
        y = LainYaml(data=open(YAML).read(), ignore_prepare=True)
        assert y.appname == 'hello'
        assert y.build.base == 'golang'
        assert tuple(y.build.script) == ('go build -o hello', )
        assert tuple(y.release.script) == ()
        assert y.release.dest_base == 'ubuntu'
        assert len(y.release.copy) == 1
        assert y.release.copy[0]['src'] == 'hello'
        assert y.release.copy[0]['dest'] == '/usr/bin/hello'
        assert tuple(y.test.script) == ('go test', )
        assert tuple(y.procs['web'].cmd) == ('hello', )
        assert y.procs['web'].setup_time == 40
        assert y.procs['web'].kill_timeout == 30

    def test_prepare_act(self):
        y = LainYaml(lain_yaml_path=YAML, ignore_prepare=True)
        assert y.act is True
        assert len(y.img_names) == 5
        assert len(y.img_temps) == 5
        assert len(y.img_builders) == 5
        assert tuple(y.release.script) == ()
        assert y.release.dest_base == 'ubuntu'
        assert len(y.release.copy) == 1
        assert y.release.copy[0]['src'] == 'hello'
        assert y.release.copy[0]['dest'] == '/usr/bin/hello'
